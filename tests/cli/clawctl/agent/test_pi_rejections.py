"""Pi deferred-operation boundaries have no side effects."""

import json
from typer.testing import CliRunner
from clawrium.cli import app

runner = CliRunner()


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


def test_sync_help_discloses_pi_provider_and_sync_boundary():
    result = runner.invoke(app, ["agent", "sync", "--help"])
    assert result.exit_code == 0
    assert "Pi provider provisioning and sync are unsupported" in result.output


def test_pi_configure_and_sync_reject_before_lifecycle(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.core.lifecycle.configure_agent", boom)
    for cmd in (["agent", "configure", "pi-test"], ["agent", "sync", "pi-test"]):
        r = runner.invoke(app, cmd)
        assert r.exit_code != 0 and "not supported yet" in r.output


def test_pi_channel_and_integration_attach_reject_before_metadata_write(
    fleet_dir, monkeypatch
):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.channel._safe_get_channel", lambda _name: {}
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.channel.add_agent_channel", boom
    )
    channel = runner.invoke(
        app, ["agent", "channel", "attach", "discord", "--agent", "pi-test"]
    )
    assert channel.exit_code != 0 and "unavailable" in channel.output
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.channel.remove_agent_channel", boom
    )
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
    assert integration_detach.exit_code != 0 and "unavailable" in integration_detach.output


def test_pi_secret_mutations_reject_before_input_or_store_access(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.secret._read_from_file", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.secret.set_instance_secret", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.secret.remove_instance_secret", boom)
    create = runner.invoke(
        app, ["agent", "secret", "create", "KEY", "--agent", "pi-test", "--value", "x"]
    )
    imported = runner.invoke(
        app, ["agent", "secret", "import", "--agent", "pi-test", "--from-file", "/missing"]
    )
    deleted = runner.invoke(
        app, ["agent", "secret", "delete", "KEY", "--agent", "pi-test", "--yes"]
    )
    assert all(r.exit_code != 0 and "unavailable" in r.output for r in (create, imported, deleted))


def test_pi_skill_mutations_reject_before_input_editor_or_state_access(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.skill._resolve_add_input", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.skill._run_editor", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.skill.remove_skill", boom)
    added = runner.invoke(app, ["agent", "skill", "add", "pi-test", "--from-template", "clawrium/tdd"])
    edited = runner.invoke(app, ["agent", "skill", "edit", "pi-test", "tdd"])
    removed = runner.invoke(app, ["agent", "skill", "remove", "pi-test", "tdd"])
    assert all(r.exit_code != 0 and "unavailable" in r.output for r in (added, edited, removed))


def test_pi_provider_attach_rejects_before_metadata_write(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._safe_get_provider",
        lambda _name: {"type": "openrouter"},
    )
    monkeypatch.setattr("clawrium.cli.clawctl.agent.provider._get_attachments", boom)
    r = runner.invoke(
        app, ["agent", "provider", "attach", "router", "--agent", "pi-test"]
    )
    assert r.exit_code != 0 and "not supported for pi" in r.output


def test_pi_upgrade_rejects_before_install(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.core.install.run_installation", boom)
    result = runner.invoke(app, ["agent", "upgrade", "pi-test", "--yes"])
    assert result.exit_code != 0 and "install-only" in result.output


def test_pi_chat_and_shell_reject_before_remote_backend(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.cli.chat.chat", boom)
    monkeypatch.setattr("clawrium.cli.clawctl.agent.shell.run_agent_shell", boom)
    chat = runner.invoke(app, ["agent", "chat", "pi-test", "--once", "hello"])
    shell = runner.invoke(app, ["agent", "shell", "pi-test", "--", "true"])
    assert chat.exit_code != 0 and "install-only" in chat.output
    assert shell.exit_code != 0 and "install-only" in shell.output


def test_pi_port_forward_rejects_before_tunnel(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    monkeypatch.setattr("clawrium.core.web_ui_tunnel.ensure", boom)
    r = runner.invoke(app, ["agent", "port-forward", "pi-test", "22"])
    assert r.exit_code != 0 and "no native listener" in r.output
