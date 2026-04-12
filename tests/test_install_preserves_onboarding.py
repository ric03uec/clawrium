"""Tests for onboarding preservation during reinstall."""

import json
import pytest
from unittest.mock import MagicMock, patch
from clawrium.core.install import run_installation
from clawrium.core.onboarding import (
    initialize_onboarding,
    get_onboarding_state,
    OnboardingState,
)
from clawrium.core.hosts import get_host


@pytest.fixture
def host_with_ready_agent(isolated_config, monkeypatch):
    """Set up a host with an agent in READY onboarding state."""
    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "192.168.1.100",
            "hardware": {
                "architecture": "x86_64",
                "os": "ubuntu",
                "os_version": "24.04",
                "memtotal_mb": 4096,
            },
            "agents": {
                "work": {  # Instance name is the key
                    "type": "openclaw",
                    "version": "0.1.0",
                    "status": "installed",
                    "installed_at": "2026-04-06T00:00:00+00:00",
                    "error": None,
                    "onboarding": {
                        "state": "ready",
                        "started_at": "2026-04-06T00:00:00+00:00",
                        "stages": {
                            "providers": {
                                "status": "complete",
                                "completed_at": "2026-04-06T00:01:00+00:00",
                                "provider_id": "anthropic",
                            },
                            "identity": {
                                "status": "complete",
                                "completed_at": "2026-04-06T00:02:00+00:00",
                            },
                            "channels": {
                                "status": "complete",
                                "completed_at": "2026-04-06T00:03:00+00:00",
                            },
                            "validate": {
                                "status": "complete",
                                "completed_at": "2026-04-06T00:04:00+00:00",
                            },
                        },
                    },
                }
            },
        }
    ]

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / "hosts.json"
    hosts_path.write_text(json.dumps(hosts_data))

    # Mock SSH key
    import clawrium.core.install
    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: "fake-ssh-key"
    )

    # Mock manifest
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"python": ">=3.9"},
                },
            }
        ],
    }

    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    return isolated_config


class TestReinstallPreservesOnboarding:
    """Test that reinstalling an agent preserves onboarding configuration."""

    def test_reinstall_preserves_ready_state(self, host_with_ready_agent, monkeypatch):
        """Reinstalling agent preserves READY onboarding state."""
        # Mock ansible-runner
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.rc = 0

        with patch("clawrium.core.install.ansible_runner.run") as mock_run:
            mock_run.return_value = mock_result

            # Get pre-reinstall state
            pre_state = get_onboarding_state("192.168.1.100", "work")
            assert pre_state == OnboardingState.READY

            # Reinstall the same agent instance
            run_installation("openclaw", "192.168.1.100", name="work")

            # Assert: Onboarding state still READY
            post_state = get_onboarding_state("192.168.1.100", "work")
            assert post_state == OnboardingState.READY, f"Expected READY, got {post_state}"

    def test_reinstall_preserves_stage_metadata(self, host_with_ready_agent, monkeypatch):
        """Reinstalling preserves stage completion metadata (provider_id, timestamps)."""
        # Mock ansible-runner
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.rc = 0

        with patch("clawrium.core.install.ansible_runner.run") as mock_run:
            mock_run.return_value = mock_result

            # Capture pre-reinstall state
            host = get_host("192.168.1.100")
            pre_onboarding = host["agents"]["work"]["onboarding"]
            pre_provider_id = pre_onboarding["stages"]["providers"]["provider_id"]
            pre_started_at = pre_onboarding["started_at"]
            pre_providers_completed_at = pre_onboarding["stages"]["providers"][
                "completed_at"
            ]

            # Reinstall
            run_installation("openclaw", "192.168.1.100", name="work")

            # Assert: Metadata preserved
            host = get_host("192.168.1.100")
            post_onboarding = host["agents"]["work"]["onboarding"]

            assert post_onboarding["stages"]["providers"]["provider_id"] == pre_provider_id
            assert post_onboarding["started_at"] == pre_started_at
            assert (
                post_onboarding["stages"]["providers"]["completed_at"]
                == pre_providers_completed_at
            )
            assert post_onboarding["stages"]["providers"]["status"] == "complete"

    def test_reinstall_with_cleanup_resets_onboarding(
        self, host_with_ready_agent, monkeypatch
    ):
        """Using --cleanup-failed resets onboarding to PENDING."""
        # Mock ansible-runner
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.rc = 0

        with patch("clawrium.core.install.ansible_runner.run") as mock_run:
            mock_run.return_value = mock_result

            # Reinstall with cleanup
            run_installation(
                "openclaw", "192.168.1.100", name="work", cleanup_failed=True
            )

            # Assert: Onboarding reset to PENDING
            state = get_onboarding_state("192.168.1.100", "work")
            assert state == OnboardingState.PENDING

    def test_initialize_onboarding_skips_if_exists(self, host_with_ready_agent):
        """initialize_onboarding() is idempotent - skips if onboarding already exists."""
        # Get pre-initialization state
        host = get_host("192.168.1.100")
        pre_onboarding = host["agents"]["work"]["onboarding"]
        pre_state = pre_onboarding["state"]
        pre_provider_id = pre_onboarding["stages"]["providers"]["provider_id"]

        # Call initialize_onboarding (should be no-op)
        result = initialize_onboarding("192.168.1.100", "work")
        assert result is True

        # Verify state unchanged
        host = get_host("192.168.1.100")
        post_onboarding = host["agents"]["work"]["onboarding"]

        assert post_onboarding["state"] == pre_state
        assert post_onboarding["stages"]["providers"]["provider_id"] == pre_provider_id
        assert post_onboarding == pre_onboarding  # Entire structure unchanged
