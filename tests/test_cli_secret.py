"""Tests for CLI secret commands."""

import json
import os
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch

from clawrium.cli.main import app

runner = CliRunner()


# Helper to create custom host setups for tests that need specific configs
def _create_hosts_json(isolated_config: Path, hosts_data: list) -> None:
    """Create hosts.json with custom data."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps(hosts_data, indent=2))


def test_secret_set_creates_new(hosts_with_installed_claw: Path):
    """clm secret set <claw_name> KEY prompts for value and creates secret."""
    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-secret-value"):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "TEST_KEY"], env=os.environ
        )

    assert result.exit_code == 0
    assert "created" in result.output.lower()

    # Verify secret was stored under instance key
    secrets_file = hosts_with_installed_claw / "secrets.json"
    assert secrets_file.exists()
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert instance_key in secrets
    assert "TEST_KEY" in secrets[instance_key]
    assert secrets[instance_key]["TEST_KEY"]["value"] == "my-secret-value"


def test_secret_set_with_description(hosts_with_installed_claw: Path):
    """clm secret set <claw_name> KEY --description saves description."""
    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-value"):
        result = runner.invoke(
            app,
            [
                "agent",
                "secret",
                "set",
                "work",
                "API_KEY",
                "--description",
                "My API key",
            ],
            env=os.environ,
        )

    assert result.exit_code == 0

    # Verify description was stored
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert secrets[instance_key]["API_KEY"]["description"] == "My API key"


def test_secret_set_update_existing(hosts_with_installed_claw: Path):
    """clm secret set <claw_name> KEY on existing key prompts for confirmation."""
    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(
            app, ["agent", "secret", "set", "work", "EXISTING_KEY"], env=os.environ
        )

    # Try to update - cancel confirmation
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app,
            ["agent", "secret", "set", "work", "EXISTING_KEY"],
            input="n\n",
            env=os.environ,
        )

    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()

    # Verify value unchanged
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert secrets[instance_key]["EXISTING_KEY"]["value"] == "old-value"


def test_secret_set_update_confirmed(hosts_with_installed_claw: Path):
    """clm secret set <claw_name> KEY on existing key with confirmation updates value."""
    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(
            app, ["agent", "secret", "set", "work", "EXISTING_KEY"], env=os.environ
        )

    # Update with confirmation
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app,
            ["agent", "secret", "set", "work", "EXISTING_KEY"],
            input="y\n",
            env=os.environ,
        )

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    # Verify value changed
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert secrets[instance_key]["EXISTING_KEY"]["value"] == "new-value"


def test_secret_set_yes_flag_skips_confirmation(hosts_with_installed_claw: Path):
    """clm secret set <claw_name> KEY --yes skips overwrite confirmation."""
    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(app, ["agent", "secret", "set", "work", "KEY"], env=os.environ)

    # Update with --yes flag (no input needed)
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "KEY", "--yes"], env=os.environ
        )

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    # Verify value changed
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert secrets[instance_key]["KEY"]["value"] == "new-value"


def test_secret_set_empty_value_rejected(hosts_with_installed_claw: Path):
    """clm secret set <claw_name> KEY with empty value shows error."""
    with patch("clawrium.cli.secret.getpass.getpass", return_value=""):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "EMPTY_KEY"], env=os.environ
        )

    assert result.exit_code == 1
    assert "cannot be empty" in result.output.lower()


def test_secret_set_invalid_key_format(hosts_with_installed_claw: Path):
    """clm secret set with invalid key format shows error and hint."""
    # Test lowercase key
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "lowercase_key"], env=os.environ
        )
    assert result.exit_code == 1
    assert "hint" in result.output.lower()

    # Test digit-start key
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "1KEY"], env=os.environ
        )
    assert result.exit_code == 1
    assert "hint" in result.output.lower()

    # Test special-char key
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "KEY:BAD"], env=os.environ
        )
    assert result.exit_code == 1
    assert "hint" in result.output.lower()


def test_secret_set_keyboard_interrupt(hosts_with_installed_claw: Path):
    """clm secret set handles Ctrl-C during password input."""
    with patch("clawrium.cli.secret.getpass.getpass", side_effect=KeyboardInterrupt):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "TEST_KEY"], env=os.environ
        )

    assert result.exit_code == 1
    assert "cancelled" in result.output.lower()


def test_secret_set_eof_error(hosts_with_installed_claw: Path):
    """clm secret set handles EOF during password input."""
    with patch("clawrium.cli.secret.getpass.getpass", side_effect=EOFError):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "TEST_KEY"], env=os.environ
        )

    assert result.exit_code == 1
    assert "cancelled" in result.output.lower()


def test_secret_set_corrupted_secrets_file(hosts_with_installed_claw: Path):
    """clm secret set with corrupted secrets.json shows error."""
    # Create corrupted secrets file
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets_file.write_text("{invalid json")

    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        result = runner.invoke(
            app, ["agent", "secret", "set", "work", "TEST_KEY"], env=os.environ
        )

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_secret_list_corrupted_secrets_file(hosts_with_installed_claw: Path):
    """clm secret list with corrupted secrets.json shows error."""
    # Create corrupted secrets file
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets_file.write_text("{invalid json")

    result = runner.invoke(app, ["agent", "secret", "list", "work"], env=os.environ)

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_secret_remove_corrupted_secrets_file(hosts_with_installed_claw: Path):
    """clm secret remove with corrupted secrets.json shows error."""
    # Create corrupted secrets file
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets_file.write_text("{invalid json")

    result = runner.invoke(
        app, ["agent", "secret", "remove", "work", "KEY", "--force"], env=os.environ
    )

    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_secret_list_empty(hosts_with_installed_claw: Path):
    """clm secret list with no secrets shows appropriate message."""
    result = runner.invoke(app, ["agent", "secret", "list", "work"], env=os.environ)

    assert result.exit_code == 0
    # Should show claw with "No secrets set"
    assert "work" in result.output


def test_secret_list_shows_keys_not_values(hosts_with_installed_claw: Path):
    """clm secret list shows table with keys and metadata, not values."""
    # Create test secrets
    with patch("clawrium.cli.secret.getpass.getpass", return_value="secret-value-1"):
        runner.invoke(
            app,
            ["agent", "secret", "set", "work", "KEY1", "--description", "First key"],
            env=os.environ,
        )

    with patch("clawrium.cli.secret.getpass.getpass", return_value="secret-value-2"):
        runner.invoke(
            app,
            ["agent", "secret", "set", "work", "KEY2", "--description", "Second key"],
            env=os.environ,
        )

    result = runner.invoke(app, ["agent", "secret", "list", "work"], env=os.environ)

    assert result.exit_code == 0
    # Should show keys
    assert "KEY1" in result.output
    assert "KEY2" in result.output
    # Should show descriptions
    assert "First key" in result.output
    assert "Second key" in result.output
    # Should NOT show values
    assert "secret-value-1" not in result.output
    assert "secret-value-2" not in result.output


def test_secret_list_shows_missing_required_secrets(hosts_with_installed_claw: Path):
    """clm secret list shows missing required secrets per claw instance."""
    result = runner.invoke(app, ["agent", "secret", "list", "work"], env=os.environ)

    assert result.exit_code == 0
    # Should show claw and missing secrets
    assert "work" in result.output
    assert "OPENAI_API_KEY" in result.output
    assert "Missing" in result.output or "missing" in result.output


def test_secret_list_no_missing_when_all_set(hosts_with_installed_claw: Path):
    """clm secret list does not show missing section when all required secrets set."""
    # Set all required secrets for openclaw
    with patch("clawrium.cli.secret.getpass.getpass", return_value="sk-test"):
        runner.invoke(
            app, ["agent", "secret", "set", "work", "OPENAI_API_KEY"], env=os.environ
        )

    result = runner.invoke(app, ["agent", "secret", "list", "work"], env=os.environ)

    assert result.exit_code == 0
    # Should show the stored secret
    assert "OPENAI_API_KEY" in result.output
    # Should NOT show missing section
    assert "Missing:" not in result.output


def test_secret_remove_prompts_confirmation(hosts_with_installed_claw: Path):
    """clm secret remove <claw_name> KEY prompts for confirmation."""
    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(
            app, ["agent", "secret", "set", "work", "TO_REMOVE"], env=os.environ
        )

    # Try to remove - cancel
    result = runner.invoke(
        app,
        ["agent", "secret", "remove", "work", "TO_REMOVE"],
        input="n\n",
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()

    # Verify secret still exists
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert "TO_REMOVE" in secrets[instance_key]


def test_secret_remove_confirmed(hosts_with_installed_claw: Path):
    """clm secret remove <claw_name> KEY with confirmation removes secret."""
    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(
            app, ["agent", "secret", "set", "work", "TO_REMOVE"], env=os.environ
        )

    # Remove with confirmation
    result = runner.invoke(
        app,
        ["agent", "secret", "remove", "work", "TO_REMOVE"],
        input="y\n",
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "removed" in result.output.lower()

    # Verify secret was removed
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    # Instance key should be removed entirely since it has no secrets
    assert instance_key not in secrets


def test_secret_remove_force_skips_confirmation(hosts_with_installed_claw: Path):
    """clm secret remove <claw_name> KEY --force skips confirmation prompt."""
    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(
            app, ["agent", "secret", "set", "work", "TO_REMOVE"], env=os.environ
        )

    # Remove with --force (no input needed)
    result = runner.invoke(
        app,
        ["agent", "secret", "remove", "work", "TO_REMOVE", "--force"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "removed" in result.output.lower()

    # Verify secret was removed
    secrets_file = hosts_with_installed_claw / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "192.168.1.100:openclaw:work"
    assert instance_key not in secrets


def test_secret_remove_nonexistent_shows_error(hosts_with_installed_claw: Path):
    """clm secret remove <claw_name> KEY for non-existent key shows error."""
    result = runner.invoke(
        app, ["agent", "secret", "remove", "work", "NONEXISTENT"], env=os.environ
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# Per-claw secret tests (Phase 06 Plan 02) - tests with different host configs


def test_secret_set_with_claw(isolated_config: Path):
    """clm secret set <claw_name> KEY prompts for value and stores for that claw."""
    _create_hosts_json(
        isolated_config,
        [
            {
                "hostname": "wolf",
                "alias": "wolf",
                "claws": {
                    "openclaw": {
                        "name": "opc-work",
                        "status": "installed",
                        "user": "opc-work",
                    }
                },
            }
        ],
    )

    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-secret-value"):
        result = runner.invoke(
            app,
            ["agent", "secret", "set", "opc-work", "OPENAI_API_KEY"],
            env=os.environ,
        )

    assert result.exit_code == 0
    assert "created" in result.output.lower()

    # Verify secret was stored under instance key
    secrets_file = isolated_config / "secrets.json"
    assert secrets_file.exists()
    secrets = json.loads(secrets_file.read_text())
    instance_key = "wolf:openclaw:opc-work"
    assert instance_key in secrets
    assert "OPENAI_API_KEY" in secrets[instance_key]
    assert secrets[instance_key]["OPENAI_API_KEY"]["value"] == "my-secret-value"


def test_secret_set_claw_not_found(isolated_config: Path):
    """clm secret set <claw_name> KEY shows error when claw doesn't exist."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-value"):
        result = runner.invoke(
            app,
            ["agent", "secret", "set", "nonexistent-claw", "API_KEY"],
            env=os.environ,
        )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()
    assert "nonexistent-claw" in result.output


def test_secret_set_with_claw_update_confirmed(isolated_config: Path):
    """clm secret set <claw_name> KEY with confirmation updates value for that claw."""
    _create_hosts_json(
        isolated_config,
        [
            {
                "hostname": "wolf",
                "alias": "wolf",
                "claws": {
                    "openclaw": {
                        "name": "opc-work",
                        "status": "installed",
                        "user": "opc-work",
                    }
                },
            }
        ],
    )

    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(
            app, ["agent", "secret", "set", "opc-work", "API_KEY"], env=os.environ
        )

    # Update with confirmation
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app,
            ["agent", "secret", "set", "opc-work", "API_KEY"],
            input="y\n",
            env=os.environ,
        )

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    # Verify value changed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "wolf:openclaw:opc-work"
    assert secrets[instance_key]["API_KEY"]["value"] == "new-value"


def test_secret_list_per_claw(isolated_config: Path):
    """clm secret list <claw_name> shows secrets for that specific claw."""
    _create_hosts_json(
        isolated_config,
        [
            {
                "hostname": "wolf",
                "alias": "wolf",
                "claws": {
                    "openclaw": {
                        "name": "opc-work",
                        "status": "installed",
                        "user": "opc-work",
                    }
                },
            },
            {
                "hostname": "bear",
                "alias": "bear",
                "claws": {
                    "openclaw": {
                        "name": "opc-personal",
                        "status": "installed",
                        "user": "opc-personal",
                    }
                },
            },
        ],
    )

    # Create secrets for both claws
    with patch("clawrium.cli.secret.getpass.getpass", return_value="work-key"):
        runner.invoke(
            app,
            ["agent", "secret", "set", "opc-work", "OPENAI_API_KEY"],
            env=os.environ,
        )

    with patch("clawrium.cli.secret.getpass.getpass", return_value="personal-key"):
        runner.invoke(
            app,
            ["agent", "secret", "set", "opc-personal", "OPENAI_API_KEY"],
            env=os.environ,
        )

    # List secrets for opc-work only
    result = runner.invoke(app, ["agent", "secret", "list", "opc-work"], env=os.environ)

    assert result.exit_code == 0
    assert "opc-work" in result.output
    assert "wolf" in result.output
    assert "OPENAI_API_KEY" in result.output
    # Should NOT show the other claw
    assert "opc-personal" not in result.output
    assert "bear" not in result.output


def test_secret_list_shows_missing_required(isolated_config: Path):
    """clm secret list shows missing required secrets per claw instance."""
    _create_hosts_json(
        isolated_config,
        [
            {
                "hostname": "wolf",
                "alias": "wolf",
                "claws": {
                    "openclaw": {
                        "name": "opc-work",
                        "status": "installed",
                        "user": "opc-work",
                    }
                },
            }
        ],
    )

    result = runner.invoke(app, ["agent", "secret", "list", "opc-work"], env=os.environ)

    assert result.exit_code == 0
    # Should show claw
    assert "opc-work" in result.output
    # Should show missing required secrets
    assert "Missing" in result.output or "missing" in result.output
    assert "OPENAI_API_KEY" in result.output


def test_secret_list_claw_not_found(isolated_config: Path):
    """clm secret list with non-existent claw shows error."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create empty hosts file
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text("[]")

    result = runner.invoke(
        app, ["agent", "secret", "list", "nonexistent"], env=os.environ
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "error" in result.output.lower()


def test_secret_remove_with_claw(isolated_config: Path):
    """clm secret remove <claw_name> KEY removes from specific claw."""
    _create_hosts_json(
        isolated_config,
        [
            {
                "hostname": "wolf",
                "alias": "wolf",
                "claws": {
                    "openclaw": {
                        "name": "opc-work",
                        "status": "installed",
                        "user": "opc-work",
                    }
                },
            }
        ],
    )

    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(
            app, ["agent", "secret", "set", "opc-work", "TO_REMOVE"], env=os.environ
        )

    # Remove with confirmation
    result = runner.invoke(
        app,
        ["agent", "secret", "remove", "opc-work", "TO_REMOVE"],
        input="y\n",
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "removed" in result.output.lower()

    # Verify secret was removed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "wolf:openclaw:opc-work"
    # Instance key should be removed entirely since it has no secrets
    assert instance_key not in secrets


def test_secret_remove_claw_not_found(isolated_config: Path):
    """clm secret remove <claw_name> KEY shows error when claw doesn't exist."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(
        app, ["agent", "secret", "remove", "nonexistent", "KEY"], env=os.environ
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()
