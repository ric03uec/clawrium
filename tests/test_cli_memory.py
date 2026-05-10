"""Tests for CLI memory commands (clm agent <name> memory show|delete|edit)."""

import os
import contextlib
import stat
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch

from clawrium.cli.main import app
from clawrium.core.memory import MAX_MEMORY_CONTENT_BYTES

runner = CliRunner()


@contextlib.contextmanager
def _fake_tty():
    """Make the CLI's TTY check return True for the duration of the block.

    The CliRunner-injected stdin is a non-TTY pipe, which the --all --force
    path correctly rejects. Tests that exercise the typed-confirmation
    flow opt in to a TTY-like environment by patching the small helper
    that wraps the isatty call.
    """
    with patch("clawrium.cli.memory._stdin_is_tty", return_value=True):
        yield


# `hosts_with_installed_claw` (defined in conftest.py) registers a single
# openclaw agent — hostname=192.168.1.100, claw_type=openclaw, name=work,
# unix agent_name=opc-work. All tests below use that fixture.


# ----- show -----------------------------------------------------------------


def test_show_renders_table_when_info_available(hosts_with_installed_claw):
    info = {
        "workspace_path": "/home/opc-work/.openclaw/workspace",
        "total_bytes": 2048,
        "files": [
            {
                "name": "SOUL.md",
                "exists": True,
                "size_bytes": 1024,
                "relative_path": "SOUL.md",
            },
            {
                "name": "USER.md",
                "exists": False,
                "size_bytes": 0,
                "relative_path": "USER.md",
            },
            {
                "name": "2026-05-09.md",
                "exists": True,
                "size_bytes": 1024,
                "relative_path": "memory/2026-05-09.md",
            },
        ],
    }
    with patch("clawrium.cli.memory.get_memory_info", return_value=info):
        result = runner.invoke(app, ["agent", "memory", "show", "work"], env=os.environ)
    assert result.exit_code == 0, result.output
    assert "SOUL.md" in result.output
    assert "USER.md" in result.output
    assert "memory/2026-05-09.md" in result.output
    # Total rendered as human-readable.
    assert "2.0 KB" in result.output


def test_show_exits_nonzero_when_agent_not_found(hosts_with_installed_claw):
    result = runner.invoke(app, ["agent", "memory", "show", "ghost"], env=os.environ)
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_show_exits_with_unavailable_message_on_offline_host(
    hosts_with_installed_claw,
):
    with patch("clawrium.cli.memory.get_memory_info", return_value=None):
        result = runner.invoke(app, ["agent", "memory", "show", "work"], env=os.environ)
    assert result.exit_code != 0
    assert "unavailable" in result.output.lower()


# ----- delete: argument validation -----------------------------------------


def test_delete_requires_file_or_all(hosts_with_installed_claw):
    result = runner.invoke(app, ["agent", "memory", "delete", "work"], env=os.environ)
    assert result.exit_code != 0
    assert "either --file" in result.output


def test_delete_rejects_file_and_all_together(hosts_with_installed_claw):
    result = runner.invoke(
        app,
        ["agent", "memory", "delete", "work", "--file", "SOUL.md", "--all"],
        env=os.environ,
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


# ----- delete: single file --------------------------------------------------


def test_delete_single_file_with_confirmation(hosts_with_installed_claw):
    with patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--file", "SOUL.md"],
            input="y\n",
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    assert "Deleted 'SOUL.md'" in result.output
    args, _kwargs = mock_delete.call_args
    assert args[2] == ["SOUL.md"]


def test_delete_single_file_cancelled(hosts_with_installed_claw):
    with patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--file", "SOUL.md"],
            input="n\n",
            env=os.environ,
        )
    assert result.exit_code == 0
    assert "Cancelled" in result.output
    mock_delete.assert_not_called()


def test_delete_single_file_with_force_skips_prompt(hosts_with_installed_claw):
    with patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
        result = runner.invoke(
            app,
            [
                "agent",
                "memory",
                "delete",
                "work",
                "--file",
                "memory/2026-05-09.md",
                "--force",
            ],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    assert "Deleted 'memory/2026-05-09.md'" in result.output
    mock_delete.assert_called_once()


def test_delete_single_file_surfaces_core_error(hosts_with_installed_claw):
    with patch(
        "clawrium.cli.memory.delete_memory_files",
        return_value=(False, "agent unreachable"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "memory",
                "delete",
                "work",
                "--file",
                "SOUL.md",
                "--force",
            ],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "agent unreachable" in result.output


# ----- delete --all gating --------------------------------------------------


def test_delete_all_without_force_refuses(hosts_with_installed_claw):
    with patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "--force" in result.output
    mock_delete.assert_not_called()


def test_delete_all_force_requires_typed_confirmation(
    hosts_with_installed_claw,
):
    info = {
        "workspace_path": "/home/opc-work/.openclaw/workspace",
        "total_bytes": 100,
        "files": [
            {
                "name": "SOUL.md",
                "exists": True,
                "size_bytes": 50,
                "relative_path": "SOUL.md",
            },
            {
                "name": "USER.md",
                "exists": True,
                "size_bytes": 50,
                "relative_path": "USER.md",
            },
        ],
    }
    with (
        _fake_tty(),
        patch("clawrium.cli.memory.get_memory_info", return_value=info),
        patch(
            "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
        ) as mock_delete,
    ):
        # Wrong typed name → cancelled.
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            input="not-the-name\n",
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "Cancelled" in result.output
    mock_delete.assert_not_called()


def test_delete_all_force_with_correct_name_proceeds(
    hosts_with_installed_claw,
):
    info = {
        "workspace_path": "/home/opc-work/.openclaw/workspace",
        "total_bytes": 100,
        "files": [
            {
                "name": "SOUL.md",
                "exists": True,
                "size_bytes": 50,
                "relative_path": "SOUL.md",
            },
            {
                "name": "USER.md",
                "exists": False,
                "size_bytes": 0,
                "relative_path": "USER.md",
            },
            {
                "name": "2026-05-09.md",
                "exists": True,
                "size_bytes": 50,
                "relative_path": "memory/2026-05-09.md",
            },
        ],
    }
    with (
        _fake_tty(),
        patch("clawrium.cli.memory.get_memory_info", return_value=info),
        patch(
            "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
        ) as mock_delete,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            input="work\n",
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    # Only existing files are deleted; USER.md (missing) is excluded.
    args, _kwargs = mock_delete.call_args
    assert sorted(args[2]) == ["SOUL.md", "memory/2026-05-09.md"]
    assert "Deleted 2 memory file(s)" in result.output


def test_delete_all_force_when_no_files(hosts_with_installed_claw):
    info = {
        "workspace_path": "/home/opc-work/.openclaw/workspace",
        "total_bytes": 0,
        "files": [],
    }
    with (
        _fake_tty(),
        patch("clawrium.cli.memory.get_memory_info", return_value=info),
        patch(
            "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
        ) as mock_delete,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            env=os.environ,
        )
    assert result.exit_code == 0
    assert "No memory files" in result.output
    mock_delete.assert_not_called()


def test_delete_all_force_offline_host(hosts_with_installed_claw):
    with (
        _fake_tty(),
        patch("clawrium.cli.memory.get_memory_info", return_value=None),
        patch(
            "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
        ) as mock_delete,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "unavailable" in result.output.lower()
    mock_delete.assert_not_called()


def test_delete_all_force_refuses_when_stdin_not_tty(hosts_with_installed_claw):
    """B4: piped input must not be able to satisfy the typed confirmation.

    The CliRunner default already provides a non-TTY stdin, so we just
    invoke without _fake_tty and confirm the early refusal fires."""
    with (
        patch("clawrium.cli.memory.get_memory_info") as mock_info,
        patch("clawrium.cli.memory.delete_memory_files") as mock_delete,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            input="work\n",
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "TTY" in result.output
    # The TTY guard fires before either core call.
    mock_info.assert_not_called()
    mock_delete.assert_not_called()


# ----- routing fix coverage (B7) -------------------------------------------


def test_show_rejects_non_openclaw_agent(isolated_config):
    """Routing fix: agents with type != openclaw must be rejected with a
    clear message rather than running memory ops against them."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "192.168.1.100",
                    "alias": "server1",
                    "port": 22,
                    "agent_name": "xclm",
                    "agents": {
                        "zerowork": {
                            "type": "zeroclaw",
                            "agent_name": "zerowork",
                            "name": "zerowork",
                        }
                    },
                }
            ]
        )
    )

    result = runner.invoke(app, ["agent", "memory", "show", "zerowork"], env=os.environ)
    assert result.exit_code != 0
    assert "openclaw" in result.output.lower()
    assert "zeroclaw" in result.output.lower()


def test_delete_rejects_nonexistent_agent(hosts_with_installed_claw):
    result = runner.invoke(
        app,
        ["agent", "memory", "delete", "ghost", "--file", "SOUL.md", "--force"],
        env=os.environ,
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_delete_all_surfaces_core_failure(hosts_with_installed_claw):
    """When the underlying delete_memory_files returns (False, error) on the
    --all path, the CLI must surface that error and exit non-zero rather
    than printing a misleading success line."""
    info = {
        "workspace_path": "/home/opc-work/.openclaw/workspace",
        "total_bytes": 50,
        "files": [
            {
                "name": "SOUL.md",
                "exists": True,
                "size_bytes": 50,
                "relative_path": "SOUL.md",
            }
        ],
    }
    with (
        _fake_tty(),
        patch("clawrium.cli.memory.get_memory_info", return_value=info),
        patch(
            "clawrium.cli.memory.delete_memory_files",
            return_value=(False, "Host unreachable: timed out"),
        ),
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            input="work\n",
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "Host unreachable" in result.output


# ----- edit -----------------------------------------------------------------


def _make_editor(new_content=None, *, exit_code=0, delete_temp=False, observer=None):
    """Build a fake _run_editor that simulates editor side effects.

    new_content: str written to the temp file (None = leave file untouched)
    exit_code: editor return code
    delete_temp: if True, unlink the temp file before returning
    observer: optional callable(path) invoked while file still exists,
              useful for asserting file mode / contents mid-flight
    """

    def _editor(argv, file_path):
        if observer is not None:
            observer(file_path)
        if delete_temp:
            os.unlink(file_path)
        elif new_content is not None:
            Path(file_path).write_text(new_content, encoding="utf-8")
        return exit_code

    return _editor


def _restart_ok(*_args, **_kwargs):
    return {
        "success": True,
        "agent": "opc-work",
        "host": "192.168.1.100",
        "operation": "restart",
        "pid": 1234,
        "started_at": "2026-05-09T00:00:00Z",
        "error": None,
    }


@contextlib.contextmanager
def _running_agent():
    """Make _agent_runtime_status return 'running' so the restart path fires.

    The conftest fixture installs the agent without runtime.status, which
    defaults to 'stopped' under the new pre-flight check. Tests that need
    to exercise the restart code path opt in via this helper.
    """
    with patch(
        "clawrium.cli.memory._agent_runtime_status", return_value="running"
    ):
        yield


def test_edit_happy_path_writes_and_restarts(hosts_with_installed_claw):
    with (
        _fake_tty(),
        _running_agent(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            input="y\n",
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    args, _kwargs = mock_write.call_args
    assert args[2] == "SOUL.md"
    assert args[3] == "new\n"
    mock_restart.assert_called_once()
    assert "restarted agent" in result.output.lower()


def test_edit_unchanged_does_not_write(hosts_with_installed_claw):
    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="same\n"),
        patch("clawrium.cli.memory._run_editor", side_effect=_make_editor()),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    assert "No changes" in result.output
    mock_write.assert_not_called()
    mock_restart.assert_not_called()


def test_edit_editor_nonzero_exit_does_not_write(hosts_with_installed_claw):
    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="x\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="changed\n", exit_code=1),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            env=os.environ,
        )
    assert result.exit_code == 0
    assert "non-zero" in result.output
    mock_write.assert_not_called()
    mock_restart.assert_not_called()


def test_edit_temp_file_deleted_does_not_write(hosts_with_installed_claw):
    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="x\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(delete_temp=True),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            env=os.environ,
        )
    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()
    mock_write.assert_not_called()
    mock_restart.assert_not_called()


def test_edit_oversized_content_aborts_before_write(hosts_with_installed_claw):
    huge = "x" * (MAX_MEMORY_CONTENT_BYTES + 1)
    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="small\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content=huge),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "exceeds maximum size" in result.output
    mock_write.assert_not_called()
    mock_restart.assert_not_called()


def test_edit_unreachable_on_initial_read(hosts_with_installed_claw):
    with (
        patch("clawrium.cli.memory.read_memory_file", return_value=None),
        patch("clawrium.cli.memory._run_editor") as mock_editor,
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "unavailable" in result.output.lower()
    mock_editor.assert_not_called()
    mock_write.assert_not_called()


def test_edit_write_failure_surfaces_error(hosts_with_installed_claw):
    with (
        _fake_tty(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file",
            return_value=(False, "playbook failed"),
        ),
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            input="y\n",
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "playbook failed" in result.output
    mock_restart.assert_not_called()


def test_edit_restart_confirmation_declined(hosts_with_installed_claw):
    with (
        _fake_tty(),
        _running_agent(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            input="n\n",
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    mock_write.assert_called_once()
    mock_restart.assert_not_called()
    assert "not restarted" in result.output.lower()


def test_edit_no_restart_flag_skips_restart(hosts_with_installed_claw):
    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--no-restart"],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    mock_write.assert_called_once()
    mock_restart.assert_not_called()
    assert "skipping restart" in result.output.lower()


def test_edit_force_skips_confirmation(hosts_with_installed_claw):
    with (
        _running_agent(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch("clawrium.cli.memory.write_memory_file", return_value=(True, None)),
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--force"],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    mock_restart.assert_called_once()


def test_edit_non_tty_without_force_refuses_restart(hosts_with_installed_claw):
    # Default _stdin_is_tty() under CliRunner is False. No --force, no
    # --no-restart → must refuse the restart but the file is still saved.
    with (
        _running_agent(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file", return_value=(True, None)
        ) as mock_write,
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "TTY" in result.output
    mock_write.assert_called_once()
    mock_restart.assert_not_called()


def test_edit_temp_file_always_cleaned_up(hosts_with_installed_claw):
    captured = {}

    def _observe(path):
        captured["path"] = path
        captured["mode"] = stat.S_IMODE(os.stat(path).st_mode)

    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n", observer=_observe),
        ),
        patch(
            "clawrium.cli.memory.write_memory_file",
            return_value=(False, "boom"),
        ),
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--force"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert captured.get("mode") == 0o600
    assert not os.path.exists(captured["path"])


def test_edit_rejects_path_traversal(hosts_with_installed_claw):
    # The path validator lives in core; the CLI surfaces the same
    # "unavailable" path when read_memory_file rejects the input.
    with patch("clawrium.cli.memory._run_editor") as mock_editor:
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "../../../etc/passwd"],
            env=os.environ,
        )
    assert result.exit_code != 0
    mock_editor.assert_not_called()


def test_edit_rejects_non_openclaw_agent(isolated_config):
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "192.168.1.100",
                    "alias": "server1",
                    "port": 22,
                    "agent_name": "xclm",
                    "agents": {
                        "zerowork": {
                            "type": "zeroclaw",
                            "agent_name": "zerowork",
                            "name": "zerowork",
                        }
                    },
                }
            ]
        )
    )

    result = runner.invoke(
        app,
        ["agent", "memory", "edit", "zerowork", "SOUL.md"],
        env=os.environ,
    )
    assert result.exit_code != 0
    assert "openclaw" in result.output.lower()


def test_edit_restart_returns_failure_surfaces_error(hosts_with_installed_claw):
    """When restart_agent returns success=False, we must print Saved + the
    restart error, then exit 1."""
    failure = {
        "success": False,
        "agent": "opc-work",
        "host": "192.168.1.100",
        "operation": "restart",
        "pid": None,
        "started_at": None,
        "error": "Stop failed: timed out",
    }
    with (
        _running_agent(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch("clawrium.cli.memory.write_memory_file", return_value=(True, None)),
        patch(
            "clawrium.cli.memory.restart_agent", return_value=failure
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--force"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "Saved" in result.output
    assert "timed out" in result.output
    # Rich may wrap the phrase across lines; check the unwrapped output.
    assert "may now be stopped" in " ".join(result.output.split())
    mock_restart.assert_called_once()


def test_edit_restart_raises_lifecycle_error_surfaces_error(
    hosts_with_installed_claw,
):
    """If restart_agent raises LifecycleError, we must surface it cleanly
    rather than letting a traceback leak. The user must still see that the
    file was saved before the restart attempt failed."""
    from clawrium.core.lifecycle import LifecycleError

    with (
        _running_agent(),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch("clawrium.cli.memory.write_memory_file", return_value=(True, None)),
        patch(
            "clawrium.cli.memory.restart_agent",
            side_effect=LifecycleError("Host '192.168.1.100' not found"),
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--force"],
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "Saved" in result.output
    assert "not found" in result.output
    # Rich may wrap the phrase across lines; check the unwrapped output.
    assert "may now be stopped" in " ".join(result.output.split())
    mock_restart.assert_called_once()
    # No raw Python traceback in the output.
    assert "Traceback" not in result.output


def test_edit_skips_restart_when_agent_not_running(hosts_with_installed_claw):
    """If the agent is stopped, edit must not call restart_agent — that
    would unintentionally start a stopped agent (since restart = stop +
    start, and stop is idempotent)."""
    with (
        patch(
            "clawrium.cli.memory._agent_runtime_status", return_value="stopped"
        ),
        patch("clawrium.cli.memory.read_memory_file", return_value="old\n"),
        patch(
            "clawrium.cli.memory._run_editor",
            side_effect=_make_editor(new_content="new\n"),
        ),
        patch("clawrium.cli.memory.write_memory_file", return_value=(True, None)),
        patch(
            "clawrium.cli.memory.restart_agent", side_effect=_restart_ok
        ) as mock_restart,
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--force"],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    mock_restart.assert_not_called()
    flat = " ".join(result.output.split()).lower()
    assert "stopped" in flat
    assert "next start" in flat


def test_edit_no_shell_invocation(hosts_with_installed_claw):
    """Editor must be spawned with shell=False (default) and an argv list,
    so user-controlled $EDITOR can never be interpreted as a shell command.
    """
    captured_kwargs = {}
    captured_args = {}

    class _Result:
        returncode = 0

    def _fake_run(*args, **kwargs):
        captured_args["args"] = args
        captured_kwargs.update(kwargs)
        return _Result()

    with (
        patch("clawrium.cli.memory.read_memory_file", return_value="x\n"),
        patch("clawrium.cli.memory.subprocess.run", side_effect=_fake_run),
    ):
        runner.invoke(
            app,
            ["agent", "memory", "edit", "work", "SOUL.md", "--no-restart"],
            env=os.environ,
        )
    # subprocess.run was called with a list as the first positional arg
    # and shell is either absent (default False) or explicitly False.
    argv = captured_args["args"][0]
    assert isinstance(argv, list)
    assert captured_kwargs.get("shell", False) is False
