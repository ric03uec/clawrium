"""Tests for CLI secret commands."""

import json
import os
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch

from clawrium.cli.main import app

runner = CliRunner()


def test_secret_set_creates_new(isolated_config: Path):
    """clm secret set <claw_name> KEY prompts for value and creates secret."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": "testhost",
            "alias": "testhost",
            "claws": {
                "openclaw": {
                    "name": "test-claw",
                    "status": "installed",
                    "user": "test-user",
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-secret-value"):
        result = runner.invoke(
            app, ["secret", "set", "test-claw", "TEST_KEY"], env=os.environ
        )

    assert result.exit_code == 0
    assert "created" in result.output.lower()

    # Verify secret was stored under instance key
    secrets_file = isolated_config / "secrets.json"
    assert secrets_file.exists()
    secrets = json.loads(secrets_file.read_text())
    instance_key = "testhost:openclaw:test-claw"
    assert instance_key in secrets
    assert "TEST_KEY" in secrets[instance_key]
    assert secrets[instance_key]["TEST_KEY"]["value"] == "my-secret-value"


def test_secret_set_with_description(isolated_config: Path):
    """clm secret set <claw_name> KEY --description saves description."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": "testhost",
            "alias": "testhost",
            "claws": {
                "openclaw": {
                    "name": "test-claw",
                    "status": "installed",
                    "user": "test-user",
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-value"):
        result = runner.invoke(
            app,
            ["secret", "set", "test-claw", "API_KEY", "--description", "My API key"],
            env=os.environ,
        )

    assert result.exit_code == 0

    # Verify description was stored
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "testhost:openclaw:test-claw"
    assert secrets[instance_key]["API_KEY"]["description"] == "My API key"


def test_secret_set_update_existing(isolated_config: Path):
    """clm secret set <claw_name> KEY on existing key prompts for confirmation."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": "testhost",
            "alias": "testhost",
            "claws": {
                "openclaw": {
                    "name": "test-claw",
                    "status": "installed",
                    "user": "test-user",
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(app, ["secret", "set", "test-claw", "EXISTING_KEY"], env=os.environ)

    # Try to update - cancel confirmation
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app, ["secret", "set", "test-claw", "EXISTING_KEY"], input="n\n", env=os.environ
        )

    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()

    # Verify value unchanged
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "testhost:openclaw:test-claw"
    assert secrets[instance_key]["EXISTING_KEY"]["value"] == "old-value"


def test_secret_set_update_confirmed(isolated_config: Path):
    """clm secret set <claw_name> KEY on existing key with confirmation updates value."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": "testhost",
            "alias": "testhost",
            "claws": {
                "openclaw": {
                    "name": "test-claw",
                    "status": "installed",
                    "user": "test-user",
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(app, ["secret", "set", "test-claw", "EXISTING_KEY"], env=os.environ)

    # Update with confirmation
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app, ["secret", "set", "test-claw", "EXISTING_KEY"], input="y\n", env=os.environ
        )

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    # Verify value changed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "testhost:openclaw:test-claw"
    assert secrets[instance_key]["EXISTING_KEY"]["value"] == "new-value"


def test_secret_set_yes_flag_skips_confirmation(isolated_config: Path):
    """clm secret set <claw_name> KEY --yes skips overwrite confirmation."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": "testhost",
            "alias": "testhost",
            "claws": {
                "openclaw": {
                    "name": "test-claw",
                    "status": "installed",
                    "user": "test-user",
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(app, ["secret", "set", "test-claw", "KEY"], env=os.environ)

    # Update with --yes flag (no input needed)
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app, ["secret", "set", "test-claw", "KEY", "--yes"], env=os.environ
        )

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    # Verify value changed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "testhost:openclaw:test-claw"
    assert secrets[instance_key]["KEY"]["value"] == "new-value"


def test_secret_set_empty_value_rejected(isolated_config: Path):
    """clm secret set <claw_name> KEY with empty value shows error."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": "testhost",
            "alias": "testhost",
            "claws": {
                "openclaw": {
                    "name": "test-claw",
                    "status": "installed",
                    "user": "test-user",
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    with patch("clawrium.cli.secret.getpass.getpass", return_value=""):
        result = runner.invoke(app, ["secret", "set", "test-claw", "EMPTY_KEY"], env=os.environ)

    assert result.exit_code == 1
    assert "cannot be empty" in result.output.lower()


def test_secret_list_empty(isolated_config: Path):
    """clm secret list with no secrets shows 'No secrets stored'."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(app, ["secret", "list"], env=os.environ)

    assert result.exit_code == 0
    assert "no secrets" in result.output.lower()


def test_secret_list_shows_keys_not_values(isolated_config: Path):
    """clm secret list shows table with keys and metadata, not values."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create test secrets
    with patch("clawrium.cli.secret.getpass.getpass", return_value="secret-value-1"):
        runner.invoke(
            app,
            ["secret", "set", "KEY1", "--description", "First key"],
            env=os.environ,
        )

    with patch("clawrium.cli.secret.getpass.getpass", return_value="secret-value-2"):
        runner.invoke(
            app,
            ["secret", "set", "KEY2", "--description", "Second key"],
            env=os.environ,
        )

    result = runner.invoke(app, ["secret", "list"], env=os.environ)

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


def test_secret_list_shows_missing_required_secrets(isolated_config: Path):
    """clm secret list shows missing required secrets grouped by claw type."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Don't create any secrets - openclaw requires OPENAI_API_KEY
    result = runner.invoke(app, ["secret", "list"], env=os.environ)

    assert result.exit_code == 0
    assert "missing required secrets" in result.output.lower()
    assert "openclaw" in result.output.lower()
    assert "OPENAI_API_KEY" in result.output


def test_secret_list_no_missing_when_all_set(isolated_config: Path):
    """clm secret list does not show missing section when all required secrets set."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Set all required secrets for openclaw
    with patch("clawrium.cli.secret.getpass.getpass", return_value="sk-test"):
        runner.invoke(app, ["secret", "set", "OPENAI_API_KEY"], env=os.environ)

    result = runner.invoke(app, ["secret", "list"], env=os.environ)

    assert result.exit_code == 0
    # Should show the stored secret
    assert "OPENAI_API_KEY" in result.output
    # Should NOT show missing section
    assert "missing required secrets" not in result.output.lower()


def test_secret_remove_prompts_confirmation(isolated_config: Path):
    """clm secret remove KEY prompts for confirmation."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(app, ["secret", "set", "TO_REMOVE"], env=os.environ)

    # Try to remove - cancel
    result = runner.invoke(
        app, ["secret", "remove", "TO_REMOVE"], input="n\n", env=os.environ
    )

    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()

    # Verify secret still exists (in __global__ namespace)
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    assert "TO_REMOVE" in secrets["__global__"]


def test_secret_remove_confirmed(isolated_config: Path):
    """clm secret remove KEY with confirmation removes secret."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(app, ["secret", "set", "TO_REMOVE"], env=os.environ)

    # Remove with confirmation
    result = runner.invoke(
        app, ["secret", "remove", "TO_REMOVE"], input="y\n", env=os.environ
    )

    assert result.exit_code == 0
    assert "removed" in result.output.lower()

    # Verify secret was removed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    assert "TO_REMOVE" not in secrets


def test_secret_remove_force_skips_confirmation(isolated_config: Path):
    """clm secret remove KEY --force skips confirmation prompt."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="value"):
        runner.invoke(app, ["secret", "set", "TO_REMOVE"], env=os.environ)

    # Remove with --force (no input needed)
    result = runner.invoke(
        app, ["secret", "remove", "TO_REMOVE", "--force"], env=os.environ
    )

    assert result.exit_code == 0
    assert "removed" in result.output.lower()

    # Verify secret was removed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    assert "TO_REMOVE" not in secrets


def test_secret_remove_nonexistent_shows_error(isolated_config: Path):
    """clm secret remove KEY for non-existent key shows error."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(app, ["secret", "remove", "NONEXISTENT"], env=os.environ)

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# Per-claw secret tests (Phase 06 Plan 02)


def test_secret_set_with_claw(isolated_config: Path):
    """clm secret set <claw_name> KEY prompts for value and stores for that claw."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
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
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    with patch("clawrium.cli.secret.getpass.getpass", return_value="my-secret-value"):
        result = runner.invoke(
            app, ["secret", "set", "opc-work", "OPENAI_API_KEY"], env=os.environ
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
            app, ["secret", "set", "nonexistent-claw", "API_KEY"], env=os.environ
        )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()
    assert "nonexistent-claw" in result.output


def test_secret_set_with_claw_update_confirmed(isolated_config: Path):
    """clm secret set <claw_name> KEY with confirmation updates value for that claw."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create a host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
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
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    # Create existing secret
    with patch("clawrium.cli.secret.getpass.getpass", return_value="old-value"):
        runner.invoke(app, ["secret", "set", "opc-work", "API_KEY"], env=os.environ)

    # Update with confirmation
    with patch("clawrium.cli.secret.getpass.getpass", return_value="new-value"):
        result = runner.invoke(
            app, ["secret", "set", "opc-work", "API_KEY"], input="y\n", env=os.environ
        )

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    # Verify value changed
    secrets_file = isolated_config / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    instance_key = "wolf:openclaw:opc-work"
    assert secrets[instance_key]["API_KEY"]["value"] == "new-value"
