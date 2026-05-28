"""Tests for the OS-family playbook resolver (issue #469 step 1)."""

from __future__ import annotations

import pytest

from clawrium.core.playbook_resolver import (
    resolve_agent_playbook,
    resolve_base_playbook,
)


class TestResolveBasePlaybook:
    def test_linux_returns_existing_base(self):
        path = resolve_base_playbook("linux")
        assert path.name == "base.yaml"
        assert path.exists()

    def test_darwin_returns_existing_base_macos(self):
        """Step 4 of #469 landed base_macos.yaml; resolver returns it."""
        path = resolve_base_playbook("darwin")
        assert path.name == "base_macos.yaml"
        assert path.exists()

    def test_unknown_os_family_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported os_family"):
            resolve_base_playbook("windows")


class TestResolveAgentPlaybook:
    def test_linux_hermes_install_returns_existing(self):
        path = resolve_agent_playbook("hermes", "install", "linux")
        assert path.name == "install.yaml"
        assert path.exists()

    def test_linux_zeroclaw_configure_returns_existing(self):
        path = resolve_agent_playbook("zeroclaw", "configure", "linux")
        assert path.name == "configure.yaml"
        assert path.exists()

    def test_darwin_hermes_install_raises_until_step_5(self):
        with pytest.raises(FileNotFoundError) as exc:
            resolve_agent_playbook("hermes", "install", "darwin")
        assert "install_macos.yaml" in str(exc.value)
        assert "hermes" in str(exc.value)
        assert "darwin" in str(exc.value)

    def test_unknown_agent_type_raises_file_not_found(self):
        # Same error class as Mac-missing — caller can distinguish via the
        # path embedded in the message.
        with pytest.raises(FileNotFoundError):
            resolve_agent_playbook("nonexistent-agent", "install", "linux")

    def test_unknown_os_family_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported os_family"):
            resolve_agent_playbook("hermes", "install", "windows")
