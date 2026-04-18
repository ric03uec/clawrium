"""Tests for claw health checking."""

import pytest
from unittest.mock import patch, MagicMock

from clawrium.core.health import (
    check_claw_health,
    check_all_claws_on_host,
    get_missing_secrets,
    get_onboarding_status,
    count_completed_stages,
    ClawStatus,
    ONBOARDING_STEP_MAP,
)
from clawrium.core.secrets import SecretsFileCorruptedError


@pytest.fixture
def mock_host():
    """Host record with installed claw."""
    return {
        "hostname": "192.168.1.100",
        "port": 22,
        "agent_name": "xclm",
        "key_id": "testhost",
        "agents": {
            "openclaw": {
                "type": "openclaw",
                "version": "0.1.0",
                "status": "installed",
                "agent_name": "opc-testhost",
            }
        },
    }


def test_health_check_running(mock_host):
    """Process running returns RUNNING status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            # Mock no required secrets for openclaw
            with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.RUNNING
    assert result["agent"] == "openclaw"
    assert result["agent_name"] == "opc-testhost"
    assert result["error"] is None
    assert result["missing_secrets"] is None
    assert result["onboarding_step"] is None
    assert result["process_running"] is True


def test_health_check_stopped_no_onboarding(mock_host):
    """Process not running without onboarding returns PENDING_ONBOARD status."""
    mock_runner = MagicMock()
    mock_runner.status = "failed"
    mock_runner.events = [
        {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    # Without onboarding record, should return PENDING_ONBOARD for backward compatibility
    assert result["status"] == ClawStatus.PENDING_ONBOARD
    assert result["missing_secrets"] is None
    assert result["onboarding_step"] is None
    assert result["process_running"] is False


def test_health_check_ssh_fails(mock_host):
    """SSH failure returns UNKNOWN status with error."""
    mock_runner = MagicMock()
    mock_runner.status = "failed"
    mock_runner.events = []

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "SSH failed" in result["error"]


def test_health_check_not_installed(mock_host):
    """Claw not in host record returns NOT_INSTALLED."""
    result = check_claw_health("zeroclaw", mock_host)

    assert result["status"] == ClawStatus.NOT_INSTALLED


def test_health_check_no_ssh_key(mock_host):
    """Missing SSH key returns UNKNOWN."""
    with patch("clawrium.core.health.get_host_private_key", return_value=None):
        result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "SSH key not found" in result["error"]


def test_health_check_timeout(mock_host):
    """Timeout returns UNKNOWN status."""
    mock_runner = MagicMock()
    mock_runner.status = "timeout"
    mock_runner.events = []

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "timed out" in result["error"]


def test_check_all_claws_on_host(mock_host):
    """check_all_claws_on_host returns results for each claw."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            # Mock no required secrets for openclaw
            with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                results = check_all_claws_on_host(mock_host)

    assert len(results) == 1
    assert results[0]["agent"] == "openclaw"
    assert results[0]["status"] == ClawStatus.RUNNING
    assert results[0]["onboarding_step"] is None


def test_health_check_never_modifies_state(mock_host):
    """Health checks are read-only operations and never call update_host."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                with patch("clawrium.core.hosts.update_host") as mock_update:
                    check_claw_health("openclaw", mock_host)

    # Assert health check never modifies persisted state
    assert mock_update.call_count == 0


def test_health_check_no_claw_user():
    """Missing claw user returns UNKNOWN status with error."""
    host = {
        "hostname": "192.168.1.100",
        "agents": {
            "openclaw": {
                "version": "0.1.0",
                "status": "installed",
                # No "user" field
            }
        },
    }

    result = check_claw_health("openclaw", host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "No claw user recorded" in result["error"]


def test_health_check_corrupted_host_data():
    """Corrupted host data (missing hostname) returns UNKNOWN status."""
    # Malformed host missing critical fields
    corrupted_host = {
        "agents": {
            "openclaw": {
                "version": "0.1.0",
                "status": "installed",
                "agent_name": "opc-test",
            }
        }
        # Missing "hostname" field
    }

    result = check_claw_health("openclaw", corrupted_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert result["error"] is not None


def test_health_check_invalid_claw_user():
    """Invalid claw user format returns UNKNOWN status with error."""
    host = {
        "hostname": "192.168.1.100",
        "agents": {
            "openclaw": {
                "version": "0.1.0",
                "status": "installed",
                "agent_name": "root; rm -rf /",  # Command injection attempt
            }
        },
    }

    result = check_claw_health("openclaw", host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "Invalid claw user format" in result["error"]


def test_health_check_host_unreachable(mock_host):
    """Host unreachable returns UNKNOWN status."""
    mock_runner = MagicMock()
    mock_runner.status = (
        "successful"  # ansible-runner returns successful even for unreachable
    )
    mock_runner.events = [{"event": "runner_on_unreachable", "event_data": {}}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "unreachable" in result["error"].lower()


def test_health_check_unexpected_exit_code(mock_host):
    """Unexpected pgrep exit code returns UNKNOWN status."""
    mock_runner = MagicMock()
    mock_runner.status = "failed"
    mock_runner.events = [
        {"event": "runner_on_failed", "event_data": {"res": {"rc": 2}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "Unexpected exit code" in result["error"]


def test_claw_status_degraded_exists():
    """ClawStatus.DEGRADED enum value exists."""
    assert hasattr(ClawStatus, "DEGRADED")
    assert ClawStatus.DEGRADED == "degraded"


def test_health_result_has_missing_secrets_field(mock_host):
    """HealthResult includes missing_secrets field with None when no required secrets."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch(
                "clawrium.core.health.get_instance_secrets",
                return_value={"OPENAI_API_KEY": {}},
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    result = check_claw_health("openclaw", mock_host)

    # Assert exact value: None when running with no required secrets
    assert result["missing_secrets"] is None
    assert result["status"] == ClawStatus.RUNNING


def test_check_claw_health_degraded_when_missing_secrets(mock_host):
    """Running claw with missing required secrets returns DEGRADED status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    # Mock required secrets for openclaw
    required_secrets = [
        {"key": "OPENAI_API_KEY", "description": "OpenAI API key"},
        {"key": "ANTHROPIC_API_KEY", "description": "Anthropic API key"},
    ]

    # Mock empty instance secrets (all missing)
    instance_secrets = {}

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch(
                "clawrium.core.health.get_instance_secrets",
                return_value=instance_secrets,
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets",
                    return_value=required_secrets,
                ):
                    result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.DEGRADED
    assert result["missing_secrets"] is not None
    assert len(result["missing_secrets"]) == 2
    assert "OPENAI_API_KEY" in result["missing_secrets"]
    assert "ANTHROPIC_API_KEY" in result["missing_secrets"]


def test_check_claw_health_running_when_all_secrets_present(mock_host):
    """Running claw with all required secrets returns RUNNING status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    # Mock required secrets for openclaw
    required_secrets = [
        {"key": "OPENAI_API_KEY", "description": "OpenAI API key"},
    ]

    # Mock instance secrets (all present)
    instance_secrets = {
        "OPENAI_API_KEY": {
            "key": "OPENAI_API_KEY",
            "value": "sk-test",
            "created_at": "2026-03-22T00:00:00Z",
            "updated_at": "2026-03-22T00:00:00Z",
            "description": "",
        }
    }

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch(
                "clawrium.core.health.get_instance_secrets",
                return_value=instance_secrets,
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets",
                    return_value=required_secrets,
                ):
                    result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.RUNNING
    assert result["missing_secrets"] is None


def test_check_claw_health_degraded_partial_secrets(mock_host):
    """Running claw with some missing secrets returns DEGRADED."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    # Mock required secrets for openclaw
    required_secrets = [
        {"key": "OPENAI_API_KEY", "description": "OpenAI API key"},
        {"key": "ANTHROPIC_API_KEY", "description": "Anthropic API key"},
    ]

    # Mock partial instance secrets (one present, one missing)
    instance_secrets = {
        "OPENAI_API_KEY": {
            "key": "OPENAI_API_KEY",
            "value": "sk-test",
            "created_at": "2026-03-22T00:00:00Z",
            "updated_at": "2026-03-22T00:00:00Z",
            "description": "",
        }
    }

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch(
                "clawrium.core.health.get_instance_secrets",
                return_value=instance_secrets,
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets",
                    return_value=required_secrets,
                ):
                    result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.DEGRADED
    assert result["missing_secrets"] == ["ANTHROPIC_API_KEY"]


def test_check_claw_health_corrupted_secrets_file(mock_host):
    """Corrupted secrets file returns DEGRADED status with error message."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    # Mock required secrets for openclaw
    required_secrets = [{"key": "OPENAI_API_KEY", "description": "OpenAI API key"}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            # Mock get_instance_secrets to raise SecretsFileCorruptedError
            with patch(
                "clawrium.core.health.get_instance_secrets",
                side_effect=SecretsFileCorruptedError("Secrets file is corrupted"),
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets",
                    return_value=required_secrets,
                ):
                    result = check_claw_health("openclaw", mock_host)

    # Should return DEGRADED with error message, not crash
    assert result["status"] == ClawStatus.DEGRADED
    assert result["error"] is not None
    assert "corrupted" in result["error"].lower()


def test_check_claw_health_uses_type_not_key_for_secrets():
    """Regression test: secrets lookup uses agent type, not agent key.

    When the agent key (e.g., 'wolf-i') differs from the agent type (e.g., 'openclaw'),
    get_required_secrets must receive the type, not the key. Otherwise, it would fail
    with ManifestNotFoundError because there's no 'wolf-i' manifest.
    """
    # Host with agent key 'wolf-i' but type 'openclaw'
    host = {
        "hostname": "192.168.1.100",
        "port": 22,
        "key_id": "testhost",
        "agents": {
            "wolf-i": {  # Key differs from type
                "type": "openclaw",  # Actual agent type
                "version": "2026.4.2",
                "status": "installed",
                "agent_name": "wolf-i",
            }
        },
    }

    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch(
                "clawrium.core.health.get_instance_secrets", return_value={}
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ) as mock_required:
                    result = check_claw_health("wolf-i", host)

    # Should call get_required_secrets with 'openclaw' (the type), not 'wolf-i' (the key)
    mock_required.assert_called_once_with("openclaw")

    # Should succeed without ManifestNotFoundError
    assert result["status"] == ClawStatus.RUNNING


def test_missing_secrets_none_for_non_running_status(mock_host):
    """Non-running status has missing_secrets as None."""
    mock_runner = MagicMock()
    mock_runner.status = "failed"
    mock_runner.events = [
        {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    # Without onboarding record, stopped process returns PENDING_ONBOARD
    assert result["status"] == ClawStatus.PENDING_ONBOARD
    assert result["missing_secrets"] is None


# Tests for get_missing_secrets() - B4/B5 ATX review fix


class TestGetMissingSecrets:
    """Tests for get_missing_secrets function - core Phase 06 logic."""

    def test_claw_name_from_record_name_field(self):
        """Uses agent name from 'agent_name' field (canonical field)."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"name": "work", "agent_name": "opc-work"}

        with patch("clawrium.core.health.get_instance_key") as mock_key:
            mock_key.return_value = "192.168.1.100:openclaw:opc-work"
            with patch("clawrium.core.health.get_instance_secrets", return_value={}):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    get_missing_secrets("openclaw", host, claw_record)

        # Verify instance key was built with correct agent_name
        mock_key.assert_called_once_with("192.168.1.100", "openclaw", "opc-work")

    def test_claw_name_derived_from_user_fallback(self):
        """Falls back to using user field directly."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"agent_name": "opc-work"}  # No 'name' field

        with patch("clawrium.core.health.get_instance_key") as mock_key:
            mock_key.return_value = "192.168.1.100:openclaw:opc-work"
            with patch("clawrium.core.health.get_instance_secrets", return_value={}):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    get_missing_secrets("openclaw", host, claw_record)

        # Verify user value was used directly
        mock_key.assert_called_once_with("192.168.1.100", "openclaw", "opc-work")

    def test_multi_hyphen_claw_name(self):
        """Preserves multi-hyphen user names exactly."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"agent_name": "opc-my-claw"}  # Multi-hyphen

        with patch("clawrium.core.health.get_instance_key") as mock_key:
            mock_key.return_value = "192.168.1.100:openclaw:opc-my-claw"
            with patch("clawrium.core.health.get_instance_secrets", return_value={}):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    get_missing_secrets("openclaw", host, claw_record)

        # Verify full value is preserved
        mock_key.assert_called_once_with("192.168.1.100", "openclaw", "opc-my-claw")

    def test_no_hyphen_fallback(self):
        """Handles user names without hyphen (uses full name)."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"agent_name": "simpleuser"}  # No hyphen

        with patch("clawrium.core.health.get_instance_key") as mock_key:
            mock_key.return_value = "192.168.1.100:openclaw:simpleuser"
            with patch("clawrium.core.health.get_instance_secrets", return_value={}):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    get_missing_secrets("openclaw", host, claw_record)

        # Verify full username used when no hyphen
        mock_key.assert_called_once_with("192.168.1.100", "openclaw", "simpleuser")

    def test_empty_user_string_returns_empty(self):
        """Returns empty list when claw name cannot be determined."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"agent_name": ""}  # Empty user, no name field

        result = get_missing_secrets("openclaw", host, claw_record)

        assert result == []

    def test_missing_user_and_name_returns_empty(self):
        """Returns empty list when both name and user are missing."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {}  # No name, no user

        result = get_missing_secrets("openclaw", host, claw_record)

        assert result == []

    def test_returns_missing_secrets(self):
        """Returns list of missing required secrets."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"name": "work", "agent_name": "opc-work"}

        required = [
            {"key": "OPENAI_API_KEY", "description": "OpenAI key"},
            {"key": "ANTHROPIC_API_KEY", "description": "Anthropic key"},
        ]
        instance_secrets = {
            "OPENAI_API_KEY": {"key": "OPENAI_API_KEY", "value": "sk-test"}
        }

        with patch(
            "clawrium.core.health.get_instance_secrets", return_value=instance_secrets
        ):
            with patch(
                "clawrium.core.health.get_required_secrets", return_value=required
            ):
                result = get_missing_secrets("openclaw", host, claw_record)

        assert result == ["ANTHROPIC_API_KEY"]

    def test_returns_empty_when_all_present(self):
        """Returns empty list when all required secrets are present."""
        host = {"hostname": "192.168.1.100"}
        claw_record = {"name": "work", "agent_name": "opc-work"}

        required = [{"key": "OPENAI_API_KEY", "description": "OpenAI key"}]
        instance_secrets = {
            "OPENAI_API_KEY": {"key": "OPENAI_API_KEY", "value": "sk-test"}
        }

        with patch(
            "clawrium.core.health.get_instance_secrets", return_value=instance_secrets
        ):
            with patch(
                "clawrium.core.health.get_required_secrets", return_value=required
            ):
                result = get_missing_secrets("openclaw", host, claw_record)

        assert result == []


def test_degraded_status_verifies_instance_key_argument(mock_host):
    """B5: Verify instance_key argument passed to get_instance_secrets is correct."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

    # Mock required secrets
    required_secrets = [{"key": "OPENAI_API_KEY", "description": "OpenAI"}]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            with patch("clawrium.core.health.get_instance_secrets") as mock_get_secrets:
                mock_get_secrets.return_value = {}  # All missing
                with patch(
                    "clawrium.core.health.get_required_secrets",
                    return_value=required_secrets,
                ):
                    result = check_claw_health("openclaw", mock_host)

    # Verify correct instance key was passed
    # mock_host has hostname 192.168.1.100 and claw user opc-testhost
    mock_get_secrets.assert_called_once()
    call_args = mock_get_secrets.call_args[0][0]
    assert call_args == "192.168.1.100:openclaw:opc-testhost"
    assert result["status"] == ClawStatus.DEGRADED


# Tests for onboarding-aware statuses - Issue #70


class TestClawStatusOnboardingEnums:
    """Tests for new ClawStatus enum values."""

    def test_pending_onboard_status_exists(self):
        """ClawStatus.PENDING_ONBOARD enum value exists."""
        assert hasattr(ClawStatus, "PENDING_ONBOARD")
        assert ClawStatus.PENDING_ONBOARD == "pending_onboard"

    def test_onboarding_status_exists(self):
        """ClawStatus.ONBOARDING enum value exists."""
        assert hasattr(ClawStatus, "ONBOARDING")
        assert ClawStatus.ONBOARDING == "onboarding"

    def test_ready_status_exists(self):
        """ClawStatus.READY enum value exists."""
        assert hasattr(ClawStatus, "READY")
        assert ClawStatus.READY == "ready"


class TestGetOnboardingStatus:
    """Tests for get_onboarding_status helper function."""

    def test_no_onboarding_record_returns_pending_onboard(self):
        """Missing onboarding record returns PENDING_ONBOARD for backward compatibility."""
        claw_record = {"version": "0.1.0", "agent_name": "opc-test"}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.PENDING_ONBOARD
        assert step is None

    def test_pending_state_returns_pending_onboard(self):
        """Onboarding state 'pending' returns PENDING_ONBOARD."""
        claw_record = {"onboarding": {"state": "pending"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.PENDING_ONBOARD
        assert step is None

    def test_ready_state_returns_ready(self):
        """Onboarding state 'ready' returns READY."""
        claw_record = {"onboarding": {"state": "ready"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.READY
        assert step is None

    def test_providers_state_returns_onboarding_step_1(self):
        """Onboarding state 'providers' returns ONBOARDING with step 1/4."""
        claw_record = {"onboarding": {"state": "providers"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.ONBOARDING
        assert step == "1/4"

    def test_identity_state_returns_onboarding_step_2(self):
        """Onboarding state 'identity' returns ONBOARDING with step 2/4."""
        claw_record = {"onboarding": {"state": "identity"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.ONBOARDING
        assert step == "2/4"

    def test_channels_state_returns_onboarding_step_3(self):
        """Onboarding state 'channels' returns ONBOARDING with step 3/4."""
        claw_record = {"onboarding": {"state": "channels"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.ONBOARDING
        assert step == "3/4"

    def test_validate_state_returns_onboarding_step_4(self):
        """Onboarding state 'validate' returns ONBOARDING with step 4/4."""
        claw_record = {"onboarding": {"state": "validate"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.ONBOARDING
        assert step == "4/4"

    def test_unknown_state_returns_onboarding_no_step(self):
        """Unknown onboarding state returns ONBOARDING with None step."""
        claw_record = {"onboarding": {"state": "unknown_state"}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.ONBOARDING
        assert step is None

    # B3 fix tests: corrupted/non-dict onboarding records
    @pytest.mark.parametrize("bad_value", ["done", 1, [], True, 3.14])
    def test_non_dict_onboarding_returns_pending_onboard(self, bad_value):
        """B3: Non-dict onboarding value returns PENDING_ONBOARD without raising."""
        claw_record = {"onboarding": bad_value}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.PENDING_ONBOARD
        assert step is None

    # B4 fix tests: state=None handling
    def test_null_state_returns_pending_onboard(self):
        """B4: Explicit null state returns PENDING_ONBOARD, not ONBOARDING."""
        claw_record = {"onboarding": {"state": None}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.PENDING_ONBOARD
        assert step is None

    def test_empty_string_state_returns_pending_onboard(self):
        """B4: Empty string state returns PENDING_ONBOARD."""
        claw_record = {"onboarding": {"state": ""}}
        status, step = get_onboarding_status(claw_record)
        assert status == ClawStatus.PENDING_ONBOARD
        assert step is None

    def test_malformed_stages_data_returns_pending_onboard(self):
        """Malformed stages (string instead of dict) returns PENDING_ONBOARD gracefully."""
        claw_record = {
            "onboarding": {"state": "providers", "stages": "malformed-string"}
        }
        status, step = get_onboarding_status(claw_record)
        # Should handle gracefully - return ONBOARDING with step based on state
        assert status == ClawStatus.ONBOARDING
        assert step == "1/4"


class TestOnboardingStepMap:
    """Tests for ONBOARDING_STEP_MAP constant."""

    def test_step_map_has_four_stages(self):
        """Step map contains all four onboarding stages."""
        assert len(ONBOARDING_STEP_MAP) == 4

    def test_step_map_values(self):
        """Step map has correct values."""
        assert ONBOARDING_STEP_MAP["providers"] == "1/4"
        assert ONBOARDING_STEP_MAP["identity"] == "2/4"
        assert ONBOARDING_STEP_MAP["channels"] == "3/4"
        assert ONBOARDING_STEP_MAP["validate"] == "4/4"


class TestHealthCheckOnboardingIntegration:
    """Integration tests for health check with onboarding states."""

    @pytest.fixture
    def mock_host_with_onboarding(self):
        """Host with installed claw that has onboarding state."""
        return {
            "hostname": "192.168.1.100",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "testhost",
            "agents": {
                "openclaw": {
                    "type": "openclaw",
                    "version": "0.1.0",
                    "status": "installed",
                    "agent_name": "opc-testhost",
                    "onboarding": {
                        "state": "providers",
                        "started_at": "2026-04-06T00:00:00+00:00",
                    },
                }
            },
        }

    def test_stopped_claw_in_providers_state(self, mock_host_with_onboarding):
        """Stopped claw in providers state returns ONBOARDING with step 1/4."""
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.ONBOARDING
        assert result["onboarding_step"] == "1/4"
        assert result["error"] is None
        assert result["missing_secrets"] is None
        assert result["process_running"] is False
        assert result["onboarding_stages"] is None

    def test_stopped_claw_in_identity_state(self, mock_host_with_onboarding):
        """Stopped claw in identity state returns ONBOARDING with step 2/4."""
        mock_host_with_onboarding["agents"]["openclaw"]["onboarding"]["state"] = (
            "identity"
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.ONBOARDING
        assert result["onboarding_step"] == "2/4"
        assert result["error"] is None
        assert result["missing_secrets"] is None
        assert result["process_running"] is False
        assert result["onboarding_stages"] is None

    def test_stopped_claw_in_channels_state(self, mock_host_with_onboarding):
        """Stopped claw in channels state returns ONBOARDING with step 3/4."""
        mock_host_with_onboarding["agents"]["openclaw"]["onboarding"]["state"] = (
            "channels"
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.ONBOARDING
        assert result["onboarding_step"] == "3/4"
        assert result["error"] is None
        assert result["missing_secrets"] is None
        assert result["process_running"] is False
        assert result["onboarding_stages"] is None

    def test_stopped_claw_in_validate_state(self, mock_host_with_onboarding):
        """Stopped claw in validate state returns ONBOARDING with step 4/4."""
        mock_host_with_onboarding["agents"]["openclaw"]["onboarding"]["state"] = (
            "validate"
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.ONBOARDING
        assert result["onboarding_step"] == "4/4"
        assert result["error"] is None
        assert result["missing_secrets"] is None
        assert result["process_running"] is False
        assert result["onboarding_stages"] is None

    def test_stopped_claw_in_ready_state(self, mock_host_with_onboarding):
        """Stopped claw in ready state returns READY."""
        mock_host_with_onboarding["agents"]["openclaw"]["onboarding"]["state"] = "ready"

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.READY
        assert result["onboarding_step"] is None
        assert result["process_running"] is False
        assert result["onboarding_stages"] is None

    def test_stopped_claw_in_pending_state(self, mock_host_with_onboarding):
        """Stopped claw in pending state returns PENDING_ONBOARD."""
        mock_host_with_onboarding["agents"]["openclaw"]["onboarding"]["state"] = (
            "pending"
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.PENDING_ONBOARD
        assert result["onboarding_step"] is None
        assert result["process_running"] is False
        assert result["onboarding_stages"] is None

    def test_running_claw_ignores_onboarding_state(self, mock_host_with_onboarding):
        """Running claw returns RUNNING regardless of onboarding state."""
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    result = check_claw_health("openclaw", mock_host_with_onboarding)

        assert result["status"] == ClawStatus.RUNNING
        assert result["onboarding_step"] is None
        assert result["process_running"] is True
        assert result["onboarding_stages"] is None


class TestHealthResultOnboardingStepField:
    """Tests for onboarding_step field in HealthResult."""

    def test_not_installed_has_onboarding_step_none(self):
        """NOT_INSTALLED status has onboarding_step as None."""
        host = {
            "hostname": "192.168.1.100",
            "agents": {},
        }
        result = check_claw_health("openclaw", host)
        assert result["status"] == ClawStatus.NOT_INSTALLED
        assert "onboarding_step" in result
        assert result["onboarding_step"] is None

    def test_unknown_has_onboarding_step_none(self):
        """UNKNOWN status has onboarding_step as None."""
        host = {
            "hostname": "192.168.1.100",
            "agents": {
                "openclaw": {"version": "0.1.0", "status": "installed"}
                # Missing user field
            },
        }
        result = check_claw_health("openclaw", host)
        assert result["status"] == ClawStatus.UNKNOWN
        assert result["onboarding_step"] is None


class TestProcessRunningField:
    """Tests for process_running field in HealthResult - B1/B2 fix."""

    @pytest.fixture
    def mock_host(self):
        """Host record with installed claw."""
        return {
            "hostname": "192.168.1.100",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "testhost",
            "agents": {
                "openclaw": {
                    "type": "openclaw",
                    "version": "0.1.0",
                    "status": "installed",
                    "agent_name": "opc-testhost",
                }
            },
        }

    def test_running_process_has_process_running_true(self, mock_host):
        """RUNNING status has process_running=True."""
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.health.get_required_secrets", return_value=[]
                ):
                    result = check_claw_health("openclaw", mock_host)

        assert result["status"] == ClawStatus.RUNNING
        assert result["process_running"] is True

    def test_degraded_process_has_process_running_true(self, mock_host):
        """DEGRADED status has process_running=True (process is running but missing secrets)."""
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}
        ]

        required = [{"key": "OPENAI_API_KEY", "description": "test"}]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.health.get_instance_secrets", return_value={}
                ):
                    with patch(
                        "clawrium.core.health.get_required_secrets",
                        return_value=required,
                    ):
                        result = check_claw_health("openclaw", mock_host)

        assert result["status"] == ClawStatus.DEGRADED
        assert result["process_running"] is True

    def test_stopped_process_has_process_running_false(self, mock_host):
        """Stopped process has process_running=False."""
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host)

        assert result["process_running"] is False

    def test_ready_but_stopped_has_process_running_false(self, mock_host):
        """B2: READY status with stopped process has process_running=False."""
        mock_host["agents"]["openclaw"]["onboarding"] = {"state": "ready"}

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"rc": 1}}}
        ]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host)

        # B2 fix: Can distinguish "ready but stopped" from "running"
        assert result["status"] == ClawStatus.READY
        assert result["process_running"] is False

    def test_not_installed_has_process_running_none(self):
        """NOT_INSTALLED status has process_running=None."""
        host = {"hostname": "192.168.1.100", "agents": {}}
        result = check_claw_health("openclaw", host)
        assert result["status"] == ClawStatus.NOT_INSTALLED
        assert result["process_running"] is None

    def test_unknown_has_process_running_none(self):
        """UNKNOWN status has process_running=None."""
        host = {
            "hostname": "192.168.1.100",
            "agents": {
                "openclaw": {"version": "0.1.0", "status": "installed"}
                # Missing user field
            },
        }
        result = check_claw_health("openclaw", host)
        assert result["status"] == ClawStatus.UNKNOWN
        assert result["process_running"] is None

    def test_timeout_has_process_running_none(self, mock_host):
        """Timeout has process_running=None."""
        mock_runner = MagicMock()
        mock_runner.status = "timeout"
        mock_runner.events = []

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host)

        assert result["status"] == ClawStatus.UNKNOWN
        assert result["process_running"] is None

    def test_ssh_failure_has_process_running_none(self, mock_host):
        """SSH failure has process_running=None."""
        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = []

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host)

        assert result["status"] == ClawStatus.UNKNOWN
        assert result["process_running"] is None

    def test_unreachable_has_process_running_none(self, mock_host):
        """Unreachable host has process_running=None."""
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [{"event": "runner_on_unreachable", "event_data": {}}]

        with patch(
            "clawrium.core.health.get_host_private_key", return_value="/fake/key"
        ):
            with patch(
                "clawrium.core.health.ansible_runner.run", return_value=mock_runner
            ):
                result = check_claw_health("openclaw", mock_host)

        assert result["status"] == ClawStatus.UNKNOWN
        assert result["process_running"] is None


class TestCountCompletedStages:
    """Tests for count_completed_stages function - Issue #73."""

    def test_no_onboarding_returns_zero_four(self):
        """Missing onboarding record returns (0, 4)."""
        claw_record = {"version": "0.1.0", "agent_name": "opc-test"}
        completed, total = count_completed_stages(claw_record)
        assert completed == 0
        assert total == 4

    def test_non_dict_onboarding_returns_zero_four(self):
        """Non-dict onboarding value returns (0, 4)."""
        claw_record = {"onboarding": "invalid"}
        completed, total = count_completed_stages(claw_record)
        assert completed == 0
        assert total == 4

    def test_no_stages_returns_zero_four(self):
        """Missing stages dict returns (0, 4)."""
        claw_record = {"onboarding": {"state": "pending"}}
        completed, total = count_completed_stages(claw_record)
        assert completed == 0
        assert total == 4

    def test_all_stages_pending_returns_zero_four(self):
        """All stages pending returns (0, 4)."""
        claw_record = {
            "onboarding": {
                "state": "pending",
                "stages": {
                    "providers": {"status": "pending"},
                    "identity": {"status": "pending"},
                    "channels": {"status": "pending"},
                    "validate": {"status": "pending"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 0
        assert total == 4

    def test_one_stage_complete_returns_one_four(self):
        """One stage complete returns (1, 4)."""
        claw_record = {
            "onboarding": {
                "state": "identity",
                "stages": {
                    "providers": {"status": "complete"},
                    "identity": {"status": "pending"},
                    "channels": {"status": "pending"},
                    "validate": {"status": "pending"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 1
        assert total == 4

    def test_two_stages_complete_returns_two_four(self):
        """Two stages complete returns (2, 4)."""
        claw_record = {
            "onboarding": {
                "state": "channels",
                "stages": {
                    "providers": {"status": "complete"},
                    "identity": {"status": "complete"},
                    "channels": {"status": "pending"},
                    "validate": {"status": "pending"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 2
        assert total == 4

    def test_all_stages_complete_returns_four_four(self):
        """All stages complete returns (4, 4)."""
        claw_record = {
            "onboarding": {
                "state": "ready",
                "stages": {
                    "providers": {"status": "complete"},
                    "identity": {"status": "complete"},
                    "channels": {"status": "complete"},
                    "validate": {"status": "complete"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 4
        assert total == 4

    def test_skipped_stage_counts_as_complete(self):
        """Skipped stages count toward completed count."""
        claw_record = {
            "onboarding": {
                "state": "validate",
                "stages": {
                    "providers": {"status": "complete"},
                    "identity": {"status": "skipped"},
                    "channels": {"status": "complete"},
                    "validate": {"status": "pending"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 3
        assert total == 4

    def test_mixed_complete_and_skipped(self):
        """Mixed complete and skipped stages count correctly."""
        claw_record = {
            "onboarding": {
                "state": "ready",
                "stages": {
                    "providers": {"status": "skipped"},
                    "identity": {"status": "skipped"},
                    "channels": {"status": "skipped"},
                    "validate": {"status": "skipped"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 4
        assert total == 4

    def test_non_dict_stage_value_ignored(self):
        """Non-dict stage values are ignored in count."""
        claw_record = {
            "onboarding": {
                "state": "identity",
                "stages": {
                    "providers": {"status": "complete"},
                    "identity": "invalid",  # Non-dict value
                    "channels": {"status": "pending"},
                    "validate": {"status": "pending"},
                },
            }
        }
        completed, total = count_completed_stages(claw_record)
        assert completed == 1
        assert total == 4

    def test_stages_is_string_not_dict_returns_zero(self):
        """Malformed stages (string instead of dict) returns (0, 4) gracefully."""
        claw_record = {"onboarding": {"state": "providers", "stages": "malformed"}}
        completed, total = count_completed_stages(claw_record)
        assert completed == 0
        assert total == 4


class TestProcessNameByAgentType:
    """Tests for agent-type-aware process name in health check (issue #224)."""

    def test_openclaw_uses_openclaw_process_name(self):
        """openclaw agent type uses 'pgrep -u {user} openclaw'."""
        host = {
            "hostname": "192.168.1.100",
            "port": 22,
            "user": "xclm",
            "key_id": "testhost",
            "agents": {
                "my-openclaw": {
                    "type": "openclaw",
                    "agent_name": "wolf-i",
                    "version": "0.1.0",
                }
            },
        }

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

        with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
            with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner) as mock_run:
                with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                    check_claw_health("my-openclaw", host)

        # Verify first call (pgrep) uses 'openclaw' process name
        # Second call is for system info (cpu/memory)
        assert len(mock_run.call_args_list) >= 1
        first_call = mock_run.call_args_list[0]
        module_args = first_call.kwargs.get("module_args", "")
        assert "pgrep -u wolf-i openclaw" == module_args

    def test_zeroclaw_uses_node_process_name(self):
        """zeroclaw agent type uses 'pgrep -u {user} node'."""
        host = {
            "hostname": "192.168.1.100",
            "port": 22,
            "user": "xclm",
            "key_id": "testhost",
            "agents": {
                "my-zeroclaw": {
                    "type": "zeroclaw",
                    "agent_name": "zc-edge",
                    "version": "0.1.0",
                }
            },
        }

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

        with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
            with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner) as mock_run:
                with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                    check_claw_health("my-zeroclaw", host)

        # Verify first call (pgrep) uses 'node' process name
        # Second call is for system info (cpu/memory)
        assert len(mock_run.call_args_list) >= 1
        first_call = mock_run.call_args_list[0]
        module_args = first_call.kwargs.get("module_args", "")
        assert "pgrep -u zc-edge node" == module_args

    def test_missing_type_defaults_to_node(self):
        """Agent without type field defaults to 'node' process name."""
        host = {
            "hostname": "192.168.1.100",
            "port": 22,
            "user": "xclm",
            "key_id": "testhost",
            "agents": {
                "legacy-agent": {
                    "agent_name": "legacy-user",
                    "version": "0.1.0",
                    # No "type" field
                }
            },
        }

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

        with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
            with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner) as mock_run:
                with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                    check_claw_health("legacy-agent", host)

        # Verify first call (pgrep) defaults to 'node' process name
        # Second call is for system info (cpu/memory)
        assert len(mock_run.call_args_list) >= 1
        first_call = mock_run.call_args_list[0]
        module_args = first_call.kwargs.get("module_args", "")
        assert "pgrep -u legacy-user node" == module_args

    def test_empty_type_defaults_to_node(self):
        """Agent with empty type string defaults to 'node' process name."""
        host = {
            "hostname": "192.168.1.100",
            "port": 22,
            "user": "xclm",
            "key_id": "testhost",
            "agents": {
                "empty-type-agent": {
                    "type": "",
                    "agent_name": "empty-user",
                    "version": "0.1.0",
                }
            },
        }

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = [{"event": "runner_on_ok", "event_data": {"res": {"rc": 0}}}]

        with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
            with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner) as mock_run:
                with patch("clawrium.core.health.get_required_secrets", return_value=[]):
                    check_claw_health("empty-type-agent", host)

        # Verify first call (pgrep) defaults to 'node' process name
        # Second call is for system info (cpu/memory)
        assert len(mock_run.call_args_list) >= 1
        first_call = mock_run.call_args_list[0]
        module_args = first_call.kwargs.get("module_args", "")
        assert "pgrep -u empty-user node" == module_args
