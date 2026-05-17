"""Tests for integration storage module."""

import json
import pytest
from unittest.mock import patch

from clawrium.core.integrations import (
    INTEGRATIONS_FILE,
    INTEGRATION_TYPES,
    load_integrations,
    add_integration,
    get_integration,
    remove_integration,
    validate_integration_name,
    validate_integration_type,
    get_credentials_for_type,
    get_integration_instance_key,
    set_integration_credential,
    get_integration_credentials,
    remove_integration_credentials,
    get_agent_integrations,
    set_agent_integrations,
    add_agent_integration,
    remove_agent_integration,
    find_agents_using_integration,
    IntegrationsFileCorruptedError,
    DuplicateIntegrationError,
    InvalidIntegrationTypeError,
    InvalidIntegrationNameError,
    IntegrationInUseError,
)


class TestValidation:
    """Tests for validation functions."""

    def test_validate_integration_name_valid(self):
        """validate_integration_name accepts valid names."""
        valid_names = [
            "mygithub",
            "my-github",
            "my_github",
            "MyGitHub",
            "a",
            "A1",
            "integration123",
            "a" * 64,  # Max length
        ]
        for name in valid_names:
            try:
                validate_integration_name(name)  # Should not raise
            except InvalidIntegrationNameError:
                pytest.fail(
                    f"'{name}' should be valid but raised InvalidIntegrationNameError"
                )

    def test_validate_integration_name_invalid(self):
        """validate_integration_name rejects invalid names."""
        invalid_names = [
            "",  # Empty
            "1integration",  # Starts with number
            "-integration",  # Starts with hyphen
            "_integration",  # Starts with underscore
            "my integration",  # Contains space
            "my.integration",  # Contains dot
            "my/integration",  # Contains slash
            "../path",  # Path traversal attempt
            "a" * 65,  # Too long
        ]
        for name in invalid_names:
            with pytest.raises(InvalidIntegrationNameError):
                validate_integration_name(name)

    def test_validate_integration_name_none(self):
        """validate_integration_name raises for None input."""
        with pytest.raises(InvalidIntegrationNameError) as exc_info:
            validate_integration_name(None)
        assert "must be a string" in str(exc_info.value).lower()

    def test_validate_integration_name_non_string(self):
        """validate_integration_name raises for non-string input."""
        with pytest.raises(InvalidIntegrationNameError):
            validate_integration_name(123)

    def test_validate_integration_type_valid(self):
        """validate_integration_type accepts all valid types."""
        for integration_type in INTEGRATION_TYPES.keys():
            validate_integration_type(integration_type)  # Should not raise

    def test_validate_integration_type_invalid(self):
        """validate_integration_type rejects unknown types."""
        with pytest.raises(InvalidIntegrationTypeError) as exc_info:
            validate_integration_type("unknown-integration")
        assert "invalid integration type" in str(exc_info.value).lower()

    def test_get_credentials_for_type_returns_credentials(self):
        """get_credentials_for_type returns credential list for valid types."""
        for integration_type in INTEGRATION_TYPES.keys():
            credentials = get_credentials_for_type(integration_type)
            assert isinstance(credentials, list)
            # Each credential should have key, description, required
            for cred in credentials:
                assert "key" in cred
                assert "description" in cred
                assert "required" in cred

    def test_get_credentials_for_type_invalid(self):
        """get_credentials_for_type raises for invalid type."""
        with pytest.raises(InvalidIntegrationTypeError):
            get_credentials_for_type("invalid-type")


class TestIntegrationTypes:
    """Tests for INTEGRATION_TYPES registry."""

    def test_integration_types_has_expected_types(self):
        """INTEGRATION_TYPES contains expected integration types."""
        expected_types = {"github", "gitlab", "atlassian", "linear", "notion"}
        assert set(INTEGRATION_TYPES.keys()) == expected_types

    def test_each_type_has_description_and_credentials(self):
        """Each integration type has description and credentials."""
        for name, config in INTEGRATION_TYPES.items():
            assert "description" in config, f"{name} missing description"
            assert "credentials" in config, f"{name} missing credentials"
            assert isinstance(config["credentials"], list)

    def test_github_has_token_credential(self):
        """GitHub integration requires GITHUB_TOKEN."""
        github = INTEGRATION_TYPES["github"]
        keys = [c["key"] for c in github["credentials"]]
        assert "GITHUB_TOKEN" in keys

    def test_atlassian_has_required_credentials(self):
        """Atlassian integration requires URL, email, and token."""
        atlassian = INTEGRATION_TYPES["atlassian"]
        keys = [c["key"] for c in atlassian["credentials"]]
        assert "ATLASSIAN_URL" in keys
        assert "ATLASSIAN_EMAIL" in keys
        assert "ATLASSIAN_API_TOKEN" in keys


class TestIntegrationInstanceKey:
    """Tests for get_integration_instance_key."""

    def test_returns_prefixed_key(self):
        """Instance key has integration: prefix."""
        key = get_integration_instance_key("my-github")
        assert key == "integration:my-github"

    def test_different_names_different_keys(self):
        """Different integration names produce different keys."""
        key1 = get_integration_instance_key("github-work")
        key2 = get_integration_instance_key("github-personal")
        assert key1 != key2


class TestLoadIntegrations:
    """Tests for load_integrations function."""

    def test_returns_empty_list_when_file_missing(self, tmp_path):
        """Returns empty list when integrations.json doesn't exist."""
        with patch("clawrium.core.integrations.get_config_dir", return_value=tmp_path):
            result = load_integrations()
            assert result == []

    def test_loads_valid_integrations(self, tmp_path):
        """Loads integrations from valid JSON file."""
        integrations = [
            {"name": "work-github", "type": "github"},
            {"name": "company-atlassian", "type": "atlassian"},
        ]
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps(integrations))

        with patch("clawrium.core.integrations.get_config_dir", return_value=tmp_path):
            result = load_integrations()
            assert len(result) == 2
            assert result[0]["name"] == "work-github"
            assert result[1]["type"] == "atlassian"

    def test_raises_on_invalid_json(self, tmp_path):
        """Raises IntegrationsFileCorruptedError on invalid JSON."""
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text("not valid json")

        with patch("clawrium.core.integrations.get_config_dir", return_value=tmp_path):
            with pytest.raises(IntegrationsFileCorruptedError) as exc_info:
                load_integrations()
            assert "corrupted" in str(exc_info.value).lower()

    def test_raises_when_not_a_list(self, tmp_path):
        """Raises when JSON is not a list."""
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text('{"not": "a list"}')

        with patch("clawrium.core.integrations.get_config_dir", return_value=tmp_path):
            with pytest.raises(IntegrationsFileCorruptedError) as exc_info:
                load_integrations()
            assert "not a list" in str(exc_info.value).lower()


class TestAddIntegration:
    """Tests for add_integration function."""

    def test_adds_new_integration(self, tmp_path):
        """Adds new integration to empty file."""
        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            add_integration({"name": "my-github", "type": "github"})
            integrations = load_integrations()
            assert len(integrations) == 1
            assert integrations[0]["name"] == "my-github"

    def test_raises_on_duplicate_name(self, tmp_path):
        """Raises DuplicateIntegrationError when name exists."""
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps([{"name": "my-github", "type": "github"}]))

        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            with pytest.raises(DuplicateIntegrationError) as exc_info:
                add_integration({"name": "my-github", "type": "github"})
            assert "already exists" in str(exc_info.value)

    def test_raises_on_invalid_name(self, tmp_path):
        """Raises InvalidIntegrationNameError for invalid name."""
        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            with pytest.raises(InvalidIntegrationNameError):
                add_integration({"name": "123invalid", "type": "github"})

    def test_raises_on_invalid_type(self, tmp_path):
        """Raises InvalidIntegrationTypeError for invalid type."""
        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            with pytest.raises(InvalidIntegrationTypeError):
                add_integration({"name": "myint", "type": "invalid-type"})

    def test_stamps_created_at_and_updated_at(self, tmp_path):
        """add_integration stamps timestamps when caller omits them."""
        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            add_integration({"name": "myint", "type": "github"})
            saved = load_integrations()
            assert len(saved) == 1
            rec = saved[0]
            assert isinstance(rec.get("created_at"), str)
            assert isinstance(rec.get("updated_at"), str)
            assert rec["created_at"] == rec["updated_at"]
            # ISO-8601 UTC: must end with +00:00 and contain a T separator
            assert "T" in rec["created_at"]
            assert rec["created_at"].endswith("+00:00")

    def test_preserves_caller_supplied_timestamps(self, tmp_path):
        """setdefault semantics: caller-supplied timestamps are not overwritten."""
        ts = "2025-01-01T00:00:00+00:00"
        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            add_integration(
                {
                    "name": "myint",
                    "type": "github",
                    "created_at": ts,
                    "updated_at": ts,
                }
            )
            saved = load_integrations()
            assert saved[0]["created_at"] == ts
            assert saved[0]["updated_at"] == ts


class TestGetIntegration:
    """Tests for get_integration function."""

    def test_returns_integration_when_found(self, tmp_path):
        """Returns integration dict when name matches."""
        integrations = [
            {"name": "work-github", "type": "github"},
            {"name": "company-atlassian", "type": "atlassian"},
        ]
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps(integrations))

        with patch("clawrium.core.integrations.get_config_dir", return_value=tmp_path):
            result = get_integration("company-atlassian")
            assert result is not None
            assert result["name"] == "company-atlassian"
            assert result["type"] == "atlassian"

    def test_returns_none_when_not_found(self, tmp_path):
        """Returns None when integration name not found."""
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps([{"name": "other", "type": "github"}]))

        with patch("clawrium.core.integrations.get_config_dir", return_value=tmp_path):
            result = get_integration("nonexistent")
            assert result is None


class TestRemoveIntegration:
    """Tests for remove_integration function."""

    def test_removes_existing_integration(self, tmp_path):
        """Removes integration and returns True."""
        integrations = [
            {"name": "work-github", "type": "github"},
            {"name": "company-atlassian", "type": "atlassian"},
        ]
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps(integrations))

        # Mock remove_integration_credentials
        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.init_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.remove_integration_credentials", return_value=True
        ):
            result = remove_integration("work-github")
            assert result is True
            remaining = load_integrations()
            assert len(remaining) == 1
            assert remaining[0]["name"] == "company-atlassian"

    def test_returns_false_when_not_found(self, tmp_path):
        """Returns False when integration not found."""
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps([{"name": "other", "type": "github"}]))

        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch("clawrium.core.integrations.init_config_dir", return_value=tmp_path):
            result = remove_integration("nonexistent")
            assert result is False

    def test_removes_credentials_before_json_record(self, tmp_path):
        """Regression guard for W2: credential cleanup must run BEFORE the
        JSON record is rewritten. At the moment ``remove_integration_credentials``
        is invoked, the integrations.json file still contains the target
        record — so a crash between the two steps leaves the integration
        visible (recoverable) rather than orphaning secrets.
        """
        integrations = [
            {"name": "work-github", "type": "github"},
            {"name": "other", "type": "atlassian"},
        ]
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps(integrations))

        observed: dict[str, bool] = {}

        def observing_remove(name: str) -> bool:
            # Read the on-disk file while inside the cleanup hook — the
            # JSON record must still be present at this exact moment.
            current = json.loads(integrations_file.read_text())
            observed["record_present_during_cred_cleanup"] = any(
                rec.get("name") == name for rec in current
            )
            return True

        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.init_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.remove_integration_credentials",
            side_effect=observing_remove,
        ):
            result = remove_integration("work-github")
            assert result is True

        assert observed.get("record_present_during_cred_cleanup") is True, (
            "remove_integration must call remove_integration_credentials "
            "BEFORE saving the new integrations.json"
        )

        # And the final on-disk state should reflect the removal.
        final = json.loads(integrations_file.read_text())
        assert [r["name"] for r in final] == ["other"]


class TestCredentialStorage:
    """Tests for credential storage functions."""

    def test_set_and_get_integration_credential(self):
        """Credential can be stored and retrieved."""
        with patch(
            "clawrium.core.secrets.set_instance_secret"
        ) as mock_set, patch(
            "clawrium.core.secrets.get_instance_secrets"
        ) as mock_get:
            mock_set.return_value = True
            mock_get.return_value = {
                "GITHUB_TOKEN": {"value": "ghp_test123"}
            }

            # Set credential
            result = set_integration_credential(
                "my-github", "GITHUB_TOKEN", "ghp_test123", "My token"
            )
            assert result is True
            mock_set.assert_called_once()

            # Get credentials
            creds = get_integration_credentials("my-github")
            assert creds["GITHUB_TOKEN"] == "ghp_test123"

    def test_remove_integration_credentials(self):
        """Credentials can be removed."""
        with patch(
            "clawrium.core.secrets.remove_instance_secrets"
        ) as mock_remove:
            mock_remove.return_value = True
            result = remove_integration_credentials("my-github")
            assert result is True
            mock_remove.assert_called_once_with("integration:my-github")

    def test_get_integration_credentials_skips_malformed_entry(self):
        """Entries missing a 'value' key are filtered, not crashed on.

        Regression guard for B1 — a malformed SecretEntry (manual edit,
        future writer bug) must not raise KeyError; valid entries should
        still come through unchanged.
        """
        with patch(
            "clawrium.core.secrets.get_instance_secrets"
        ) as mock_get:
            mock_get.return_value = {
                "GOOD_KEY": {"value": "abc"},
                "MISSING_VALUE_KEY": {"description": "no value"},
                "NON_DICT_KEY": "scalar",
            }
            creds = get_integration_credentials("my-github")
            assert creds == {"GOOD_KEY": "abc"}


class TestAgentIntegrations:
    """Tests for agent integration assignment functions."""

    def test_get_agent_integrations_returns_empty_when_not_assigned(self):
        """Returns empty list when no integrations assigned."""
        with patch("clawrium.core.hosts.get_host") as mock_get_host:
            mock_get_host.return_value = {
                "hostname": "testhost",
                "agents": {
                    "test-agent": {
                        "type": "openclaw",
                        "config": {}
                    }
                }
            }
            result = get_agent_integrations("testhost", "test-agent")
            assert result == []

    def test_get_agent_integrations_returns_list(self):
        """Returns list of assigned integration names from dedicated field."""
        with patch("clawrium.core.hosts.get_host") as mock_get_host:
            mock_get_host.return_value = {
                "hostname": "testhost",
                "agents": {
                    "test-agent": {
                        "type": "openclaw",
                        "integrations": ["work-github", "company-jira"],
                        "config": {}
                    }
                }
            }
            result = get_agent_integrations("testhost", "test-agent")
            assert result == ["work-github", "company-jira"]

    def test_get_agent_integrations_returns_empty_for_unknown_host(self):
        """Returns empty list for unknown host."""
        with patch("clawrium.core.hosts.get_host") as mock_get_host:
            mock_get_host.return_value = None
            result = get_agent_integrations("unknown", "agent")
            assert result == []

    def test_set_agent_integrations_updates_dedicated_field(self):
        """set_agent_integrations updates dedicated integrations field."""
        host_data = {
            "hostname": "testhost",
            "agents": {"agent": {"type": "openclaw"}}
        }

        def capture_and_run_updater(hostname, updater):
            # Simulate what update_host does: call the updater with host data
            updater(host_data)
            return True

        with patch("clawrium.core.hosts.get_host") as mock_get_host, \
             patch("clawrium.core.hosts.update_host", side_effect=capture_and_run_updater):
            mock_get_host.return_value = host_data

            result = set_agent_integrations("testhost", "agent", ["github"])
            assert result is True

            # Verify updater set dedicated 'integrations' field
            assert host_data["agents"]["agent"]["integrations"] == ["github"]
            assert "integrations" not in host_data["agents"]["agent"].get("config", {})

    def test_add_agent_integration_adds_to_dedicated_field(self):
        """add_agent_integration adds to dedicated integrations field."""
        captured_updater = None
        host_data = {
            "hostname": "testhost",
            "agents": {
                "agent": {
                    "type": "openclaw",
                    "integrations": ["existing"]
                }
            }
        }

        def capture_and_run_updater(hostname, updater):
            nonlocal captured_updater
            captured_updater = updater
            # Simulate what update_host does: call the updater with host data
            updater(host_data)
            return True

        with patch("clawrium.core.hosts.get_host") as mock_get_host, \
             patch("clawrium.core.hosts.update_host", side_effect=capture_and_run_updater):
            mock_get_host.return_value = host_data

            result = add_agent_integration("testhost", "agent", "new-integration")
            assert result is True

            # Verify updater added to dedicated field
            assert "new-integration" in host_data["agents"]["agent"]["integrations"]
            assert "existing" in host_data["agents"]["agent"]["integrations"]

    def test_add_agent_integration_returns_false_for_duplicate(self):
        """add_agent_integration returns False when already assigned."""
        with patch("clawrium.core.hosts.get_host") as mock_get_host, \
             patch("clawrium.core.hosts.update_host") as mock_update:
            mock_get_host.return_value = {
                "hostname": "testhost",
                "agents": {
                    "agent": {
                        "type": "openclaw",
                        "integrations": ["existing"]
                    }
                }
            }
            mock_update.return_value = True
            result = add_agent_integration("testhost", "agent", "existing")
            assert result is False

    def test_remove_agent_integration_removes_from_dedicated_field(self):
        """remove_agent_integration removes from dedicated field."""
        host_data = {
            "hostname": "testhost",
            "agents": {
                "agent": {
                    "type": "openclaw",
                    "integrations": ["integration1", "integration2"]
                }
            }
        }

        def capture_and_run_updater(hostname, updater):
            # Simulate what update_host does: call the updater with host data
            updater(host_data)
            return True

        with patch("clawrium.core.hosts.get_host") as mock_get_host, \
             patch("clawrium.core.hosts.update_host", side_effect=capture_and_run_updater):
            mock_get_host.return_value = host_data

            result = remove_agent_integration("testhost", "agent", "integration1")
            assert result is True

            # Verify updater removed from dedicated field
            assert host_data["agents"]["agent"]["integrations"] == ["integration2"]

    def test_remove_agent_integration_returns_false_when_not_found(self):
        """remove_agent_integration returns False when not assigned."""
        with patch("clawrium.core.hosts.get_host") as mock_get_host, \
             patch("clawrium.core.hosts.update_host") as mock_update:
            mock_get_host.return_value = {
                "hostname": "testhost",
                "agents": {
                    "agent": {
                        "type": "openclaw",
                        "integrations": ["other"]
                    }
                }
            }
            mock_update.return_value = True
            result = remove_agent_integration("testhost", "agent", "nonexistent")
            assert result is False


class TestFindAgentsUsingIntegration:
    """Tests for find_agents_using_integration function."""

    def test_returns_empty_when_no_usage(self):
        """Returns empty list when integration not used."""
        with patch("clawrium.core.hosts.load_hosts") as mock_load:
            mock_load.return_value = [
                {
                    "hostname": "host1",
                    "agents": {
                        "agent1": {"type": "openclaw", "integrations": ["other"]}
                    }
                }
            ]
            result = find_agents_using_integration("unused-integration")
            assert result == []

    def test_finds_agents_using_integration(self):
        """Returns list of (host, agent) tuples using integration."""
        with patch("clawrium.core.hosts.load_hosts") as mock_load:
            mock_load.return_value = [
                {
                    "hostname": "host1",
                    "agents": {
                        "agent1": {"type": "openclaw", "integrations": ["my-github"]},
                        "agent2": {"type": "zeroclaw", "integrations": ["other"]}
                    }
                },
                {
                    "hostname": "host2",
                    "agents": {
                        "agent3": {"type": "openclaw", "integrations": ["my-github", "jira"]}
                    }
                }
            ]
            result = find_agents_using_integration("my-github")
            assert len(result) == 2
            assert ("host1", "agent1") in result
            assert ("host2", "agent3") in result

    def test_handles_missing_integrations_field(self):
        """Handles agents without integrations field gracefully."""
        with patch("clawrium.core.hosts.load_hosts") as mock_load:
            mock_load.return_value = [
                {
                    "hostname": "host1",
                    "agents": {
                        "agent1": {"type": "openclaw"}  # No integrations field
                    }
                }
            ]
            result = find_agents_using_integration("my-github")
            assert result == []


class TestRemoveIntegrationWithUsageCheck:
    """Tests for remove_integration with usage checking."""

    def test_raises_when_in_use(self, tmp_path):
        """Raises IntegrationInUseError when integration assigned to agents."""
        integrations = [{"name": "my-github", "type": "github"}]
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps(integrations))

        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.find_agents_using_integration"
        ) as mock_find:
            mock_find.return_value = [("host1", "agent1")]

            with pytest.raises(IntegrationInUseError) as exc_info:
                remove_integration("my-github")
            assert "assigned to agents" in str(exc_info.value)
            assert "host1:agent1" in str(exc_info.value)

    def test_force_removes_even_when_in_use(self, tmp_path):
        """force=True removes integration even when assigned."""
        integrations = [{"name": "my-github", "type": "github"}]
        integrations_file = tmp_path / INTEGRATIONS_FILE
        integrations_file.write_text(json.dumps(integrations))

        with patch(
            "clawrium.core.integrations.get_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.init_config_dir", return_value=tmp_path
        ), patch(
            "clawrium.core.integrations.find_agents_using_integration"
        ) as mock_find, patch(
            "clawrium.core.integrations.remove_integration_credentials"
        ):
            mock_find.return_value = [("host1", "agent1")]

            result = remove_integration("my-github", force=True)
            assert result is True
            # Verify integration was removed
            remaining = load_integrations()
            assert len(remaining) == 0
