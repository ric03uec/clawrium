"""Tests for `clawctl provider registry` CRUD verbs.

The fleet_dir fixture isolates `XDG_CONFIG_HOME` so providers.json,
secrets.json, and hosts.json live inside a tmp directory.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_create_anthropic_with_api_key(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "my-anthropic",
            "--type",
            "anthropic",
            "--model",
            "claude-opus-4-20250514",
            "--api-key",
            "sk-test-abc",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "provider/my-anthropic" in result.output
    assert "created" in result.output


def test_create_requires_api_key_on_non_tty(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["provider", "registry", "create", "p", "--type", "anthropic"],
    )
    assert result.exit_code != 0
    assert "missing required flag --api-key" in result.output


def test_create_api_key_stdin_reads_value(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "stdin-anthropic",
            "--type",
            "anthropic",
            "--api-key-stdin",
        ],
        input="sk-piped-key\n",
    )
    assert result.exit_code == 0, result.output


def test_create_duplicate_fails(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dup",
            "--type",
            "anthropic",
            "--api-key",
            "sk-x",
        ],
    )
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dup",
            "--type",
            "anthropic",
            "--api-key",
            "sk-x",
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_bedrock_with_aws_triplet(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "my-bedrock",
            "--type",
            "bedrock",
            "--access-key",
            "AKIA",
            "--secret-key",
            "secret",
            "--region",
            "us-west-2",
        ],
    )
    assert result.exit_code == 0, result.output


def test_create_bedrock_missing_access_key_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "no-creds",
            "--type",
            "bedrock",
            "--secret-key",
            "secret",
        ],
    )
    assert result.exit_code != 0
    assert "missing required flag --access-key" in result.output


def test_get_lists_providers(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "p1",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "get"])
    assert result.exit_code == 0, result.output
    assert "p1" in result.output
    assert "anthropic" in result.output


def test_get_json_emits_array(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "jp",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "get", "-o", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert any(p["name"] == "jp" for p in data)


def test_get_name_format(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "n1",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "get", "-o", "name"])
    assert result.exit_code == 0
    assert "provider/n1" in result.output


def test_get_types_lists_catalog(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["provider", "registry", "get", "--types"])
    assert result.exit_code == 0
    # PROVIDER_MODELS has at least anthropic + openai + ollama
    assert "anthropic" in result.output
    assert "ollama" in result.output


def test_describe_unknown_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["provider", "registry", "describe", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_describe_known(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "d1",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "describe", "d1"])
    assert result.exit_code == 0
    assert "Name:" in result.output
    assert "d1" in result.output
    assert "anthropic" in result.output


def test_edit_model(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "e1",
            "--type",
            "anthropic",
            "--model",
            "old-model",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(
        app,
        ["provider", "registry", "edit", "e1", "--model", "new-model"],
    )
    assert result.exit_code == 0, result.output
    desc = runner.invoke(app, ["provider", "registry", "describe", "e1", "-o", "json"])
    data = json.loads(desc.output)
    assert data[0]["model"] == "new-model"


def test_edit_no_args_fails(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "e2",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "edit", "e2"])
    assert result.exit_code != 0


def test_delete_requires_yes_on_non_tty(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dx",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "delete", "dx"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_delete_with_yes_removes_record(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dy",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "delete", "dy", "--yes"])
    assert result.exit_code == 0
    # Now describing returns not-found.
    desc = runner.invoke(app, ["provider", "registry", "describe", "dy"])
    assert desc.exit_code != 0
