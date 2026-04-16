"""Tests for integration CLI commands."""

import json
from unittest.mock import patch
from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.integrations import INTEGRATIONS_FILE


runner = CliRunner()


class TestIntegrationTypes:
    """Tests for 'clm integration types' command."""

    def test_types_lists_all_integrations(self, isolated_config):
        """'clm integration types' lists all supported integration types."""
        result = runner.invoke(app, ["integration", "types"])

        assert result.exit_code == 0
        assert "github" in result.output
        assert "gitlab" in result.output
        assert "jira" in result.output
        assert "confluence" in result.output
        assert "linear" in result.output
        assert "notion" in result.output


class TestIntegrationList:
    """Tests for 'clm integration list' command."""

    def test_list_empty(self, isolated_config):
        """'clm integration list' shows message when no integrations."""
        result = runner.invoke(app, ["integration", "list"])

        assert result.exit_code == 0
        assert "no integrations configured" in result.output.lower()

    def test_list_with_integrations(self, isolated_config):
        """'clm integration list' shows configured integrations."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        integrations = [
            {"name": "work-github", "type": "github", "created_at": "2026-04-15T10:00:00Z"},
            {"name": "company-jira", "type": "jira", "created_at": "2026-04-15T11:00:00Z"},
        ]
        (isolated_config / INTEGRATIONS_FILE).write_text(json.dumps(integrations))

        result = runner.invoke(app, ["integration", "list"])

        assert result.exit_code == 0
        assert "work-github" in result.output
        assert "company-jira" in result.output
        assert "github" in result.output
        assert "jira" in result.output


class TestIntegrationAdd:
    """Tests for 'clm integration add' command."""

    def test_add_requires_type(self, isolated_config):
        """'clm integration add' requires --type option."""
        result = runner.invoke(app, ["integration", "add", "my-github"])

        assert result.exit_code != 0
        assert "type" in result.output.lower() or "missing option" in result.output.lower()

    def test_add_rejects_invalid_type(self, isolated_config):
        """'clm integration add' rejects invalid integration type."""
        result = runner.invoke(
            app,
            ["integration", "add", "my-int", "--type", "invalid-type"],
            input="\n"  # Cancel prompt
        )

        assert result.exit_code == 1
        assert "invalid integration type" in result.output.lower()

    def test_add_rejects_invalid_name(self, isolated_config):
        """'clm integration add' rejects invalid integration name."""
        result = runner.invoke(
            app,
            ["integration", "add", "123invalid", "--type", "github"],
            input="\n"
        )

        assert result.exit_code == 1
        assert "invalid" in result.output.lower() and "name" in result.output.lower()

    def test_add_prompts_for_credentials(self, isolated_config):
        """'clm integration add' prompts for credentials."""
        isolated_config.mkdir(parents=True, exist_ok=True)

        # Provide token value when prompted
        result = runner.invoke(
            app,
            ["integration", "add", "my-github", "--type", "github"],
            input="ghp_test123\n"
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

        # Verify integration was saved
        integrations_file = isolated_config / INTEGRATIONS_FILE
        assert integrations_file.exists()
        integrations = json.loads(integrations_file.read_text())
        assert len(integrations) == 1
        assert integrations[0]["name"] == "my-github"
        assert integrations[0]["type"] == "github"

    def test_add_rejects_duplicate(self, isolated_config):
        """'clm integration add' rejects duplicate name."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        result = runner.invoke(
            app,
            ["integration", "add", "my-github", "--type", "github"],
            input="ghp_test\n"
        )

        assert result.exit_code == 1
        assert "already exists" in result.output.lower()


class TestIntegrationShow:
    """Tests for 'clm integration show' command."""

    def test_show_not_found(self, isolated_config):
        """'clm integration show' errors when integration not found."""
        result = runner.invoke(app, ["integration", "show", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_show_existing_integration(self, isolated_config):
        """'clm integration show' displays integration details."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{
                "name": "work-github",
                "type": "github",
                "created_at": "2026-04-15T10:00:00Z",
                "updated_at": "2026-04-15T10:00:00Z",
            }])
        )

        result = runner.invoke(app, ["integration", "show", "work-github"])

        assert result.exit_code == 0
        assert "work-github" in result.output
        assert "github" in result.output


class TestIntegrationRemove:
    """Tests for 'clm integration remove' command."""

    def test_remove_not_found(self, isolated_config):
        """'clm integration remove' errors when integration not found."""
        result = runner.invoke(app, ["integration", "remove", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_remove_prompts_for_confirmation(self, isolated_config):
        """'clm integration remove' prompts for confirmation."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        # Decline confirmation
        result = runner.invoke(
            app,
            ["integration", "remove", "my-github"],
            input="n\n"
        )

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

        # Verify not removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 1

    def test_remove_with_force(self, isolated_config):
        """'clm integration remove --force' skips confirmation."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.remove_integration_credentials",
            return_value=True
        ), patch(
            "clawrium.core.integrations.find_agents_using_integration",
            return_value=[]
        ):
            result = runner.invoke(
                app,
                ["integration", "remove", "my-github", "--force"]
            )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

        # Verify removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 0

    def test_remove_with_confirmation(self, isolated_config):
        """'clm integration remove' removes when confirmed."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.remove_integration_credentials",
            return_value=True
        ), patch(
            "clawrium.core.integrations.find_agents_using_integration",
            return_value=[]
        ):
            result = runner.invoke(
                app,
                ["integration", "remove", "my-github"],
                input="y\n"
            )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

    def test_remove_blocked_when_in_use(self, isolated_config):
        """'clm integration remove' fails when integration in use by agents."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.find_agents_using_integration",
            return_value=[("host1", "agent1")]
        ):
            result = runner.invoke(
                app,
                ["integration", "remove", "my-github"],
                input="y\n"
            )

        assert result.exit_code == 1
        assert "assigned to agents" in result.output.lower()
        assert "host1:agent1" in result.output

        # Verify NOT removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 1

    def test_remove_force_overrides_in_use_check(self, isolated_config):
        """'clm integration remove --force' removes even when in use."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.remove_integration_credentials",
            return_value=True
        ), patch(
            "clawrium.core.integrations.find_agents_using_integration",
            return_value=[("host1", "agent1")]
        ):
            result = runner.invoke(
                app,
                ["integration", "remove", "my-github", "--force"]
            )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

        # Verify removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 0


class TestIntegrationCredentials:
    """Tests for 'clm integration credentials' command."""

    def test_credentials_not_found(self, isolated_config):
        """'clm integration credentials' errors when integration not found."""
        result = runner.invoke(app, ["integration", "credentials", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_credentials_shows_status(self, isolated_config):
        """'clm integration credentials' shows credential status."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "work-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.get_integration_credentials",
            return_value={"GITHUB_TOKEN": "ghp_test123"}
        ):
            result = runner.invoke(app, ["integration", "credentials", "work-github"])

        assert result.exit_code == 0
        assert "GITHUB_TOKEN" in result.output
        # Token should be masked
        assert "ghp_test123" not in result.output
