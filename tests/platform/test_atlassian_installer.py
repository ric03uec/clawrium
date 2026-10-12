"""Hermes Atlassian sync-time launcher regression coverage (#1059)."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from clawrium.core import lifecycle_canonical
from clawrium.core.lifecycle_canonical import CanonicalSyncError
from clawrium.core.render import _HERMES_MCP_ATLASSIAN_VERSION


_ROOT = Path(__file__).parents[2]
_PLAYBOOKS = _ROOT / "src/clawrium/platform/registry/hermes/playbooks"
_RUNBOOKS = ("install_atlassian_mcp.yaml", "install_atlassian_mcp_macos.yaml")


def _playbook(name: str) -> dict:
    return yaml.safe_load((_PLAYBOOKS / name).read_text())[0]


@pytest.mark.parametrize("name", _RUNBOOKS)
def test_atlassian_runbook_pin_matches_renderer(name: str) -> None:
    """Rule 8: assert the render pin directly against each runbook."""
    assert (
        _playbook(name)["vars"]["mcp_atlassian_version"]
        == _HERMES_MCP_ATLASSIAN_VERSION
    )


@pytest.mark.parametrize("name", _RUNBOOKS)
def test_atlassian_runbook_maps_are_checksum_complete(name: str) -> None:
    vars_ = _playbook(name)["vars"]
    assert set(vars_["mcp_atlassian_uv_arch_map"]) == set(
        vars_["mcp_atlassian_uv_sha256_map"]
    )
    assert vars_["mcp_atlassian_uv_version"] == "0.13.0"


@pytest.mark.parametrize("name", _RUNBOOKS)
def test_atlassian_runbook_preserves_newer_uv(name: str) -> None:
    tasks = _playbook(name)["tasks"]
    install_fact = next(
        task["ansible.builtin.set_fact"]["mcp_atlassian_uv_needs_install"]
        for task in tasks
        if "mcp_atlassian_uv_needs_install" in task.get("ansible.builtin.set_fact", {})
    )
    assert "is version(mcp_atlassian_uv_version, '<')" in install_fact
    assert "uvx" not in (_PLAYBOOKS / name).read_text()


@pytest.mark.parametrize("name", _RUNBOOKS)
def test_atlassian_runbook_has_task_zero_dispatch_guard(name: str) -> None:
    task = _playbook(name)["tasks"][0]
    assert "ansible.builtin.fail" in task
    assert "ansible_os_family" in str(task.get("when"))


def _inputs(*types: str) -> SimpleNamespace:
    return SimpleNamespace(
        integrations=tuple(
            SimpleNamespace(type=integration_type) for integration_type in types
        )
    )


def test_atlassian_installer_gate_dispatches_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook",
        lambda **kwargs: calls.append(kwargs) or (True, ""),
    )
    lifecycle_canonical._hermes_install_atlassian_mcp(
        "alice", "host", {"os_family": "linux"}, _inputs("atlassian")
    )
    assert calls[0]["operation"] == "install_atlassian_mcp"
    assert calls[0]["playbook_path_override"].name == "install_atlassian_mcp.yaml"


def test_atlassian_installer_gate_skips_unattached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook",
        lambda **_kwargs: pytest.fail("unattached integration must not invoke ansible"),
    )
    lifecycle_canonical._hermes_install_atlassian_mcp(
        "alice", "host", {}, _inputs("github")
    )


def test_atlassian_installer_dispatches_macos_and_short_circuits_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook",
        lambda **kwargs: calls.append(kwargs) or (False, "download failed"),
    )
    with pytest.raises(
        CanonicalSyncError, match="Atlassian MCP launcher install failed"
    ):
        lifecycle_canonical._hermes_install_atlassian_mcp(
            "alice", "host", {"os_family": "darwin"}, _inputs("atlassian")
        )
    assert calls[0]["playbook_path_override"].name == "install_atlassian_mcp_macos.yaml"


def test_atlassian_installer_dry_run_never_invokes_ansible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook",
        lambda **_kwargs: pytest.fail("dry run must not invoke Ansible"),
    )
    lifecycle_canonical._hermes_install_atlassian_mcp(
        "alice", "host", {}, _inputs("atlassian"), dry_run=True
    )


def test_atlassian_installer_runs_before_canonical_writes_and_restart() -> None:
    """A failed install must not write config or restart Hermes."""
    source = inspect.getsource(lifecycle_canonical.sync_agent_canonical)
    install = source.index("_hermes_install_atlassian_mcp(")
    write = source.index("for d in diffs:", install)
    restart = source.index("_restart_unit(", write)
    assert install < write < restart


def test_atlassian_install_failure_short_circuits_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real pipeline: no canonical write or restart after failure."""
    inputs = _inputs("atlassian")
    inputs.agent_type = "hermes"
    client = MagicMock()
    client.close = MagicMock()
    writes = MagicMock()
    restart = MagicMock()

    monkeypatch.setattr(
        lifecycle_canonical, "build_render_inputs", lambda _name: inputs
    )
    monkeypatch.setitem(
        lifecycle_canonical._RENDERERS,
        "hermes",
        lambda *_args, **_kwargs: SimpleNamespace(files={}),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _name: (
            {"hostname": "host", "key_id": "host", "os_family": "linux"},
            "alice",
            {"type": "hermes"},
        ),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "probe_host_install",
        lambda *_args, **_kwargs: lifecycle_canonical.HostInstallProbe(
            unit_present=True,
            home_present=True,
            unit_path="/etc/systemd/system/hermes-alice.service",
            home_path="/home/alice/.hermes",
        ),
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_open_ssh", lambda *_args, **_kwargs: client
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_kwargs: [])
    monkeypatch.setattr(
        lifecycle_canonical, "_hermes_reconcile_herdr", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_hermes_install_atlassian_mcp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CanonicalSyncError("download failed")
        ),
    )
    monkeypatch.setattr(lifecycle_canonical, "_atomic_write", writes)
    monkeypatch.setattr(lifecycle_canonical, "_restart_unit", restart)

    with pytest.raises(CanonicalSyncError, match="download failed"):
        lifecycle_canonical.sync_agent_canonical("alice")

    writes.assert_not_called()
    restart.assert_not_called()
