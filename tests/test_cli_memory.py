"""Tests for CLI memory commands (clm agent <name> memory show|delete)."""

import os
import contextlib
from typer.testing import CliRunner
from unittest.mock import patch

from clawrium.cli.main import app

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
        result = runner.invoke(
            app, ["agent", "memory", "show", "work"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    assert "SOUL.md" in result.output
    assert "USER.md" in result.output
    assert "memory/2026-05-09.md" in result.output
    # Total rendered as human-readable.
    assert "2.0 KB" in result.output


def test_show_exits_nonzero_when_agent_not_found(hosts_with_installed_claw):
    result = runner.invoke(
        app, ["agent", "memory", "show", "ghost"], env=os.environ
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_show_exits_with_unavailable_message_on_offline_host(
    hosts_with_installed_claw,
):
    with patch("clawrium.cli.memory.get_memory_info", return_value=None):
        result = runner.invoke(
            app, ["agent", "memory", "show", "work"], env=os.environ
        )
    assert result.exit_code != 0
    assert "unavailable" in result.output.lower()


# ----- delete: argument validation -----------------------------------------


def test_delete_requires_file_or_all(hosts_with_installed_claw):
    result = runner.invoke(
        app, ["agent", "memory", "delete", "work"], env=os.environ
    )
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
    with _fake_tty(), patch(
        "clawrium.cli.memory.get_memory_info", return_value=info
    ), patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
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
    with _fake_tty(), patch(
        "clawrium.cli.memory.get_memory_info", return_value=info
    ), patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
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
    with _fake_tty(), patch(
        "clawrium.cli.memory.get_memory_info", return_value=info
    ), patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            env=os.environ,
        )
    assert result.exit_code == 0
    assert "No memory files" in result.output
    mock_delete.assert_not_called()


def test_delete_all_force_offline_host(hosts_with_installed_claw):
    with _fake_tty(), patch(
        "clawrium.cli.memory.get_memory_info", return_value=None
    ), patch(
        "clawrium.cli.memory.delete_memory_files", return_value=(True, None)
    ) as mock_delete:
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
    with patch(
        "clawrium.cli.memory.get_memory_info"
    ) as mock_info, patch(
        "clawrium.cli.memory.delete_memory_files"
    ) as mock_delete:
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

    result = runner.invoke(
        app, ["agent", "memory", "show", "zerowork"], env=os.environ
    )
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
    with _fake_tty(), patch(
        "clawrium.cli.memory.get_memory_info", return_value=info
    ), patch(
        "clawrium.cli.memory.delete_memory_files",
        return_value=(False, "Host unreachable: timed out"),
    ):
        result = runner.invoke(
            app,
            ["agent", "memory", "delete", "work", "--all", "--force"],
            input="work\n",
            env=os.environ,
        )
    assert result.exit_code != 0
    assert "Host unreachable" in result.output
