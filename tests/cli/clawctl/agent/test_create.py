"""Tests for `clawctl agent create` — persisted hosts.json shape.

Phase 2 of #11 (issue #944): a fresh `create --type openclaw --name X`
must persist three new keys under
`hosts.json.agents.<X>.config`:

  - `runtime: "nemoclaw"`
  - `sandbox_name: <derived from agent name>`
  - `nemoclaw_version: <core.nemoclaw.NEMOCLAW_VERSION>`

Legacy bare openclaw records (no `runtime` key) MUST survive a
re-install untouched — Phase 2 is additive; Phase 3 (issue #945)
carries the breaking removal of the bare path.

The tests drive `run_installation` directly (same pattern as
`tests/test_install_preserves_onboarding.py`) so the persistence
shape is asserted post-install without shelling through Typer.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.install import run_installation
from clawrium.core.nemoclaw import NEMOCLAW_VERSION


def _write_bare_host(isolated_config, agents_block):
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
                "memtotal_mb": 8192,
            },
            "agents": agents_block,
        }
    ]
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(json.dumps(hosts_data))


@pytest.fixture
def openclaw_install_env(isolated_config, monkeypatch):
    """Mock SSH + manifest + ansible-runner so `run_installation`
    reaches `set_installed` without touching the network."""
    import clawrium.core.install as install_mod

    monkeypatch.setattr(install_mod, "get_host_private_key", lambda x: "fake-ssh-key")
    monkeypatch.setattr(
        install_mod,
        "load_manifest",
        lambda x: {
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
        },
    )
    return isolated_config


def _run_ansible_successfully():
    mock_result = MagicMock()
    mock_result.status = "successful"
    mock_result.rc = 0
    return mock_result


class TestOpenclawCreateNemoclawConfig:
    """Phase 2: new openclaw creates persist the sandbox runtime shape."""

    def test_fresh_create_persists_runtime_nemoclaw(
        self, openclaw_install_env, monkeypatch
    ):
        _write_bare_host(openclaw_install_env, agents_block={})
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=_run_ansible_successfully(),
        ):
            run_installation("openclaw", "192.168.1.100", name="oc-nemo")

        hosts_data = json.loads((openclaw_install_env / "hosts.json").read_text())
        config = hosts_data[0]["agents"]["oc-nemo"]["config"]
        assert config["runtime"] == "nemoclaw"

    def test_fresh_create_persists_sandbox_name(
        self, openclaw_install_env, monkeypatch
    ):
        _write_bare_host(openclaw_install_env, agents_block={})
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=_run_ansible_successfully(),
        ):
            run_installation("openclaw", "192.168.1.100", name="oc-nemo")

        config = json.loads((openclaw_install_env / "hosts.json").read_text())[0][
            "agents"
        ]["oc-nemo"]["config"]
        # Phase 2 default: sandbox_name is identity of agent_name.
        # Phase 3+ may namespace / hash — updates land in
        # `core.nemoclaw.default_sandbox_name` and this test.
        assert config["sandbox_name"] == "oc-nemo"

    def test_fresh_create_persists_nemoclaw_version(
        self, openclaw_install_env, monkeypatch
    ):
        _write_bare_host(openclaw_install_env, agents_block={})
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=_run_ansible_successfully(),
        ):
            run_installation("openclaw", "192.168.1.100", name="oc-nemo")

        config = json.loads((openclaw_install_env / "hosts.json").read_text())[0][
            "agents"
        ]["oc-nemo"]["config"]
        assert config["nemoclaw_version"] == NEMOCLAW_VERSION


class TestOpenclawCreateMigratesLegacyBareOnReinstall:
    """Phase 3 (issue #945): bare openclaw is gone. A re-install of a
    legacy bare record MUST stamp `runtime: "nemoclaw"` + `sandbox_name`
    + `nemoclaw_version` — the Phase 2 `__bare__` preserve branch was
    the non-regression carve-out; deleting it here is the breaking cut-
    over documented in `docs/releases/26.7.3/CHANGELOG.md`."""

    def test_reinstall_of_bare_openclaw_migrates_to_nemoclaw(
        self, openclaw_install_env, monkeypatch
    ):
        _write_bare_host(
            openclaw_install_env,
            agents_block={
                "legacy": {
                    "type": "openclaw",
                    "version": "0.1.0",
                    "status": "installed",
                    "installed_at": "2026-04-06T00:00:00+00:00",
                    "error": None,
                    "agent_name": "legacy",
                    "config": {"gateway": {"port": 40000}},
                }
            },
        )
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=_run_ansible_successfully(),
        ):
            run_installation("openclaw", "192.168.1.100", name="legacy")

        config = json.loads((openclaw_install_env / "hosts.json").read_text())[0][
            "agents"
        ]["legacy"]["config"]
        assert config["runtime"] == "nemoclaw"
        assert config["sandbox_name"] == "legacy"
        assert config["nemoclaw_version"] == NEMOCLAW_VERSION
