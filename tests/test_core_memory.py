"""Tests for openclaw memory operations."""

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.memory import (
    MAX_MEMORY_CONTENT_BYTES,
    MEMORY_TOP_LEVEL_FILES,
    MemoryOpError,
    _cleanup_artifacts,
    _extract_failure_message,
    _parse_memory_info_stdout,
    _resolve_agent_with_memory,
    _resolve_openclaw_agent,
    _validate_agent_name,
    _validate_memory_filename,
    delete_memory_files,
    get_memory_info,
    read_memory_file,
    write_memory_file,
)


# ----- validation -----------------------------------------------------------


class TestValidation:
    def test_agent_name_accepts_typical_unix_user(self):
        _validate_agent_name("opc-work")

    def test_agent_name_rejects_uppercase(self):
        with pytest.raises(MemoryOpError):
            _validate_agent_name("OPC-Work")

    def test_agent_name_rejects_path_traversal(self):
        with pytest.raises(MemoryOpError):
            _validate_agent_name("../etc")

    def test_filename_accepts_top_level(self):
        _validate_memory_filename("SOUL.md")

    def test_filename_accepts_daily(self):
        _validate_memory_filename("memory/2026-05-09.md")

    def test_filename_rejects_traversal(self):
        with pytest.raises(MemoryOpError):
            _validate_memory_filename("../../../etc/passwd")

    def test_filename_rejects_nested_path(self):
        with pytest.raises(MemoryOpError):
            _validate_memory_filename("a/b/c.md")

    def test_filename_rejects_absolute_path(self):
        with pytest.raises(MemoryOpError):
            _validate_memory_filename("/etc/hosts")

    @pytest.mark.parametrize(
        "name",
        [
            "..",
            "../etc",
            "memory/..",
            "../memory",
            ".",
            "./SOUL.md",
            "",
            "SOUL\x00.md",  # null byte
            "..\\etc",  # backslash separator (regex rejects)
            "%2e%2e/etc",  # url-encoded (regex rejects '%')
            "memory/SOUL.md/extra",  # too-deep path (regex rejects)
        ],
    )
    def test_filename_rejects_traversal_components(self, name: str):
        with pytest.raises(MemoryOpError):
            _validate_memory_filename(name)

    def test_agent_name_rejects_empty(self):
        with pytest.raises(MemoryOpError):
            _validate_agent_name("")

    def test_agent_name_accepts_max_length(self):
        # 32 chars: 1 letter + 31 trailing
        _validate_agent_name("a" + "0" * 31)

    def test_agent_name_rejects_over_max_length(self):
        with pytest.raises(MemoryOpError):
            _validate_agent_name("a" + "0" * 32)


# ----- top-level constants --------------------------------------------------


class TestConstants:
    def test_openclaw_top_level_files_match_workspace_layout(self):
        assert set(MEMORY_TOP_LEVEL_FILES["openclaw"]) == {
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "TOOLS.md",
        }

    def test_hermes_top_level_files_match_three_file_set(self):
        # Hermes surfaces three files via memory_info: MEMORY.md, USER.md
        # (both under ~/.hermes/memories/) and SOUL.md (at ~/.hermes/).
        assert set(MEMORY_TOP_LEVEL_FILES["hermes"]) == {
            "MEMORY.md",
            "USER.md",
            "SOUL.md",
        }

    def test_zeroclaw_top_level_files_cover_seven_personality_files(self):
        # Per issue #358 W8, zeroclaw must surface the seven personality MD
        # files rendered by configure (BOOTSTRAP.md is runtime-generated +
        # self-deleting and must NOT appear here).
        assert set(MEMORY_TOP_LEVEL_FILES["zeroclaw"]) == {
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "AGENTS.md",
            "TOOLS.md",
            "MEMORY.md",
            "HEARTBEAT.md",
        }
        assert "BOOTSTRAP.md" not in MEMORY_TOP_LEVEL_FILES["zeroclaw"]


# ----- _resolve_openclaw_agent ---------------------------------------------


def _host(agents: dict) -> dict:
    return {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "port": 22,
        "user": "xclm",
        "agents": agents,
    }


class TestResolveOpenclawAgent:
    def test_returns_none_when_host_missing(self):
        with patch("clawrium.core.memory.get_host", return_value=None):
            host, reason = _resolve_openclaw_agent("nope", "anything")
        assert host is None
        assert "host 'nope' not found" in reason

    def test_returns_none_when_agents_field_invalid(self):
        host = {"hostname": "192.168.1.100", "agents": []}
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason = _resolve_openclaw_agent("192.168.1.100", "x")
        assert h is None
        assert "no agents registry" in reason

    def test_resolves_by_dict_key(self):
        host = _host(
            {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "name": "work",
                }
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        assert result[0] is not None
        assert result[1] == "opc-work"

    def test_resolves_by_short_name(self):
        host = _host(
            {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "name": "work",
                }
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_openclaw_agent("192.168.1.100", "work")
        assert result[0] is not None
        assert result[1] == "opc-work"

    def test_returns_none_when_agent_missing(self):
        host = _host({})
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason = _resolve_openclaw_agent("192.168.1.100", "ghost")
        assert h is None
        assert "not found" in reason

    def test_returns_none_when_agent_is_wrong_type(self):
        host = _host(
            {"zeroclaw": {"type": "zeroclaw", "agent_name": "zc", "name": "zc"}}
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, _ = _resolve_openclaw_agent("192.168.1.100", "zeroclaw")
        assert h is None

    def test_returns_none_when_multiple_matches(self):
        host = _host(
            {
                "opc-a": {"type": "openclaw", "agent_name": "opc-a", "name": "shared"},
                "opc-b": {"type": "openclaw", "agent_name": "opc-b", "name": "shared"},
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason = _resolve_openclaw_agent("192.168.1.100", "shared")
        assert h is None
        assert "multiple openclaw agents" in reason

    @pytest.mark.parametrize("status", ["installing", "failed"])
    def test_rejects_non_installed_status(self, status: str):
        host = _host(
            {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "status": status,
                }
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        assert h is None
        # Reason must distinguish "not ready" from "not found" so users
        # debugging a still-installing agent don't chase a red herring.
        assert "not ready" in reason
        assert status in reason

    def test_rejects_unknown_future_status(self):
        # Allowlist behavior: any non-'installed' status is rejected even
        # if it isn't 'installing' or 'failed'. Guards against future
        # status additions silently passing through.
        host = _host(
            {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "status": "removing",
                }
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        assert h is None
        assert "removing" in reason

    def test_accepts_explicitly_installed_status(self):
        host = _host(
            {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "status": "installed",
                }
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        assert result[0] is not None and result[1] == "opc-work"

    def test_accepts_record_without_status_field(self):
        # Legacy/test records without status are treated as installed.
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        assert result[0] is not None


# ----- _parse_memory_info_stdout -------------------------------------------


class TestParseMemoryInfoStdout:
    def test_parses_workspace_path_and_top(self):
        stdout = (
            "WORKSPACE_PATH=/home/opc-work/.openclaw/workspace\n"
            "TOP SOUL.md 100\n"
            "TOP IDENTITY.md 50\n"
            "TOP USER.md -1\n"
            "TOP TOOLS.md 200\n"
            "DAILY 2026-05-09.md 300\n"
        )
        parsed = _parse_memory_info_stdout(stdout)
        assert parsed["workspace_path"] == "/home/opc-work/.openclaw/workspace"
        assert parsed["top"] == [
            ("SOUL.md", 100),
            ("IDENTITY.md", 50),
            ("USER.md", -1),
            ("TOOLS.md", 200),
        ]
        assert parsed["daily"] == [("2026-05-09.md", 300)]

    def test_handles_empty_stdout(self):
        parsed = _parse_memory_info_stdout("")
        assert parsed == {"workspace_path": "", "top": [], "daily": []}

    def test_skips_malformed_lines(self):
        stdout = "TOP\nDAILY only-name\nTOP weird notanumber\n"
        parsed = _parse_memory_info_stdout(stdout)
        assert parsed["top"] == []
        assert parsed["daily"] == []


# ----- _extract_failure_message --------------------------------------------


class TestExtractFailureMessage:
    def test_returns_default_when_no_failed_events(self):
        result = MagicMock()
        result.events = [
            {"event": "runner_on_ok", "event_data": {"res": {"msg": "ignored"}}}
        ]
        assert _extract_failure_message(result, "fallback") == "fallback"

    def test_returns_msg_field_when_present(self):
        result = MagicMock()
        result.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "boom", "stderr": "extra"}},
            }
        ]
        assert _extract_failure_message(result, "fallback") == "boom"

    def test_falls_back_to_stderr_when_msg_missing(self):
        result = MagicMock()
        result.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"stderr": "stderr-value"}},
            }
        ]
        assert _extract_failure_message(result, "fallback") == "stderr-value"

    def test_returns_first_failed_when_multiple(self):
        result = MagicMock()
        result.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "first"}},
            },
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "second"}},
            },
        ]
        assert _extract_failure_message(result, "fallback") == "first"

    def test_returns_default_when_failed_event_has_no_message(self):
        result = MagicMock()
        result.events = [{"event": "runner_on_failed", "event_data": {"res": {}}}]
        assert _extract_failure_message(result, "fallback") == "fallback"


# ----- get_memory_info ------------------------------------------------------


def _runner_result(status: str, events: list) -> MagicMock:
    r = MagicMock()
    r.status = status
    r.events = events
    r.rc = 0 if status == "successful" else 1
    return r


def _setup_playbook_env(tmp_path: Path, operation: str) -> tuple[Path, Path]:
    """Return (playbook_dir, ssh_key) populated with the given operation."""
    playbook_dir = tmp_path / "pb"
    playbook_dir.mkdir(exist_ok=True)
    (playbook_dir / f"{operation}.yaml").write_text("---\n")
    ssh_key = tmp_path / "id_rsa"
    if not ssh_key.exists():
        ssh_key.write_text("key")
    return playbook_dir, ssh_key


class TestGetMemoryInfo:
    def test_returns_none_when_agent_unresolved(self):
        with patch(
            "clawrium.core.memory._resolve_agent_with_memory",
            return_value=(None, "test-reason", None),
        ):
            assert get_memory_info("192.168.1.100", "x") is None

    def test_returns_none_on_missing_playbook(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", tmp_path / "missing"),
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None

    def test_returns_none_when_ssh_key_missing(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        # Point _PLAYBOOK_DIR at a tmp dir containing the playbook so the
        # missing-playbook check passes and we exercise the SSH key path.
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key", return_value=None
            ),
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None

    def test_extracts_stats_from_successful_run(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")

        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        # The memory_info playbook emits one debug msg per line; each
        # arrives as its own runner_on_ok event with res.msg populated.
        msgs = [
            "WORKSPACE_PATH=/home/opc-work/.openclaw/workspace",
            "TOP SOUL.md 10",
            "TOP IDENTITY.md 20",
            "TOP USER.md -1",
            "TOP TOOLS.md 30",
            "DAILY 2026-05-09.md 40",
        ]
        events = [
            {"event": "runner_on_ok", "event_data": {"res": {"msg": m}}} for m in msgs
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            stats = get_memory_info("192.168.1.100", "opc-work")

        assert stats is not None
        assert stats["workspace_path"] == "/home/opc-work/.openclaw/workspace"
        # 10 + 20 + 30 + 40 = 100; missing USER.md contributes 0
        assert stats["total_bytes"] == 100
        files_by_name = {f["name"]: f for f in stats["files"]}
        assert files_by_name["USER.md"]["exists"] is False
        assert files_by_name["USER.md"]["size_bytes"] == 0
        daily = files_by_name["2026-05-09.md"]
        assert daily["relative_path"] == "memory/2026-05-09.md"
        assert daily["size_bytes"] == 40

    def test_returns_none_on_timeout(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        result = _runner_result("timeout", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None

    def test_returns_none_on_runner_exception_offline(self, tmp_path: Path):
        """Gap #1: offline / unreachable agent must degrade gracefully."""
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run",
                side_effect=ConnectionError("host unreachable"),
            ),
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None


# ----- read_memory_file -----------------------------------------------------


class TestReadMemoryFile:
    def test_returns_none_on_invalid_filename(self):
        assert read_memory_file("h", "a", "../bad") is None

    def test_returns_none_when_unresolved(self):
        with patch(
            "clawrium.core.memory._resolve_agent_with_memory",
            return_value=(None, "test-reason", None),
        ):
            assert read_memory_file("h", "a", "SOUL.md") is None

    def test_returns_decoded_content_on_success(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_read.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        encoded = base64.b64encode(b"hello world").decode("ascii")
        events = [
            {"event": "runner_on_ok", "event_data": {"res": {"content": encoded}}}
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") == "hello world"

    def test_returns_none_when_playbook_fails(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")

        result = _runner_result("failed", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_runner_exception_offline(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run",
                side_effect=ConnectionError("host unreachable"),
            ),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_timeout(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")
        result = _runner_result("timeout", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_invalid_base64(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"content": "not-valid-base64!!!"}},
            }
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_non_utf8_bytes(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")
        encoded = base64.b64encode(b"\xff\xfe\xfd").decode("ascii")
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"content": encoded}},
            }
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None


# ----- write_memory_file ----------------------------------------------------


class TestWriteMemoryFile:
    def test_validation_error_returns_false(self):
        ok, err = write_memory_file("h", "a", "../etc/passwd", "x")
        assert ok is False
        assert err is not None and "Invalid" in err

    def test_returns_false_when_unresolved(self):
        with patch(
            "clawrium.core.memory._resolve_agent_with_memory",
            return_value=(None, "test-reason", None),
        ):
            ok, err = write_memory_file("h", "a", "SOUL.md", "x")
        assert ok is False
        assert err is not None

    def test_returns_true_on_successful_run(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is True
        assert err is None

    def test_returns_failure_message_from_events(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "permission denied"}},
            }
        ]
        result = _runner_result("failed", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is False
        assert err == "permission denied"

    def test_returns_false_on_timeout(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        result = _runner_result("timeout", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is False
        assert err is not None and "timed out" in err

    def test_returns_false_on_runner_exception_offline(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run",
                side_effect=ConnectionError("host unreachable"),
            ),
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is False
        assert err is not None and "unreachable" in err

    def test_rejects_oversize_content(self):
        # Build content one byte over the limit.
        oversize = "a" * (MAX_MEMORY_CONTENT_BYTES + 1)
        ok, err = write_memory_file("h", "opc-work", "SOUL.md", oversize)
        assert ok is False
        assert err is not None and "exceeds maximum size" in err

    def test_accepts_content_at_size_limit(self, tmp_path: Path):
        # Exact-limit and one-byte-under should both pass the size check
        # (and proceed to the host resolution step which we mock).
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")
        result = _runner_result("successful", [])

        for size in (MAX_MEMORY_CONTENT_BYTES - 1, MAX_MEMORY_CONTENT_BYTES):
            with (
                patch(
                    "clawrium.core.memory._resolve_agent_with_memory",
                    return_value=(host, "opc-work", "openclaw"),
                ),
                patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
                patch(
                    "clawrium.core.memory.core_keys.get_host_private_key",
                    return_value=ssh_key,
                ),
                patch("clawrium.core.memory.ansible_runner.run", return_value=result),
            ):
                ok, err = write_memory_file("h", "opc-work", "SOUL.md", "a" * size)
            assert ok is True, f"size {size} should be accepted"
            assert err is None

    def test_returns_false_on_pre_flight_oserror(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory._get_logs_dir",
                side_effect=OSError("read-only filesystem"),
            ),
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "x")
        assert ok is False
        assert err is not None and "read-only filesystem" in err


# ----- delete_memory_files --------------------------------------------------


class TestDeleteMemoryFiles:
    def test_empty_list_is_noop(self):
        ok, err = delete_memory_files("h", "a", [])
        assert ok is True
        assert err is None

    def test_validation_failure(self):
        ok, err = delete_memory_files("h", "a", ["../bad"])
        assert ok is False
        assert err is not None

    def test_returns_false_when_unresolved(self):
        with patch(
            "clawrium.core.memory._resolve_agent_with_memory",
            return_value=(None, "test-reason", None),
        ):
            ok, err = delete_memory_files("h", "a", ["SOUL.md"])
        assert ok is False

    def test_passes_files_list_through_to_playbook(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_delete")

        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run", return_value=result
            ) as mock_run,
        ):
            ok, err = delete_memory_files(
                "h", "opc-work", ["SOUL.md", "memory/2026-05-09.md"]
            )

        assert ok is True
        assert err is None
        kwargs = mock_run.call_args.kwargs
        inventory = kwargs["inventory"]
        assert inventory["all"]["vars"]["memory_files"] == [
            "SOUL.md",
            "memory/2026-05-09.md",
        ]

    def test_returns_false_on_timeout(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_delete")

        result = _runner_result("timeout", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = delete_memory_files("h", "opc-work", ["SOUL.md"])
        assert ok is False
        assert err is not None and "timed out" in err

    def test_returns_false_on_runner_exception_offline(self, tmp_path: Path):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_delete")

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run",
                side_effect=ConnectionError("host unreachable"),
            ),
        ):
            ok, err = delete_memory_files("h", "opc-work", ["SOUL.md"])
        assert ok is False
        assert err is not None and "unreachable" in err


# ----- _cleanup_artifacts ---------------------------------------------------


class TestCleanupArtifacts:
    def test_removes_known_subdirs(self, tmp_path: Path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "f").write_text("x")
        env = tmp_path / "env"
        env.mkdir()
        (env / "f").write_text("x")

        _cleanup_artifacts(tmp_path)

        assert not artifacts.exists()
        assert not env.exists()

    def test_silently_ignores_missing_dirs(self, tmp_path: Path):
        # No exception should be raised if subdirs do not exist.
        _cleanup_artifacts(tmp_path)

    @pytest.mark.parametrize(
        "operation,call",
        [
            (
                "memory_read",
                lambda: read_memory_file("h", "opc-work", "SOUL.md"),
            ),
            (
                "memory_write",
                lambda: write_memory_file("h", "opc-work", "SOUL.md", "x"),
            ),
            (
                "memory_delete",
                lambda: delete_memory_files("h", "opc-work", ["SOUL.md"]),
            ),
            (
                "memory_info",
                lambda: get_memory_info("h", "opc-work"),
            ),
        ],
    )
    def test_cleanup_called_on_success_for_all_operations(
        self, tmp_path: Path, operation: str, call
    ):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, operation)
        result = _runner_result(
            "successful",
            [
                {
                    "event": "runner_on_ok",
                    "event_data": {"res": {"stdout": "", "content": ""}},
                }
            ],
        )

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
            patch("clawrium.core.memory._cleanup_artifacts") as cleanup,
        ):
            call()
        # Success path cleans up exactly once via the caller's finally block.
        assert cleanup.call_count == 1

    @pytest.mark.parametrize(
        "operation,call",
        [
            (
                "memory_read",
                lambda: read_memory_file("h", "opc-work", "SOUL.md"),
            ),
            (
                "memory_write",
                lambda: write_memory_file("h", "opc-work", "SOUL.md", "x"),
            ),
            (
                "memory_delete",
                lambda: delete_memory_files("h", "opc-work", ["SOUL.md"]),
            ),
            (
                "memory_info",
                lambda: get_memory_info("h", "opc-work"),
            ),
        ],
    )
    def test_cleanup_called_on_runner_exception_for_all_operations(
        self, tmp_path: Path, operation: str, call
    ):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, operation)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run",
                side_effect=ConnectionError("offline"),
            ),
            patch("clawrium.core.memory._cleanup_artifacts") as cleanup,
        ):
            call()
        assert cleanup.call_count == 1

    @pytest.mark.parametrize(
        "operation,call,expect_falsy",
        [
            (
                "memory_info",
                lambda: get_memory_info("h", "opc-work"),
                lambda r: r is None,
            ),
            (
                "memory_read",
                lambda: read_memory_file("h", "opc-work", "SOUL.md"),
                lambda r: r is None,
            ),
            (
                "memory_write",
                lambda: write_memory_file("h", "opc-work", "SOUL.md", "x"),
                lambda r: r[0] is False and r[1] is not None,
            ),
            (
                "memory_delete",
                lambda: delete_memory_files("h", "opc-work", ["SOUL.md"]),
                lambda r: r[0] is False and r[1] is not None,
            ),
        ],
    )
    def test_ssh_key_missing_degrades_for_all_operations(
        self, tmp_path: Path, operation: str, call, expect_falsy
    ):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, _ = _setup_playbook_env(tmp_path, operation)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key", return_value=None
            ),
        ):
            assert expect_falsy(call())

    @pytest.mark.parametrize(
        "operation,call",
        [
            (
                "memory_write",
                lambda: write_memory_file("h", "opc-work", "SOUL.md", "x"),
            ),
            (
                "memory_delete",
                lambda: delete_memory_files("h", "opc-work", ["SOUL.md"]),
            ),
        ],
    )
    def test_ssh_key_missing_error_includes_remediation_command(
        self, tmp_path: Path, operation: str, call
    ):
        # write/delete surface the structured error string back to the user;
        # confirm the actionable 'clm host init' guidance is present so the
        # CLI/TUI message stays useful if someone refactors the error text.
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir, _ = _setup_playbook_env(tmp_path, operation)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key", return_value=None
            ),
        ):
            ok, err = call()
        assert ok is False
        assert err is not None
        assert "clm host init" in err

    def test_cleanup_swallows_permission_error(self, tmp_path: Path):
        # Real cleanup uses shutil.rmtree which can raise PermissionError on
        # locked-down FS. The function must not propagate it because callers
        # invoke it from finally blocks where a raised exception would mask
        # the original error.
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "f").write_text("x")

        with patch(
            "clawrium.core.memory.shutil.rmtree",
            side_effect=PermissionError("locked"),
        ):
            _cleanup_artifacts(tmp_path)  # must not raise


# ----- Phase 3: cross-claw memory dispatch ---------------------------------
#
# These tests cover the manifest-driven dispatch added in #314 and extended
# in #358:
#   - _resolve_agent_with_memory selects candidates by features.memory==true
#   - hermes claw type lists MEMORY.md / USER.md via the hermes playbook dir
#   - hermes write enforces the per-file character limits client-side
#   - zeroclaw (features.memory true after #358) routes to its own playbooks
#   - unknown claw types are rejected via claw_supports_memory


from clawrium.core.memory import (  # noqa: E402 - imports grouped per-section
    _get_playbook_dir,
    _manifest_workspace_path,
    claw_supports_memory,
)


class TestClawSupportsMemory:
    def test_openclaw_supports_memory(self):
        assert claw_supports_memory("openclaw") is True

    def test_hermes_supports_memory(self):
        assert claw_supports_memory("hermes") is True

    def test_zeroclaw_supports_memory(self):
        # Issue #358 wires features.memory: true into the zeroclaw manifest
        # so the memory CLI routes to zeroclaw's playbooks.
        assert claw_supports_memory("zeroclaw") is True

    def test_unknown_claw_returns_false(self):
        # Unknown / unloadable manifest treated as unsupported rather than
        # raising — keeps the CLI error friendly.
        assert claw_supports_memory("nonexistent-claw") is False


class TestGetPlaybookDir:
    def test_openclaw_uses_module_global_for_back_compat(self):
        from clawrium.core import memory as memmod

        # The module-global _PLAYBOOK_DIR is preserved so legacy tests that
        # patch it continue to inject a temp playbook directory.
        assert _get_playbook_dir("openclaw") == memmod._PLAYBOOK_DIR

    def test_hermes_resolves_to_hermes_playbooks(self):
        path = _get_playbook_dir("hermes")
        assert path.name == "playbooks"
        assert path.parent.name == "hermes"

    def test_zeroclaw_resolves_to_zeroclaw_playbooks(self):
        # After #358 the zeroclaw playbook dir ships memory_*.yaml files,
        # so this test is a structural pin on the registry layout (no
        # dispatch runs here — see TestZeroclawDispatch for that).
        path = _get_playbook_dir("zeroclaw")
        assert path.name == "playbooks"
        assert path.parent.name == "zeroclaw"


class TestManifestWorkspacePath:
    def test_openclaw_expands_tilde_with_agent_home(self):
        assert _manifest_workspace_path("openclaw", "opc-work") == (
            "/home/opc-work/.openclaw/workspace/memory"
        )

    def test_hermes_expands_tilde_with_agent_home(self):
        assert _manifest_workspace_path("hermes", "hermes-test") == (
            "/home/hermes-test/.hermes/memories"
        )

    def test_returns_empty_string_for_unknown_claw(self):
        assert _manifest_workspace_path("nonexistent-claw", "x") == ""


def _host_with_hermes() -> dict:
    return {
        "hostname": "192.168.1.36",
        "key_id": "wolf-i",
        "alias": "wolf-i",
        "port": 22,
        "user": "xclm",
        "agents": {
            "hermes-test": {
                "type": "hermes",
                "agent_name": "hermes-test",
                "name": "hermes-test",
                "status": "installed",
            }
        },
    }


def _host_with_zeroclaw() -> dict:
    return {
        "hostname": "192.168.1.36",
        "key_id": "wolf-i",
        "alias": "wolf-i",
        "port": 22,
        "user": "xclm",
        "agents": {
            "zeroclaw": {
                "type": "zeroclaw",
                "agent_name": "zc-work",
                "name": "zc-work",
                "status": "installed",
            }
        },
    }


class TestResolveAgentWithMemoryHermes:
    def test_resolves_hermes_by_name(self):
        host = _host_with_hermes()
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_agent_with_memory("192.168.1.36", "hermes-test")
        assert result[0] is not None
        assert result[1] == "hermes-test"
        assert result[2] == "hermes"

    def test_rejects_unknown_type_as_unsupported(self):
        # Issue #358 wired memory into zeroclaw, so the unsupported-type
        # rejection path is exercised with a fictional claw type instead.
        host = _host(
            {
                "future-work": {
                    "type": "futureclaw",
                    "agent_name": "future-work",
                    "name": "future-work",
                    "status": "installed",
                }
            }
        )
        host["hostname"] = "192.168.1.36"
        host["alias"] = "wolf-i"
        host["key_id"] = "wolf-i"
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason, claw_type = _resolve_agent_with_memory(
                "192.168.1.36", "future-work"
            )
        assert h is None
        assert claw_type is None
        # Reason carries the "memory-capable agent not found" wording so the
        # caller's error message clearly signals it is a capability gap, not
        # a missing agent record.
        assert "memory-capable" in reason


class TestGetMemoryInfoHermes:
    def test_show_hermes_lists_memory_user_files(self, tmp_path: Path):
        """Phase 3 acceptance: `clm agent memory show <hermes>` returns the
        canonical MEMORY.md + USER.md stats from the hermes memory_info
        playbook output."""
        host = _host_with_hermes()
        playbook_dir = tmp_path / "hermes-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        msgs = [
            "WORKSPACE_PATH=/home/hermes-test/.hermes/memories",
            "TOP MEMORY.md 120",
            "TOP USER.md 80",
        ]
        events = [
            {"event": "runner_on_ok", "event_data": {"res": {"msg": m}}} for m in msgs
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            stats = get_memory_info("192.168.1.36", "hermes-test")

        assert stats is not None
        assert stats["workspace_path"] == "/home/hermes-test/.hermes/memories"
        files_by_name = {f["name"]: f for f in stats["files"]}
        assert files_by_name["MEMORY.md"]["exists"] is True
        assert files_by_name["MEMORY.md"]["size_bytes"] == 120
        assert files_by_name["USER.md"]["exists"] is True
        assert files_by_name["USER.md"]["size_bytes"] == 80
        # Hermes does not have a "daily" notion — total is just the two files.
        assert stats["total_bytes"] == 200


class TestWriteMemoryFileHermesLimits:
    def test_rejects_user_md_over_1375_chars(self):
        """Per-file char limit enforced client-side before any SSH dispatch."""
        host = _host_with_hermes()
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", "USER.md", "a" * 1376
            )
        assert ok is False
        assert err is not None
        assert "USER.md" in err
        assert "1375" in err
        assert "1376" in err

    def test_rejects_memory_md_over_2200_chars(self):
        host = _host_with_hermes()
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", "MEMORY.md", "a" * 2201
            )
        assert ok is False
        assert err is not None
        assert "MEMORY.md" in err
        assert "2200" in err

    def test_accepts_user_md_at_1375_chars(self, tmp_path: Path):
        host = _host_with_hermes()
        playbook_dir = tmp_path / "hermes-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", "USER.md", "a" * 1375
            )
        assert ok is True
        assert err is None

    def test_rejects_non_allowlisted_filename(self):
        """Hermes accepts only MEMORY.md and USER.md — other names rejected
        with the documented error string."""
        host = _host_with_hermes()
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = write_memory_file("192.168.1.36", "hermes-test", "FOO.md", "bar")
        assert ok is False
        assert err is not None
        assert "hermes memory accepts only MEMORY.md and USER.md" in err


class TestUnsupportedTypeFriendlyError:
    def test_resolve_unsupported_type_returns_friendly_reason(self):
        """An agent whose manifest does not declare features.memory emits a
        clear 'memory-capable agent not found' message rather than a
        misleading 'openclaw agent not found' string. Issue #358 wired
        memory into zeroclaw, so the negative case is now exercised with
        a fictional claw type (no manifest -> unsupported)."""
        host = _host(
            {
                "future-work": {
                    "type": "futureclaw",
                    "agent_name": "future-work",
                    "name": "future-work",
                    "status": "installed",
                }
            }
        )
        host["hostname"] = "192.168.1.36"
        host["alias"] = "wolf-i"
        host["key_id"] = "wolf-i"
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason, claw_type = _resolve_agent_with_memory(
                "192.168.1.36", "future-work"
            )
        assert h is None
        assert claw_type is None
        assert "memory-capable" in reason


# ----- ATX iter 1 fixups (B1, B2, W10, W11) --------------------------------


class TestLegacyResolveOpenclawAgentShim:
    """B1: the backward-compat shim must keep returning a 2-tuple
    constrained to openclaw, even when hermes (also memory-capable) agents
    coexist on the same host. The new dispatcher is unaware of this shim
    — these tests pin the contract so refactors do not silently regress
    pre-Phase-3 callers."""

    def test_shim_returns_two_tuple_for_openclaw(self):
        host = _host(
            {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "name": "work",
                },
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "name": "hermes-test",
                },
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        # 2-tuple, not 3-tuple — backward compat preserved.
        assert len(result) == 2
        host_record, unix_name = result
        assert host_record is not None
        assert unix_name == "opc-work"

    def test_shim_does_not_match_hermes_records(self):
        host = _host(
            {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "name": "hermes-test",
                },
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            h, reason = _resolve_openclaw_agent("192.168.1.100", "hermes-test")
        assert h is None
        # The shim's wording is openclaw-specific and must not change.
        assert "openclaw agent 'hermes-test' not found" in reason


class TestHermesCharLimitBoundaries:
    """B2: parametrized boundary tests for the hermes per-file char limits."""

    @pytest.fixture
    def hermes_host(self):
        return _host_with_hermes()

    @pytest.fixture
    def hermes_write_env(self, tmp_path: Path):
        playbook_dir = tmp_path / "hermes-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        return playbook_dir, ssh_key

    @pytest.mark.parametrize(
        "filename,length,should_accept",
        [
            ("USER.md", 0, True),  # empty content
            ("USER.md", 1, True),
            ("USER.md", 1374, True),
            ("USER.md", 1375, True),  # exactly at limit
            ("USER.md", 1376, False),
            ("USER.md", 5000, False),
            ("MEMORY.md", 0, True),
            ("MEMORY.md", 2199, True),
            ("MEMORY.md", 2200, True),  # exactly at limit
            ("MEMORY.md", 2201, False),
            ("MEMORY.md", 10000, False),
        ],
    )
    def test_char_limit_boundary(
        self,
        hermes_host,
        hermes_write_env,
        filename: str,
        length: int,
        should_accept: bool,
    ):
        playbook_dir, ssh_key = hermes_write_env
        result = _runner_result("successful", [])
        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(hermes_host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", filename, "a" * length
            )

        if should_accept:
            assert ok is True, f"size {length} should be accepted for {filename}"
            assert err is None
        else:
            assert ok is False, f"size {length} should be rejected for {filename}"
            assert err is not None
            assert filename in err
            assert str(length) in err

    def test_multibyte_utf8_uses_codepoint_count_not_byte_count(
        self, hermes_host, hermes_write_env
    ):
        """Hermes documents memory file limits in CHARACTERS (codepoints),
        not bytes. A string of N multi-byte characters must be validated
        against the char limit, not the byte limit; otherwise a user can
        only write half the documented capacity for non-ASCII content."""
        playbook_dir, ssh_key = hermes_write_env
        result = _runner_result("successful", [])

        # 1375 codepoints of multi-byte (each "é" is 2 bytes in UTF-8).
        content = "é" * 1375
        assert len(content) == 1375
        assert len(content.encode("utf-8")) == 2750

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(hermes_host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", "USER.md", content
            )
        # 1375 codepoints at exactly the documented limit — accept.
        assert ok is True, err

        # 1376 codepoints — reject.
        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(hermes_host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", "USER.md", "é" * 1376
            )
        assert ok is False
        assert err is not None and "1376" in err and "1375" in err


class TestHermesReadAndDelete:
    """W10: cross-claw dispatch coverage for read + delete on hermes."""

    def test_read_hermes_dispatches_to_hermes_playbook_dir(self, tmp_path: Path):
        host = _host_with_hermes()
        playbook_dir = tmp_path / "hermes-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_read.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        encoded = base64.b64encode(b"hermes user profile").decode("ascii")
        events = [
            {"event": "runner_on_ok", "event_data": {"res": {"content": encoded}}}
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ) as get_dir,
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            content = read_memory_file("192.168.1.36", "hermes-test", "USER.md")
        assert content == "hermes user profile"
        # Confirm dispatch consulted the hermes playbook dir.
        get_dir.assert_called_with("hermes")

    def test_delete_hermes_dispatches_to_hermes_playbook_dir(self, tmp_path: Path):
        host = _host_with_hermes()
        playbook_dir = tmp_path / "hermes-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_delete.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "hermes-test", "hermes"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ) as get_dir,
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run", return_value=result
            ) as mock_run,
        ):
            ok, err = delete_memory_files("192.168.1.36", "hermes-test", ["USER.md"])
        assert ok is True
        assert err is None
        get_dir.assert_called_with("hermes")
        # Confirm the inventory carries the filename list as-is.
        inv = mock_run.call_args.kwargs["inventory"]
        assert inv["all"]["vars"]["memory_files"] == ["USER.md"]


class TestHermesFilenameRejection:
    """W11: hermes filename allowlist tests beyond the existing single case."""

    @pytest.mark.parametrize(
        "bad_filename",
        [
            "IDENTITY.md",
            "TOOLS.md",
            "memory/2026-05-10.md",  # openclaw daily naming
            "agent.md",
            "RANDOM.txt",
        ],
    )
    def test_hermes_rejects_non_allowlisted_filenames(self, bad_filename: str):
        host = _host_with_hermes()
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = write_memory_file(
                "192.168.1.36", "hermes-test", bad_filename, "ok"
            )
        assert ok is False
        assert err is not None
        # The allowlist error wording is part of the user-facing contract.
        assert "hermes memory accepts only MEMORY.md and USER.md and SOUL.md" in err

    def test_openclaw_does_not_apply_hermes_allowlist(self, tmp_path: Path):
        """Regression guard: the per-claw allowlist must not bleed across
        types — openclaw still accepts SOUL.md, IDENTITY.md, daily files."""
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        playbook_dir = tmp_path / "openclaw-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "opc-work", "openclaw"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            for filename in ("SOUL.md", "IDENTITY.md", "memory/2026-05-10.md"):
                ok, err = write_memory_file(
                    "192.168.1.100", "opc-work", filename, "content"
                )
                assert ok is True, f"openclaw must accept {filename}: {err}"


class TestClawSupportsMemoryFallback:
    """B3: claw_supports_memory must downgrade gracefully when manifest
    loading raises — both the documented exceptions and any unexpected
    error type — without re-raising into the public memory functions."""

    def test_returns_false_on_manifest_not_found(self):
        from clawrium.core.registry import ManifestNotFoundError

        with patch(
            "clawrium.core.memory.load_manifest",
            side_effect=ManifestNotFoundError("nope"),
        ):
            assert claw_supports_memory("nonexistent") is False

    def test_returns_false_on_manifest_parse_error(self):
        from clawrium.core.registry import ManifestParseError

        with patch(
            "clawrium.core.memory.load_manifest",
            side_effect=ManifestParseError("broken"),
        ):
            assert claw_supports_memory("broken-claw") is False

    def test_returns_false_on_unexpected_exception(self, caplog):
        """A bug inside load_manifest (e.g. TypeError) must surface in logs
        rather than silently masking all memory ops."""
        import logging

        with (
            patch(
                "clawrium.core.memory.load_manifest",
                side_effect=TypeError("internal bug"),
            ),
            caplog.at_level(logging.WARNING, logger="clawrium.core.memory"),
        ):
            result = claw_supports_memory("borked")
        assert result is False
        # Unexpected errors are logged at WARNING level; expected ones at DEBUG.
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("unexpected error" in r.getMessage() for r in warning_records)


# ----- ATX iter 1 B1: zeroclaw dispatch coverage ---------------------------


class TestZeroclawDispatch:
    """B1 (ATX round 1 for #358): exercise the full memory dispatch chain
    for zeroclaw — resolve → _get_playbook_dir('zeroclaw') → playbook run.

    Without this class, a regression that routes zeroclaw ops through the
    openclaw _PLAYBOOK_DIR fallback in _get_playbook_dir would slip past
    every other test in the suite (which either test the helper in
    isolation or only exercise hermes/openclaw dispatch)."""

    def test_get_memory_info_routes_to_zeroclaw_playbook_dir(self, tmp_path: Path):
        host = _host_with_zeroclaw()
        playbook_dir = tmp_path / "zeroclaw-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        # Emit one stat line per personality file — get_memory_info should
        # surface all seven plus the workspace path.
        msgs = [
            "WORKSPACE_PATH=/home/zc-work/.zeroclaw/workspace",
            "TOP SOUL.md 100",
            "TOP IDENTITY.md 50",
            "TOP USER.md 30",
            "TOP AGENTS.md 200",
            "TOP TOOLS.md 80",
            "TOP MEMORY.md 10",
            "TOP HEARTBEAT.md 5",
        ]
        events = [
            {"event": "runner_on_ok", "event_data": {"res": {"msg": m}}} for m in msgs
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "zc-work", "zeroclaw"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ) as get_dir,
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            stats = get_memory_info("192.168.1.36", "zc-work")

        assert stats is not None
        get_dir.assert_called_with("zeroclaw")
        assert stats["workspace_path"] == "/home/zc-work/.zeroclaw/workspace"
        names = {f["name"] for f in stats["files"]}
        assert names == {
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "AGENTS.md",
            "TOOLS.md",
            "MEMORY.md",
            "HEARTBEAT.md",
        }
        # BOOTSTRAP.md must not appear in the dispatched output.
        assert "BOOTSTRAP.md" not in names
        assert stats["total_bytes"] == 100 + 50 + 30 + 200 + 80 + 10 + 5

    def test_read_routes_to_zeroclaw_playbook_dir(self, tmp_path: Path):
        host = _host_with_zeroclaw()
        playbook_dir = tmp_path / "zeroclaw-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_read.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        encoded = base64.b64encode(b"zeroclaw soul content").decode("ascii")
        events = [
            {"event": "runner_on_ok", "event_data": {"res": {"content": encoded}}}
        ]
        result = _runner_result("successful", events)

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "zc-work", "zeroclaw"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ) as get_dir,
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            content = read_memory_file("192.168.1.36", "zc-work", "SOUL.md")
        assert content == "zeroclaw soul content"
        get_dir.assert_called_with("zeroclaw")

    def test_write_routes_to_zeroclaw_playbook_dir(self, tmp_path: Path):
        host = _host_with_zeroclaw()
        playbook_dir = tmp_path / "zeroclaw-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "zc-work", "zeroclaw"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ) as get_dir,
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run", return_value=result
            ) as mock_run,
        ):
            ok, err = write_memory_file(
                "192.168.1.36", "zc-work", "SOUL.md", "new identity content"
            )
        assert ok is True
        assert err is None
        get_dir.assert_called_with("zeroclaw")
        # Inventory must carry the content as base64 (so user-supplied bytes
        # can never be reinterpreted as Jinja2 by the playbook).
        inv = mock_run.call_args.kwargs["inventory"]
        b64 = inv["all"]["vars"]["memory_content_b64"]
        assert base64.b64decode(b64).decode("utf-8") == "new identity content"

    def test_delete_routes_to_zeroclaw_playbook_dir(self, tmp_path: Path):
        host = _host_with_zeroclaw()
        playbook_dir = tmp_path / "zeroclaw-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_delete.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "zc-work", "zeroclaw"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ) as get_dir,
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch(
                "clawrium.core.memory.ansible_runner.run", return_value=result
            ) as mock_run,
        ):
            ok, err = delete_memory_files("192.168.1.36", "zc-work", ["AGENTS.md"])
        assert ok is True
        assert err is None
        get_dir.assert_called_with("zeroclaw")
        inv = mock_run.call_args.kwargs["inventory"]
        assert inv["all"]["vars"]["memory_files"] == ["AGENTS.md"]

    def test_write_rejects_bootstrap_md(self):
        """W3 (ATX): BOOTSTRAP.md is runtime-owned and self-deletes after
        first boot. The Python write path must reject it before any SSH
        dispatch — symmetric with memory_info.yaml's exclusion."""
        host = _host_with_zeroclaw()
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = write_memory_file("192.168.1.36", "zc-work", "BOOTSTRAP.md", "x")
        assert ok is False
        assert err is not None
        # The rejection must come from the allowlist path specifically
        # (not a generic resolve / pattern / size failure that would
        # *also* match for a malformed filename). Anchor on the
        # `_MEMORY_WRITE_ALLOWED_FILES` rejection text.
        assert "accepts only" in err, (
            f"BOOTSTRAP rejection should hit the allowlist path; got: {err!r}"
        )
        # Sanity-check: at least one allowed personality file appears in the
        # error listing so an operator can see what IS writable.
        assert "SOUL.md" in err


# ----- ATX iter 5 W1: openclaw allowlist negative-path coverage ------------


class TestOpenclawWriteAllowlist:
    """W1 (iter 5): Python-side allowlist for openclaw was added in iter 4
    so the playbook + Python defenses are symmetric. These tests pin the
    negative path so a future PR that drops 'openclaw' from
    _MEMORY_WRITE_ALLOWED_FILES fails CI rather than silently reverting
    to permissive mode."""

    @pytest.mark.parametrize(
        "bad_filename",
        ["BOOTSTRAP.md", "CONFIG.md", "RANDOM.txt", "AGENTS.md"],
    )
    def test_openclaw_rejects_non_allowlisted_filename(self, bad_filename: str):
        host = _host({"opc-work": {"type": "openclaw", "agent_name": "opc-work"}})
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = write_memory_file("192.168.1.100", "opc-work", bad_filename, "x")
        assert ok is False
        assert err is not None
        assert "openclaw memory accepts only" in err
        # The daily-notes suffix is part of the user-facing contract so
        # operators understand the memory/<file> bypass exists.
        assert "(or memory/<file>)" in err


# ----- ATX iter 5 W2: zeroclaw daily-note write path -----------------------


class TestZeroclawDailyNoteWrite:
    """W2 (iter 5): the _MEMORY_WRITE_DAILY_NOTES bypass for zeroclaw is
    exercised only for openclaw in TestWriteMemoryFile.
    test_openclaw_does_not_apply_hermes_allowlist. Pin the zeroclaw daily-
    note path explicitly so dropping 'zeroclaw' from the daily-notes set
    fails CI."""

    def test_zeroclaw_accepts_memory_daily_note(self, tmp_path: Path):
        host = _host_with_zeroclaw()
        playbook_dir = tmp_path / "zeroclaw-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "zc-work", "zeroclaw"),
            ),
            patch(
                "clawrium.core.memory._get_playbook_dir",
                return_value=playbook_dir,
            ),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = write_memory_file(
                "192.168.1.36", "zc-work", "memory/2026-05-15.md", "todo"
            )
        assert ok is True, f"zeroclaw must accept daily-note path: {err}"
        assert err is None


# ----- ATX iter 5 S3: MEMORY_TOP_LEVEL_FILES not in __all__ ----------------


class TestPublicAPIShape:
    def test_memory_top_level_files_excluded_from_dunder_all(self):
        # #358 changed MEMORY_TOP_LEVEL_FILES from tuple to dict; removing
        # it from __all__ surfaces the shape change to any future external
        # consumer rather than silently breaking iteration / membership.
        from clawrium.core import memory as memmod

        assert "MEMORY_TOP_LEVEL_FILES" not in memmod.__all__


# ----- ATX iter 5 S4: cross-claw constant parity ---------------------------


class TestConstantParity:
    """S4 (iter 5): the info-playbook file set (MEMORY_TOP_LEVEL_FILES)
    and the write allowlist (_MEMORY_WRITE_ALLOWED_FILES) must agree for
    claws that appear in both. A divergence would let memory_info show a
    file the write path rejects (or vice versa) — confusing for
    operators."""

    @pytest.mark.parametrize("claw_type", ["openclaw", "hermes", "zeroclaw"])
    def test_top_level_and_write_allowlist_agree(self, claw_type: str):
        from clawrium.core.memory import (
            MEMORY_TOP_LEVEL_FILES,
            _MEMORY_WRITE_ALLOWED_FILES,
        )

        info = MEMORY_TOP_LEVEL_FILES.get(claw_type)
        write = _MEMORY_WRITE_ALLOWED_FILES.get(claw_type)
        assert info is not None, f"missing MEMORY_TOP_LEVEL_FILES for {claw_type}"
        assert write is not None, f"missing _MEMORY_WRITE_ALLOWED_FILES for {claw_type}"
        assert set(info) == set(write), (
            f"{claw_type}: memory_info file set {set(info)} disagrees with "
            f"write allowlist {set(write)} — operators will see asymmetric "
            f"behavior between `memory show` and `memory write`."
        )


# ----- ATX iter 6 W-new-1: YAML ↔ Python parity ----------------------------


class TestYamlPythonParity:
    """W-new-1 (iter 6): TestConstantParity compared two Python dicts but
    neither is the runtime source of truth. memory_info.yaml's `vars.
    memory_top_level_files` block is what each claw's runtime actually
    iterates. A PR that adds a file to the YAML without touching the
    Python constant would pass every test while breaking the
    operator-visible invariant. Pin the YAML ↔ Python relationship
    directly."""

    @pytest.mark.parametrize("claw_type", ["openclaw", "hermes", "zeroclaw"])
    def test_yaml_top_level_matches_python_constant(self, claw_type: str):
        from importlib.resources import files
        import yaml as yamlmod

        from clawrium.core.memory import MEMORY_TOP_LEVEL_FILES

        pkg = files(f"clawrium.platform.registry.{claw_type}")
        data = yamlmod.safe_load((pkg / "playbooks" / "memory_info.yaml").read_text())
        yaml_vars = data[0]["vars"]["memory_top_level_files"]
        # Hermes uses dict-of-{name,path} entries; openclaw/zeroclaw use
        # plain strings. Normalize to filenames.
        if yaml_vars and isinstance(yaml_vars[0], dict):
            yaml_names = {entry["name"] for entry in yaml_vars}
        else:
            yaml_names = set(yaml_vars)

        python_names = set(MEMORY_TOP_LEVEL_FILES[claw_type])
        assert yaml_names == python_names, (
            f"{claw_type}: memory_info.yaml lists {yaml_names} but Python "
            f"MEMORY_TOP_LEVEL_FILES says {python_names}. The YAML is the "
            f"runtime source of truth — sync the Python constant."
        )


# ----- ATX iter 6 W-new-3: hermes SOUL.md delete asymmetry -----------------


class TestHermesDeleteAsymmetry:
    """W-new-3 (iter 6): hermes accepts SOUL.md on write (file lands at
    ~/.hermes/SOUL.md) but never on delete (the file lives outside
    memories/, and removing it is destructive enough to require manual
    SSH). The Python-level allowlist surfaces this as a clear message
    before any Ansible dispatch."""

    def test_hermes_delete_rejects_soul_md(self):
        host = _host_with_hermes()
        with patch("clawrium.core.memory.get_host", return_value=host):
            ok, err = delete_memory_files("192.168.1.36", "hermes-test", ["SOUL.md"])
        assert ok is False
        assert err is not None
        assert "hermes memory delete rejects 'SOUL.md'" in err
        # Operators must see which files ARE deletable.
        assert "MEMORY.md" in err
        assert "USER.md" in err

    def test_hermes_delete_accepts_canonical_files(self, tmp_path: Path):
        host = _host_with_hermes()
        playbook_dir = tmp_path / "hermes-pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_delete.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")
        result = _runner_result("successful", [])

        with (
            patch(
                "clawrium.core.memory._resolve_agent_with_memory",
                return_value=(host, "hermes-test", "hermes"),
            ),
            patch("clawrium.core.memory._get_playbook_dir", return_value=playbook_dir),
            patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ),
            patch("clawrium.core.memory.ansible_runner.run", return_value=result),
        ):
            ok, err = delete_memory_files("192.168.1.36", "hermes-test", ["MEMORY.md"])
        assert ok is True
        assert err is None
