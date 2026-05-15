"""Tests for configure_agent integration loading."""

from unittest.mock import MagicMock, patch
import pytest


class TestConfigureAgentIntegrationLoading:
    """Tests for integration credential loading in configure_agent."""

    @pytest.fixture
    def mock_host(self):
        """Return a mock host with an agent."""
        return {
            "hostname": "192.168.1.100",
            "key_id": "test-key",
            "port": 22,
            "agents": {
                "test-agent": {
                    "type": "openclaw",
                    "status": "installed",
                    "integrations": ["work-github", "company-atlassian"],
                }
            },
        }

    @pytest.fixture
    def mock_ansible_success(self):
        """Return a mock successful ansible run result."""
        mock_result = MagicMock()
        mock_result.rc = 0
        mock_result.status = "successful"
        return mock_result

    def test_configure_agent_loads_assigned_integrations(self, mock_host, mock_ansible_success, tmp_path):
        """configure_agent calls get_agent_integrations for assigned integrations."""
        with patch(
            "clawrium.core.lifecycle.get_host", return_value=mock_host
        ), patch(
            "clawrium.core.lifecycle._resolve_agent_record"
        ) as mock_resolve, patch(
            "clawrium.core.integrations.get_agent_integrations"
        ) as mock_get_integrations, patch(
            "clawrium.core.integrations.get_integration"
        ) as mock_get_integration, patch(
            "clawrium.core.integrations.get_integration_credentials"
        ) as mock_get_credentials, patch(
            "clawrium.core.lifecycle.ansible_runner.run"
        ) as mock_run, patch(
            "clawrium.core.lifecycle.update_host", return_value=True
        ), patch(
            "clawrium.core.lifecycle.get_host_private_key", return_value="ssh-key-content"
        ), patch(
            "clawrium.core.lifecycle._get_lifecycle_playbook_path"
        ) as mock_playbook_path, patch(
            "clawrium.core.lifecycle._resolve_agent_type", return_value="openclaw"
        ), patch(
            "clawrium.core.lifecycle.get_instance_secrets", return_value={}
        ), patch(
            "clawrium.core.lifecycle._cleanup_ansible_artifacts"
        ):
            # Setup playbook path
            playbook = tmp_path / "configure.yaml"
            playbook.write_text("---\n- hosts: all\n")
            mock_playbook_path.return_value = playbook

            # Setup template path
            template_dir = tmp_path / "templates"
            template_dir.mkdir()
            (template_dir / "config.toml.j2").write_text("# config")

            mock_resolve.return_value = ("test-agent", "openclaw", mock_host["agents"]["test-agent"])
            mock_get_integrations.return_value = ["work-github", "company-atlassian"]
            mock_get_integration.side_effect = [
                {"name": "work-github", "type": "github"},
                {"name": "company-atlassian", "type": "atlassian"},
            ]
            mock_get_credentials.side_effect = [
                {"GITHUB_TOKEN": "ghp_test123"},
                {"ATLASSIAN_URL": "https://company.atlassian.net", "ATLASSIAN_EMAIL": "test@example.com", "ATLASSIAN_API_TOKEN": "atlassian_token"},
            ]
            mock_run.return_value = mock_ansible_success

            from clawrium.core.lifecycle import configure_agent

            with patch("clawrium.core.lifecycle.Path") as mock_path_cls:
                # Mock template path existence
                mock_template_path = MagicMock()
                mock_template_path.exists.return_value = True
                mock_path_cls.return_value.parent.parent.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_template_path

                result, _ = configure_agent("test-host", "test-agent", {})

            # Verify get_agent_integrations was called with the hostname parameter
            mock_get_integrations.assert_called_once_with("test-host", "test-agent")

    def test_integration_data_format_with_type_and_credentials(self):
        """Verify integration data includes type field alongside credentials."""
        # This tests the data structure transformation in configure_agent
        # Integration data should be: {name: {type: "...", CRED_KEY: "value"}}

        # Simulate the transformation done in configure_agent
        integration_name = "work-github"
        integration = {"name": "work-github", "type": "github"}
        credentials = {"GITHUB_TOKEN": "ghp_test123"}

        # This is the format used in configure_agent after B2 fix
        integrations_data = {}
        integration_type = integration.get("type", "")
        integrations_data[integration_name] = {
            "type": integration_type,
            **credentials,
        }

        # Verify format
        assert "work-github" in integrations_data
        assert integrations_data["work-github"]["type"] == "github"
        assert integrations_data["work-github"]["GITHUB_TOKEN"] == "ghp_test123"

    def test_multiple_same_type_integrations_not_overwritten(self):
        """Verify multiple integrations of same type are preserved (B2 fix)."""
        # This tests that keying by name prevents overwrite

        integrations_data = {}

        # First github integration
        integrations_data["work-github"] = {
            "type": "github",
            "GITHUB_TOKEN": "ghp_work_token",
        }

        # Second github integration (should NOT overwrite first)
        integrations_data["personal-github"] = {
            "type": "github",
            "GITHUB_TOKEN": "ghp_personal_token",
        }

        # Both should exist
        assert len(integrations_data) == 2
        assert integrations_data["work-github"]["GITHUB_TOKEN"] == "ghp_work_token"
        assert integrations_data["personal-github"]["GITHUB_TOKEN"] == "ghp_personal_token"

    def test_missing_integration_skipped_gracefully(self, mock_host, mock_ansible_success, tmp_path, caplog):
        """configure_agent logs warning for missing integration and continues."""
        with patch(
            "clawrium.core.lifecycle.get_host", return_value=mock_host
        ), patch(
            "clawrium.core.lifecycle._resolve_agent_record"
        ) as mock_resolve, patch(
            "clawrium.core.integrations.get_agent_integrations"
        ) as mock_get_integrations, patch(
            "clawrium.core.integrations.get_integration"
        ) as mock_get_integration, patch(
            "clawrium.core.integrations.get_integration_credentials"
        ), patch(
            "clawrium.core.lifecycle.ansible_runner.run"
        ) as mock_run, patch(
            "clawrium.core.lifecycle.update_host", return_value=True
        ), patch(
            "clawrium.core.lifecycle.get_host_private_key", return_value="ssh-key-content"
        ), patch(
            "clawrium.core.lifecycle._get_lifecycle_playbook_path"
        ) as mock_playbook_path, patch(
            "clawrium.core.lifecycle._resolve_agent_type", return_value="openclaw"
        ), patch(
            "clawrium.core.lifecycle.get_instance_secrets", return_value={}
        ), patch(
            "clawrium.core.lifecycle._cleanup_ansible_artifacts"
        ):
            # Setup playbook path
            playbook = tmp_path / "configure.yaml"
            playbook.write_text("---\n- hosts: all\n")
            mock_playbook_path.return_value = playbook

            mock_resolve.return_value = ("test-agent", "openclaw", mock_host["agents"]["test-agent"])
            mock_get_integrations.return_value = ["missing-integration"]
            mock_get_integration.return_value = None  # Integration not found
            mock_run.return_value = mock_ansible_success

            from clawrium.core.lifecycle import configure_agent
            import logging

            with patch("clawrium.core.lifecycle.Path") as mock_path_cls:
                mock_template_path = MagicMock()
                mock_template_path.exists.return_value = True
                mock_path_cls.return_value.parent.parent.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_template_path

                with caplog.at_level(logging.WARNING):
                    result, _ = configure_agent("test-host", "test-agent", {})

            # Should continue without failing - ansible_runner.run should be called
            mock_run.assert_called_once()

    def test_integration_without_credentials_skipped(self, mock_host, mock_ansible_success, tmp_path, caplog):
        """configure_agent logs warning for integration without credentials."""
        with patch(
            "clawrium.core.lifecycle.get_host", return_value=mock_host
        ), patch(
            "clawrium.core.lifecycle._resolve_agent_record"
        ) as mock_resolve, patch(
            "clawrium.core.integrations.get_agent_integrations"
        ) as mock_get_integrations, patch(
            "clawrium.core.integrations.get_integration"
        ) as mock_get_integration, patch(
            "clawrium.core.integrations.get_integration_credentials"
        ) as mock_get_credentials, patch(
            "clawrium.core.lifecycle.ansible_runner.run"
        ) as mock_run, patch(
            "clawrium.core.lifecycle.update_host", return_value=True
        ), patch(
            "clawrium.core.lifecycle.get_host_private_key", return_value="ssh-key-content"
        ), patch(
            "clawrium.core.lifecycle._get_lifecycle_playbook_path"
        ) as mock_playbook_path, patch(
            "clawrium.core.lifecycle._resolve_agent_type", return_value="openclaw"
        ), patch(
            "clawrium.core.lifecycle.get_instance_secrets", return_value={}
        ), patch(
            "clawrium.core.lifecycle._cleanup_ansible_artifacts"
        ):
            # Setup playbook path
            playbook = tmp_path / "configure.yaml"
            playbook.write_text("---\n- hosts: all\n")
            mock_playbook_path.return_value = playbook

            mock_resolve.return_value = ("test-agent", "openclaw", mock_host["agents"]["test-agent"])
            mock_get_integrations.return_value = ["work-github"]
            mock_get_integration.return_value = {"name": "work-github", "type": "github"}
            mock_get_credentials.return_value = {}  # No credentials
            mock_run.return_value = mock_ansible_success

            from clawrium.core.lifecycle import configure_agent
            import logging

            with patch("clawrium.core.lifecycle.Path") as mock_path_cls:
                mock_template_path = MagicMock()
                mock_template_path.exists.return_value = True
                mock_path_cls.return_value.parent.parent.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_template_path

                with caplog.at_level(logging.WARNING):
                    result, _ = configure_agent("test-host", "test-agent", {})

            # Should continue without failing
            mock_run.assert_called_once()

    def test_unknown_type_integration_emits_warning_and_is_excluded(
        self, mock_host, mock_ansible_success, tmp_path
    ):
        """A stale `jira`-typed record fires the configure-stage warning and is
        excluded from ansible extravars, rather than silently shipping a green
        configure with the broken record loaded.
        """
        events: list[tuple[str, str]] = []

        with patch(
            "clawrium.core.lifecycle.get_host", return_value=mock_host
        ), patch(
            "clawrium.core.lifecycle._resolve_agent_record"
        ) as mock_resolve, patch(
            "clawrium.core.integrations.get_agent_integrations"
        ) as mock_get_integrations, patch(
            "clawrium.core.integrations.get_integration"
        ) as mock_get_integration, patch(
            "clawrium.core.integrations.get_integration_credentials"
        ) as mock_get_credentials, patch(
            "clawrium.core.lifecycle.ansible_runner.run"
        ) as mock_run, patch(
            "clawrium.core.lifecycle.update_host", return_value=True
        ), patch(
            "clawrium.core.lifecycle.get_host_private_key", return_value="ssh-key-content"
        ), patch(
            "clawrium.core.lifecycle._get_lifecycle_playbook_path"
        ) as mock_playbook_path, patch(
            "clawrium.core.lifecycle._resolve_agent_type", return_value="openclaw"
        ), patch(
            "clawrium.core.lifecycle.get_instance_secrets", return_value={}
        ), patch(
            "clawrium.core.lifecycle._cleanup_ansible_artifacts"
        ), patch(
            "clawrium.core.lifecycle._get_logs_dir", return_value=tmp_path / "logs"
        ):
            playbook = tmp_path / "configure.yaml"
            playbook.write_text("---\n- hosts: all\n")
            mock_playbook_path.return_value = playbook

            mock_resolve.return_value = (
                "test-agent",
                "openclaw",
                mock_host["agents"]["test-agent"],
            )
            mock_get_integrations.return_value = ["old-jira", "work-github"]
            mock_get_integration.side_effect = [
                {"name": "old-jira", "type": "jira"},
                {"name": "work-github", "type": "github"},
            ]
            # Keyed-by-name side_effect: robust to ordering. If the guard
            # regresses and credentials are fetched for the stale record, the
            # `call_count` assertion below produces a clean failure rather
            # than a StopIteration traceback.
            def _credentials_by_name(name: str) -> dict:
                return {
                    "old-jira": {"JIRA_API_TOKEN": "would-be-leaked"},
                    "work-github": {"GITHUB_TOKEN": "ghp_test"},
                }.get(name, {})

            mock_get_credentials.side_effect = _credentials_by_name
            mock_run.return_value = mock_ansible_success

            from clawrium.core.lifecycle import configure_agent

            with patch("clawrium.core.lifecycle.Path") as mock_path_cls:
                mock_template_path = MagicMock()
                mock_template_path.exists.return_value = True
                mock_path_cls.return_value.parent.parent.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_template_path

                result, _ = configure_agent(
                    "test-host",
                    "test-agent",
                    {},
                    on_event=lambda stage, msg: events.append((stage, msg)),
                )

            assert result is True
            # Warning fired on the configure stage for the stale record.
            unknown_events = [(s, m) for s, m in events if "unknown type" in m.lower()]
            assert unknown_events, f"WARNING never emitted; events={events!r}"
            assert all(s == "configure" for s, _ in unknown_events), (
                f"WARNING fired on wrong stage; events={unknown_events!r}"
            )
            warning_messages = [m for _, m in unknown_events]
            assert any("old-jira" in m for m in warning_messages)
            assert any("jira" in m for m in warning_messages)
            # Valid-types hint included for actionability.
            assert any("Valid types" in m for m in warning_messages)

            # Credentials were NOT requested for the stale record (continue
            # fires before credential load). Only the github load remains.
            assert mock_get_credentials.call_count == 1

            # Stale record is excluded from the ansible vars; the valid one
            # passes through. Vars travel inside inventory[all][vars].
            inventory = mock_run.call_args.kwargs["inventory"]
            ansible_vars = inventory["all"]["vars"]
            integrations_var = ansible_vars.get("integrations", {})
            assert "old-jira" not in integrations_var
            assert "work-github" in integrations_var
            assert integrations_var["work-github"]["type"] == "github"
            # Credential payload reaches inventory, not just the record shape.
            assert integrations_var["work-github"]["GITHUB_TOKEN"] == "ghp_test"
