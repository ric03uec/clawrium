"""Pi deferred-operation boundaries have no side effects."""

import json

import pytest
from typer.testing import CliRunner
from clawrium.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_pi_configure_revoke(monkeypatch):
    """Failure-path configure tests model successful remote compensation."""
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", lambda **_kwargs: None
    )


def add_pi(fleet_dir):
    p = fleet_dir / "hosts.json"
    d = json.loads(p.read_text())
    d[0]["agents"]["pi-test"] = {
        "type": "pi",
        "agent_name": "pi-test",
        "version": "0.73.1",
        "status": "installed",
        "installed_at": "2026-10-06T00:00:00+00:00",
    }
    p.write_text(json.dumps(d))


def boom(*a, **k):
    raise AssertionError("downstream called")


def test_pi_create_provider_rejected_before_install(fleet_dir, monkeypatch):
    monkeypatch.setattr("clawrium.cli.clawctl.agent.create.run_installation", boom)
    r = runner.invoke(
        app,
        [
            "agent",
            "create",
            "pi-new",
            "--type",
            "pi",
            "--host",
            "10.0.0.1",
            "--provider",
            "x",
            "--yes",
        ],
    )
    assert r.exit_code != 0 and "not supported for pi" in r.output


def test_pi_configure_requires_explicit_openrouter_selection(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.core.lifecycle.configure_agent", boom)
    result = runner.invoke(app, ["agent", "configure", "pi-test"])
    assert result.exit_code != 0
    assert "requires --stage providers --provider" in result.output


def test_pi_configure_attaches_openrouter_then_canonical_syncs(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _name: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    calls = []
    from clawrium.core.lifecycle_canonical import CanonicalSyncResult

    def sync(agent_name, **kwargs):
        calls.append((agent_name, kwargs))
        return CanonicalSyncResult(True, agent_name, "host", (), (), ())

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        ("pi-test", {"restart": False, "verify": False, "push_workspace": False})
    ]


def test_pi_configure_surfaces_canonical_sync_failure(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _name: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    from clawrium.core.lifecycle_canonical import CanonicalSyncResult

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: CanonicalSyncResult(
            False, "pi-test", "host", (), (), (), error="denied"
        ),
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert result.exit_code != 0
    assert "Pi provider configuration failed: denied" in result.output
    assert (
        json.loads((fleet_dir / "hosts.json").read_text())[0]["agents"]["pi-test"].get(
            "providers", []
        )
        == []
    )


def test_pi_configure_rolls_back_attachment_when_sync_raises(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_a, **_kw: (_ for _ in ()).throw(CanonicalSyncError("remote failed")),
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert result.exit_code != 0 and "remote failed" in result.output
    assert (
        json.loads((fleet_dir / "hosts.json").read_text())[0]["agents"]["pi-test"].get(
            "providers", []
        )
        == []
    )


def test_pi_configure_reports_compensation_write_failure(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    from clawrium.core.hosts import update_host as real_update
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    calls = 0

    def update_once_then_fail(hostname, updater):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk unavailable")
        return real_update(hostname, updater)

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.update_host", update_once_then_fail
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_a, **_kw: (_ for _ in ()).throw(CanonicalSyncError("remote failed")),
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert result.exit_code != 0
    assert (
        "remote failed" in result.output
        and "rollback also failed (OSError)" in result.output
    )
    assert "Manually detach" in result.output
    assert "OPENROUTER_API_KEY" not in result.output


def test_pi_configure_post_write_failure_revokes_before_disk_rollback(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    remote = {"credential": False}
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    def sync(*_args, **_kwargs):
        remote["credential"] = True
        raise CanonicalSyncError("post-write failed")

    def revoke(**_kwargs):
        assert remote["credential"]
        remote["credential"] = False

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert result.exit_code != 0 and remote["credential"] is False
    assert (
        json.loads((fleet_dir / "hosts.json").read_text())[0]["agents"]["pi-test"].get(
            "providers", []
        )
        == []
    )


def test_pi_configure_failed_revoke_retains_attachment(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            CanonicalSyncError("post-write failed")
        ),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **_kw: (_ for _ in ()).throw(CanonicalSyncError("revoke failed")),
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert (
        result.exit_code != 0
        and "post-write failed" in result.output
        and "revoke failed" in result.output
        and "manually detach" in result.output.lower()
    )
    assert json.loads((fleet_dir / "hosts.json").read_text())[0]["agents"]["pi-test"][
        "providers"
    ] == ["router"]


def test_pi_reconfigure_failure_retains_new_attachment_for_recovery(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    data = json.loads((fleet_dir / "hosts.json").read_text())
    data[0]["agents"]["pi-test"]["providers"] = ["old-router"]
    (fleet_dir / "hosts.json").write_text(json.dumps(data))
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            CanonicalSyncError("post-write failed")
        ),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **_kw: pytest.fail("must retain recoverable attachment"),
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )
    assert result.exit_code != 0 and "retained for recovery" in result.output
    assert json.loads((fleet_dir / "hosts.json").read_text())[0]["agents"]["pi-test"][
        "providers"
    ] == ["router"]


def test_pi_sync_invokes_canonical_and_surfaces_failures(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    from clawrium.core.lifecycle_canonical import (
        CanonicalSyncError,
        CanonicalSyncResult,
    )

    calls = []
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *a, **kw: (
            calls.append((a, kw))
            or CanonicalSyncResult(True, "pi-test", "host", (), (), ())
        ),
    )
    ok = runner.invoke(app, ["agent", "sync", "pi-test"])
    assert ok.exit_code == 0 and calls[0][0] == ("pi-test",)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *a, **kw: CanonicalSyncResult(
            False, "pi-test", "host", (), (), (), error="denied"
        ),
    )
    failed = runner.invoke(app, ["agent", "sync", "pi-test"])
    assert failed.exit_code != 0 and "Pi sync failed: denied" in failed.output
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *a, **kw: (_ for _ in ()).throw(CanonicalSyncError("boom")),
    )
    raised = runner.invoke(app, ["agent", "sync", "pi-test"])
    assert raised.exit_code != 0 and "Pi sync failed: boom" in raised.output


def test_pi_channel_and_integration_attach_reject_before_metadata_write(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.channel._safe_get_channel", lambda _name: {}
    )
    monkeypatch.setattr("clawrium.cli.clawctl.agent.channel.add_agent_channel", boom)
    channel = runner.invoke(
        app, ["agent", "channel", "attach", "discord", "--agent", "pi-test"]
    )
    assert channel.exit_code != 0 and "unavailable" in channel.output
    monkeypatch.setattr("clawrium.cli.clawctl.agent.channel.remove_agent_channel", boom)
    channel_detach = runner.invoke(
        app, ["agent", "channel", "detach", "discord", "--agent", "pi-test"]
    )
    assert channel_detach.exit_code != 0 and "unavailable" in channel_detach.output

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.integration._safe_get_integration",
        lambda _name: {"type": "github"},
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.integration.add_agent_integration", boom
    )
    integration = runner.invoke(
        app, ["agent", "integration", "attach", "github", "--agent", "pi-test"]
    )
    assert integration.exit_code != 0 and "unavailable" in integration.output
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.integration.remove_agent_integration", boom
    )
    integration_detach = runner.invoke(
        app, ["agent", "integration", "detach", "github", "--agent", "pi-test"]
    )
    assert (
        integration_detach.exit_code != 0 and "unavailable" in integration_detach.output
    )


def test_pi_secret_mutations_reject_before_input_or_store_access(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.secret._read_from_file", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.secret.set_instance_secret", boom)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.secret.remove_instance_secret", boom
    )
    create = runner.invoke(
        app, ["agent", "secret", "create", "KEY", "--agent", "pi-test", "--value", "x"]
    )
    imported = runner.invoke(
        app,
        ["agent", "secret", "import", "--agent", "pi-test", "--from-file", "/missing"],
    )
    deleted = runner.invoke(
        app, ["agent", "secret", "delete", "KEY", "--agent", "pi-test", "--yes"]
    )
    assert all(
        r.exit_code != 0 and "unavailable" in r.output
        for r in (create, imported, deleted)
    )


def test_pi_skill_mutations_reject_before_input_editor_or_state_access(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.skill._resolve_add_input", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.skill._run_editor", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.skill.remove_skill", boom)
    added = runner.invoke(
        app, ["agent", "skill", "add", "pi-test", "--from-template", "clawrium/tdd"]
    )
    edited = runner.invoke(app, ["agent", "skill", "edit", "pi-test", "tdd"])
    removed = runner.invoke(app, ["agent", "skill", "remove", "pi-test", "tdd"])
    assert all(
        r.exit_code != 0 and "unavailable" in r.output for r in (added, edited, removed)
    )


def test_pi_provider_attach_rejects_missing_or_unsupported_model_before_metadata_write(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._safe_get_provider",
        lambda _name: {"type": "openrouter"},
    )
    monkeypatch.setattr("clawrium.cli.clawctl.agent.provider._get_attachments", boom)
    r = runner.invoke(
        app, ["agent", "provider", "attach", "router", "--agent", "pi-test"]
    )
    assert r.exit_code != 0 and "supported OpenRouter default_model" in r.output


def test_pi_upgrade_rejects_before_install(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.core.install.run_installation", boom)
    result = runner.invoke(app, ["agent", "upgrade", "pi-test", "--yes"])
    assert result.exit_code != 0 and "install-only" in result.output


def test_pi_shell_remains_rejected_before_remote_backend(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.shell.run_agent_shell", boom)
    shell = runner.invoke(app, ["agent", "shell", "pi-test", "--", "true"])
    assert shell.exit_code != 0 and "install-only" in shell.output


def test_pi_port_forward_rejects_before_tunnel(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.core.web_ui_tunnel.ensure", boom)
    r = runner.invoke(app, ["agent", "port-forward", "pi-test", "22"])
    assert r.exit_code != 0 and "no native listener" in r.output
