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
    def test_top_level_files_match_workspace_layout(self):
        assert set(MEMORY_TOP_LEVEL_FILES) == {
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "TOOLS.md",
        }


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
            assert _resolve_openclaw_agent("nope", "anything") is None

    def test_returns_none_when_agents_field_invalid(self):
        host = {"hostname": "192.168.1.100", "agents": []}
        with patch("clawrium.core.memory.get_host", return_value=host):
            assert _resolve_openclaw_agent("192.168.1.100", "x") is None

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
        assert result is not None
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
        assert result is not None
        assert result[1] == "opc-work"

    def test_returns_none_when_agent_missing(self):
        host = _host({})
        with patch("clawrium.core.memory.get_host", return_value=host):
            assert _resolve_openclaw_agent("192.168.1.100", "ghost") is None

    def test_returns_none_when_agent_is_wrong_type(self):
        host = _host(
            {"zeroclaw": {"type": "zeroclaw", "agent_name": "zc", "name": "zc"}}
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            assert _resolve_openclaw_agent("192.168.1.100", "zeroclaw") is None

    def test_returns_none_when_multiple_matches(self):
        host = _host(
            {
                "opc-a": {"type": "openclaw", "agent_name": "opc-a", "name": "shared"},
                "opc-b": {"type": "openclaw", "agent_name": "opc-b", "name": "shared"},
            }
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            assert _resolve_openclaw_agent("192.168.1.100", "shared") is None

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
            assert _resolve_openclaw_agent("192.168.1.100", "opc-work") is None

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
        assert result is not None and result[1] == "opc-work"

    def test_accepts_record_without_status_field(self):
        # Legacy/test records without status are treated as installed.
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        with patch("clawrium.core.memory.get_host", return_value=host):
            result = _resolve_openclaw_agent("192.168.1.100", "opc-work")
        assert result is not None


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
        result.events = [
            {"event": "runner_on_failed", "event_data": {"res": {}}}
        ]
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
        with patch("clawrium.core.memory._resolve_openclaw_agent", return_value=None):
            assert get_memory_info("192.168.1.100", "x") is None

    def test_returns_none_on_missing_playbook(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch(
            "clawrium.core.memory._PLAYBOOK_DIR", tmp_path / "missing"
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None

    def test_returns_none_when_ssh_key_missing(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        # Point _PLAYBOOK_DIR at a tmp dir containing the playbook so the
        # missing-playbook check passes and we exercise the SSH key path.
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=None
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None

    def test_extracts_stats_from_successful_run(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
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
            {"event": "runner_on_ok", "event_data": {"res": {"msg": m}}}
            for m in msgs
        ]
        result = _runner_result("successful", events)

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
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
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        result = _runner_result("timeout", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None

    def test_returns_none_on_runner_exception_offline(self, tmp_path: Path):
        """Gap #1: offline / unreachable agent must degrade gracefully."""
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_info.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run",
            side_effect=ConnectionError("host unreachable"),
        ):
            assert get_memory_info("192.168.1.100", "opc-work") is None


# ----- read_memory_file -----------------------------------------------------


class TestReadMemoryFile:
    def test_returns_none_on_invalid_filename(self):
        assert read_memory_file("h", "a", "../bad") is None

    def test_returns_none_when_unresolved(self):
        with patch("clawrium.core.memory._resolve_openclaw_agent", return_value=None):
            assert read_memory_file("h", "a", "SOUL.md") is None

    def test_returns_decoded_content_on_success(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
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

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") == "hello world"

    def test_returns_none_when_playbook_fails(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")

        result = _runner_result("failed", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_runner_exception_offline(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run",
            side_effect=ConnectionError("host unreachable"),
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_timeout(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")
        result = _runner_result("timeout", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_invalid_base64(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"content": "not-valid-base64!!!"}},
            }
        ]
        result = _runner_result("successful", events)

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None

    def test_returns_none_on_non_utf8_bytes(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_read")
        encoded = base64.b64encode(b"\xff\xfe\xfd").decode("ascii")
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"content": encoded}},
            }
        ]
        result = _runner_result("successful", events)

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            assert read_memory_file("h", "opc-work", "SOUL.md") is None


# ----- write_memory_file ----------------------------------------------------


class TestWriteMemoryFile:
    def test_validation_error_returns_false(self):
        ok, err = write_memory_file("h", "a", "../etc/passwd", "x")
        assert ok is False
        assert err is not None and "Invalid" in err

    def test_returns_false_when_unresolved(self):
        with patch("clawrium.core.memory._resolve_openclaw_agent", return_value=None):
            ok, err = write_memory_file("h", "a", "SOUL.md", "x")
        assert ok is False
        assert err is not None

    def test_returns_true_on_successful_run(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir = tmp_path / "pb"
        playbook_dir.mkdir()
        (playbook_dir / "memory_write.yaml").write_text("---\n")
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("key")

        result = _runner_result("successful", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is True
        assert err is None

    def test_returns_failure_message_from_events(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "permission denied"}},
            }
        ]
        result = _runner_result("failed", events)

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is False
        assert err == "permission denied"

    def test_returns_false_on_timeout(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        result = _runner_result("timeout", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            ok, err = write_memory_file("h", "opc-work", "SOUL.md", "content")
        assert ok is False
        assert err is not None and "timed out" in err

    def test_returns_false_on_runner_exception_offline(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run",
            side_effect=ConnectionError("host unreachable"),
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
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")
        result = _runner_result("successful", [])

        for size in (MAX_MEMORY_CONTENT_BYTES - 1, MAX_MEMORY_CONTENT_BYTES):
            with patch(
                "clawrium.core.memory._resolve_openclaw_agent",
                return_value=(host, "opc-work"),
            ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
                "clawrium.core.memory.core_keys.get_host_private_key",
                return_value=ssh_key,
            ), patch(
                "clawrium.core.memory.ansible_runner.run", return_value=result
            ):
                ok, err = write_memory_file(
                    "h", "opc-work", "SOUL.md", "a" * size
                )
            assert ok is True, f"size {size} should be accepted"
            assert err is None

    def test_returns_false_on_pre_flight_oserror(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_write")

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory._get_logs_dir",
            side_effect=OSError("read-only filesystem"),
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
        with patch("clawrium.core.memory._resolve_openclaw_agent", return_value=None):
            ok, err = delete_memory_files("h", "a", ["SOUL.md"])
        assert ok is False

    def test_passes_files_list_through_to_playbook(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_delete")

        result = _runner_result("successful", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ) as mock_run:
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
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_delete")

        result = _runner_result("timeout", [])

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ):
            ok, err = delete_memory_files("h", "opc-work", ["SOUL.md"])
        assert ok is False
        assert err is not None and "timed out" in err

    def test_returns_false_on_runner_exception_offline(self, tmp_path: Path):
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, "memory_delete")

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run",
            side_effect=ConnectionError("host unreachable"),
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
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
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

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run", return_value=result
        ), patch(
            "clawrium.core.memory._cleanup_artifacts"
        ) as cleanup:
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
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, ssh_key = _setup_playbook_env(tmp_path, operation)

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=ssh_key
        ), patch(
            "clawrium.core.memory.ansible_runner.run",
            side_effect=ConnectionError("offline"),
        ), patch(
            "clawrium.core.memory._cleanup_artifacts"
        ) as cleanup:
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
        host = _host(
            {"opc-work": {"type": "openclaw", "agent_name": "opc-work"}}
        )
        playbook_dir, _ = _setup_playbook_env(tmp_path, operation)

        with patch(
            "clawrium.core.memory._resolve_openclaw_agent",
            return_value=(host, "opc-work"),
        ), patch("clawrium.core.memory._PLAYBOOK_DIR", playbook_dir), patch(
            "clawrium.core.memory.core_keys.get_host_private_key", return_value=None
        ):
            assert expect_falsy(call())

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


