"""Tests for `clawctl integration registry` CRUD verbs."""

from __future__ import annotations


from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_create_github_non_interactive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "gh",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=ghp_test",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/gh" in result.output


def test_create_requires_type(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["integration", "registry", "create", "no-type", "--credential", "K=V"],
    )
    assert result.exit_code != 0


def test_create_unknown_type_rejected(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "x",
            "--type",
            "no-such-type",
            "--credential",
            "K=V",
        ],
    )
    assert result.exit_code != 0


def test_create_missing_required_credentials_fails(fleet_dir, stdin_not_tty) -> None:
    # github requires GITHUB_TOKEN; passing a non-matching key fails.
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "bad",
            "--type",
            "github",
            "--credential",
            "OTHER=VAL",
        ],
    )
    assert result.exit_code != 0
    assert "missing required credential" in result.output


def test_create_credential_stdin(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "stdin-gh",
            "--type",
            "github",
            "--credential-stdin",
        ],
        input="GITHUB_TOKEN=ghp_stdin\n",
    )
    assert result.exit_code == 0, result.output


def test_create_credential_kv_must_have_equals(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "bad-kv",
            "--type",
            "github",
            "--credential",
            "no-equals-sign",
        ],
    )
    assert result.exit_code != 0


def test_create_credential_empty_key_does_not_leak_value(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-2 W-NEW-2: `=secret-value` must not echo the value in
    the error message. Empty-key entries are operator errors but the
    half after `=` is sensitive."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "leaky",
            "--type",
            "github",
            "--credential",
            "=ghp_test_secret_value",
        ],
    )
    assert result.exit_code != 0
    # The raw value must NOT appear in stderr/stdout.
    assert "ghp_test_secret_value" not in result.output
    # The error must still name the failure reason.
    assert "key is empty" in result.output


def test_create_credential_stdin_empty_key_does_not_leak_value(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-7: same redaction contract for the stdin path."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "leaky-stdin",
            "--type",
            "github",
            "--credential-stdin",
        ],
        input="=ghp_stdin_secret_value\n",
    )
    assert result.exit_code != 0
    assert "ghp_stdin_secret_value" not in result.output
    assert "key is empty" in result.output


def test_create_credential_whitespace_key_does_not_leak_value(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-7: a whitespace-only key (`' =VAL'`) strips to
    empty and must not echo the value either."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "leaky-ws",
            "--type",
            "github",
            "--credential",
            "   =ghp_whitespace_secret_value",
        ],
    )
    assert result.exit_code != 0
    assert "ghp_whitespace_secret_value" not in result.output


def test_get_lists_integrations(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "l1",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "get"])
    assert result.exit_code == 0
    assert "l1" in result.output


def test_get_types_lists_catalog(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["integration", "registry", "get", "--types"])
    assert result.exit_code == 0
    assert "github" in result.output


def test_describe_known(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "d1",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "describe", "d1"])
    assert result.exit_code == 0
    assert "github" in result.output


def test_edit_updates_credential(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "e1",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=old",
        ],
    )
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "edit",
            "e1",
            "--credential",
            "GITHUB_TOKEN=new",
        ],
    )
    assert result.exit_code == 0


def test_delete_requires_yes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "dx",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "delete", "dx"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_delete_with_yes_removes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "dy",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "delete", "dy", "--yes"])
    assert result.exit_code == 0
