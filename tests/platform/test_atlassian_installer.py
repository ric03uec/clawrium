"""Hermes Atlassian sync-time launcher regression coverage (#1059)."""

from __future__ import annotations

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
def test_atlassian_runbook_gates_download_and_extraction_on_version_decision(
    name: str,
) -> None:
    """Missing/older launchers replace; equal/newer launchers skip both tasks."""
    tasks = _playbook(name)["tasks"]
    gated_tasks = [
        task
        for task in tasks
        if "ansible.builtin.get_url" in task or "ansible.builtin.unarchive" in task
    ]
    assert len(gated_tasks) == 2
    assert all(
        task["when"] == "mcp_atlassian_uv_needs_install | bool" for task in gated_tasks
    )


@pytest.mark.parametrize("name", _RUNBOOKS)
def test_atlassian_runbook_installs_verified_agent_owned_executable(name: str) -> None:
    """Assert the selected asset, checksum, archive target, and usable launcher."""
    playbook = _playbook(name)
    tasks = playbook["tasks"]
    home = (
        "/Users/{{ agent_name }}"
        if name.endswith("_macos.yaml")
        else "/home/{{ agent_name }}"
    )
    download = next(
        task["ansible.builtin.get_url"]
        for task in tasks
        if "ansible.builtin.get_url" in task
    )
    extract = next(
        task["ansible.builtin.unarchive"]
        for task in tasks
        if "ansible.builtin.unarchive" in task
    )
    final = next(
        task
        for task in tasks
        if task["name"].startswith("Assert uv launcher is executable")
    )

    assert (
        download["checksum"]
        == "sha256:{{ mcp_atlassian_uv_sha256_map[ansible_architecture] }}"
    )
    assert download["url"].endswith(
        "uv-{{ mcp_atlassian_uv_arch_map[ansible_architecture] }}.tar.gz"
    )
    assert extract["dest"] == f"{home}/.local/bin"
    assert extract["extra_opts"] == ["--strip-components=1"]
    assert final["ansible.builtin.file"] == {
        "path": f"{home}/.local/bin/uv",
        "mode": "0755",
        "state": "file",
    }
    assert final["become_user"] == "{{ agent_name }}"


@pytest.mark.parametrize("name", _RUNBOOKS)
def test_atlassian_runbook_rejects_symlink_before_agent_mode_repair(name: str) -> None:
    """No root task may follow an agent-controlled launcher symlink (#1059)."""
    tasks = _playbook(name)["tasks"]
    stat = next(task for task in tasks if "ansible.builtin.stat" in task)
    reject = next(task for task in tasks if "ansible.builtin.assert" in task)
    final = next(
        task
        for task in tasks
        if task["name"].startswith("Assert uv launcher is executable")
    )

    assert stat["ansible.builtin.stat"]["follow"] is False
    assert stat["register"] == "mcp_atlassian_uv_path"
    assert "islnk" in str(reject["ansible.builtin.assert"]["that"])
    assert "isreg" in str(reject["ansible.builtin.assert"]["that"])
    assert final["become_user"] == "{{ agent_name }}"
    assert "owner" not in final["ansible.builtin.file"]
    assert "group" not in final["ansible.builtin.file"]


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


class TestAtlassianCanonicalSync:
    """Exercise the real Hermes canonical-sync boundaries for #1059."""

    def _wire_pipeline(self, monkeypatch: pytest.MonkeyPatch, os_family: str):
        inputs = _inputs("atlassian")
        inputs.agent_type = "hermes"
        host = {"hostname": "host", "key_id": "host", "os_family": os_family}
        client = MagicMock()
        diff = SimpleNamespace(
            path=".hermes/config.yaml",
            remote_path="/home/alice/.hermes/config.yaml",
            rendered_body="model: {}\n",
            remote_body="",
            unified_diff="+model: {}",
        )
        order: list[str] = []
        writes = MagicMock(side_effect=lambda *_args, **_kwargs: order.append("write"))
        restart = MagicMock(
            side_effect=lambda *_args, **_kwargs: order.append("restart")
        )

        monkeypatch.setattr(
            lifecycle_canonical, "build_render_inputs", lambda _: inputs
        )
        monkeypatch.setitem(
            lifecycle_canonical._RENDERERS,
            "hermes",
            lambda *_args, **_kwargs: SimpleNamespace(
                files={diff.path: diff.rendered_body}
            ),
        )
        monkeypatch.setattr(
            lifecycle_canonical,
            "get_agent_by_name",
            lambda _: (host, "hermes", {"status": "installed", "installed_at": "now"}),
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
        monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_kwargs: [diff])
        monkeypatch.setattr(
            lifecycle_canonical, "_diff_removes_secrets", lambda _: set()
        )
        monkeypatch.setattr(
            "clawrium.core.agent_ssh_keys.ensure_agent_ssh_identity",
            lambda *_args: None,
        )
        monkeypatch.setattr(
            lifecycle_canonical,
            "_hermes_reconcile_herdr",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            lifecycle_canonical,
            "_hermes_install_slack_mcp",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            lifecycle_canonical,
            "_setup_github_integration",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(lifecycle_canonical, "_atomic_write", writes)
        monkeypatch.setattr(lifecycle_canonical, "_restart_unit", restart)
        monkeypatch.setattr(
            lifecycle_canonical, "_verify_health", lambda **_kwargs: None
        )
        return client, order, writes, restart

    @pytest.mark.parametrize(
        ("os_family", "playbook"),
        [
            ("linux", "install_atlassian_mcp.yaml"),
            ("darwin", "install_atlassian_mcp_macos.yaml"),
        ],
    )
    def test_canonical_sync_selects_runbook_before_write_and_restart(
        self, monkeypatch: pytest.MonkeyPatch, os_family: str, playbook: str
    ) -> None:
        """Resolver-selected installer runs with full runner args before mutation."""
        _client, order, _writes, _restart = self._wire_pipeline(monkeypatch, os_family)
        runner_calls: list[dict] = []

        def run_playbook(**kwargs):
            runner_calls.append(kwargs)
            order.append("install")
            return True, ""

        monkeypatch.setattr(
            "clawrium.core.lifecycle._run_lifecycle_playbook", run_playbook
        )

        lifecycle_canonical.sync_agent_canonical(
            "alice", verify=False, push_workspace=False
        )

        assert len(runner_calls) == 1
        runner_args = runner_calls[0]
        assert {
            key: value
            for key, value in runner_args.items()
            if key != "playbook_path_override"
        } == {
            "agent_type": "hermes",
            "agent_name": "alice",
            "hostname": "host",
            "operation": "install_atlassian_mcp",
            "host": {"hostname": "host", "key_id": "host", "os_family": os_family},
            "timeout": 180,
        }
        assert runner_args["playbook_path_override"].name == playbook
        assert order == ["install", "write", "restart"]

    @pytest.mark.parametrize("os_family", ["linux", "darwin"])
    def test_canonical_sync_install_failure_short_circuits_writes_and_restart(
        self, monkeypatch: pytest.MonkeyPatch, os_family: str
    ) -> None:
        """Both resolver paths propagate installer failure before host writes."""
        _client, order, writes, restart = self._wire_pipeline(monkeypatch, os_family)
        monkeypatch.setattr(
            "clawrium.core.lifecycle._run_lifecycle_playbook",
            lambda **_kwargs: (False, "download failed"),
        )

        with pytest.raises(
            CanonicalSyncError, match="Atlassian MCP launcher install failed"
        ):
            lifecycle_canonical.sync_agent_canonical(
                "alice", verify=False, push_workspace=False
            )

        writes.assert_not_called()
        restart.assert_not_called()
        assert order == []

    def test_dry_run_reports_atlassian_without_mutating_boundaries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dry-run reports the attachment but never invokes state-changing paths."""
        client, _order, writes, restart = self._wire_pipeline(monkeypatch, "linux")
        events: list[tuple[str, str]] = []
        runner = MagicMock(side_effect=AssertionError("runner invoked during dry-run"))
        credential = MagicMock(
            side_effect=AssertionError("credential path invoked during dry-run")
        )
        monkeypatch.setattr("clawrium.core.lifecycle._run_lifecycle_playbook", runner)
        monkeypatch.setattr(
            "clawrium.core.agent_ssh_keys.ensure_agent_ssh_identity", credential
        )
        herdr = MagicMock(
            side_effect=AssertionError("Herdr runner invoked during dry-run")
        )
        monkeypatch.setattr(lifecycle_canonical, "_hermes_reconcile_herdr", herdr)
        github = MagicMock(
            side_effect=AssertionError("credential writer invoked during dry-run")
        )
        monkeypatch.setattr(lifecycle_canonical, "_setup_github_integration", github)

        result = lifecycle_canonical.sync_agent_canonical(
            "alice",
            dry_run=True,
            on_event=lambda stage, message: events.append((stage, message)),
        )

        assert result.files_written == ()
        assert runner.call_count == 0
        assert credential.call_count == 0
        assert herdr.call_count == 0
        assert github.call_count == 0
        writes.assert_not_called()
        restart.assert_not_called()
        assert (
            client.close.call_count == 1
        )  # validation probe only; no write client opened
        assert (
            "atlassian_mcp_install",
            "would install uv launcher for alice",
        ) in events
