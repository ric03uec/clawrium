"""Pi final-provider detach commits metadata only after remote revocation."""

import json

import paramiko
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import provider as provider_mod
from clawrium.core.lifecycle_canonical import CanonicalSyncError

runner = CliRunner()


def _setup(tmp_path, monkeypatch, calls):
    """Use provider.py's real attachment reader/writer against a disk store."""
    path = tmp_path / "hosts.json"
    host = {
        "hostname": "wolf-i",
        "agents": {"pi-key": {"type": "pi", "providers": ["router"]}},
    }
    path.write_text(json.dumps([host]))

    def load():
        return json.loads(path.read_text())[0]

    def resolve(_):
        current = load()
        return current, "pi-key", current["agents"]["pi-key"]

    def persist(hostname, updater):
        current = load()
        assert hostname == "wolf-i"
        calls.append("persist")
        path.write_text(json.dumps([updater(current)]))
        return True

    monkeypatch.setattr(provider_mod, "safe_resolve_agent", resolve)
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(provider_mod, "update_host", persist)
    return load


def test_final_pi_detach_revocation_failure_keeps_persisted_attachment(
    tmp_path, monkeypatch
):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)

    def revoke(**kwargs):
        calls.append(("revoke", kwargs))
        raise CanonicalSyncError("remote revoke failed")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )
    assert result.exit_code != 0
    assert "failed to revoke Pi provider credential" in result.output
    assert calls == [
        (
            "revoke",
            {
                "agent_name": "pi-test",
                "host": {
                    "hostname": "wolf-i",
                    "agents": {"pi-key": {"type": "pi", "providers": ["router"]}},
                },
            },
        )
    ]
    assert load()["agents"]["pi-key"]["providers"] == ["router"]


def test_final_pi_detach_transport_failure_keeps_persisted_attachment(
    tmp_path, monkeypatch
):
    """Raw SSH failures must become the safe retryable detach outcome."""
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)

    def revoke(**kwargs):
        calls.append(("revoke", kwargs))
        raise paramiko.SSHException("connection reset")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )

    assert result.exit_code != 0
    assert (
        "failed to revoke Pi provider credential; detach did not finish"
        in result.output
    )
    assert (
        "retry: clawctl agent provider detach router --agent pi-test" in result.output
    )
    assert "connection reset" not in result.output
    assert calls[0][0] == "revoke"
    assert "persist" not in calls
    assert load()["agents"]["pi-key"]["providers"] == ["router"]


def test_final_pi_detach_revokes_before_persisting_attachment(tmp_path, monkeypatch):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **kwargs: calls.append(("revoke", kwargs)),
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "revoke"
    assert calls[0][1]["agent_name"] == "pi-test"
    assert calls[0][1]["host"]["hostname"] == "wolf-i"
    assert calls[1] == "persist"
    assert load()["agents"]["pi-key"]["providers"] == []
    assert "detached provider 'router'" in result.output
