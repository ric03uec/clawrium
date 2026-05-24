"""Tests for `clawctl agent secret create|get|describe|delete|import`."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_create_value_flag(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "FOO",
            "--agent",
            "wise-hypatia",
            "--value",
            "bar",
        ],
    )
    assert result.exit_code == 0, result.output


def test_create_value_stdin(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "BAZ",
            "--agent",
            "wise-hypatia",
            "--value-stdin",
        ],
        input="value-from-stdin\n",
    )
    assert result.exit_code == 0, result.output


def test_create_from_file(fleet_dir, stdin_not_tty, tmp_path: Path) -> None:
    f = tmp_path / "value.txt"
    f.write_text("from-file-value")
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "FROMFILE",
            "--agent",
            "wise-hypatia",
            "--from-file",
            str(f),
        ],
    )
    assert result.exit_code == 0, result.output


def test_create_requires_value_on_non_tty(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app, ["agent", "secret", "create", "NEEDS_VALUE", "--agent", "wise-hypatia"]
    )
    assert result.exit_code != 0


def test_create_rejects_multiple_sources(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "DUAL",
            "--agent",
            "wise-hypatia",
            "--value",
            "x",
            "--value-stdin",
        ],
        input="y\n",
    )
    assert result.exit_code != 0


def test_get_lists_keys_no_values(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "FOO",
            "--agent",
            "wise-hypatia",
            "--value",
            "supersecret",
        ],
    )
    result = runner.invoke(app, ["agent", "secret", "get", "--agent", "wise-hypatia"])
    assert result.exit_code == 0
    assert "FOO" in result.output
    assert "supersecret" not in result.output


def test_describe_metadata(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "FOO",
            "--agent",
            "wise-hypatia",
            "--value",
            "bar",
            "--description",
            "test description",
        ],
    )
    result = runner.invoke(
        app, ["agent", "secret", "describe", "FOO", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0
    assert "test description" in result.output
    # Value must NEVER appear in describe output.
    assert "bar" not in result.output.split("Description:")[-1]


def test_delete_requires_yes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "DELME",
            "--agent",
            "wise-hypatia",
            "--value",
            "x",
        ],
    )
    result = runner.invoke(
        app, ["agent", "secret", "delete", "DELME", "--agent", "wise-hypatia"]
    )
    assert result.exit_code != 0


def test_delete_with_yes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "DELME",
            "--agent",
            "wise-hypatia",
            "--value",
            "x",
        ],
    )
    result = runner.invoke(
        app,
        ["agent", "secret", "delete", "DELME", "--agent", "wise-hypatia", "--yes"],
    )
    assert result.exit_code == 0


def test_import_env_file(fleet_dir, stdin_not_tty, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('FOO=one\nBAR=two\n# comment\n\nBAZ="quoted"\n')
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "import",
            "--agent",
            "wise-hypatia",
            "--from-file",
            str(env),
        ],
    )
    assert result.exit_code == 0, result.output
    listed = runner.invoke(
        app, ["agent", "secret", "get", "--agent", "wise-hypatia", "-o", "json"]
    )
    data = json.loads(listed.output)
    names = {row["name"] for row in data}
    assert {"FOO", "BAR", "BAZ"} <= names


def test_import_rejects_invalid_lines(fleet_dir, stdin_not_tty, tmp_path: Path) -> None:
    env = tmp_path / "broken.env"
    env.write_text("no_equals_sign_here\n")
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "import",
            "--agent",
            "wise-hypatia",
            "--from-file",
            str(env),
        ],
    )
    assert result.exit_code != 0
