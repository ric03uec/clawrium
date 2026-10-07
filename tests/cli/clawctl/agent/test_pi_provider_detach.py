"""Pi final-provider detach commits metadata only after remote revocation."""

import json

import pytest
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
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"name": "router", "type": "openrouter", "default_model": "openai/gpt-4o"},
    )
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


def test_final_pi_codex_detach_revokes_only_native_auth_before_persisting(
    tmp_path, monkeypatch
):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"name": "router", "type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **kwargs: pytest.fail("OpenRouter credential must not be touched"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex",
        lambda **kwargs: calls.append(("revoke-codex", kwargs)),
    )

    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == "revoke-codex"
    assert calls[1] == "persist"
    assert load()["agents"]["pi-key"]["providers"] == []


def test_pi_codex_login_opens_tty_only_for_attached_dedicated_agent(monkeypatch):
    host = {
        "hostname": "wolf-i",
        "port": 22,
        "user": "xclm",
        "os_family": "linux",
        "agents": {
            "pi-key": {
                "type": "pi",
                "agent_name": "pi-dedicated",
                "providers": ["codex"],
            }
        },
    }
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi", host["agents"]["pi-key"]),
    )
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"name": "codex", "type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    calls = []
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda args, check: calls.append((args, check)) or type("R", (), {"returncode": 0})(),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", "codex", "--agent", "pi-test"]
    )

    assert result.exit_code == 0, result.output
    assert "/login" in result.output
    args, check = calls[0]
    assert check is False and args[:6] == ["ssh", "-tt", "-i", "/private/key", "-p", "22"]
    remote = args[-1]
    assert "-u pi-dedicated" in remote
    assert "--provider openai-codex --model gpt-5.1-codex-mini" in remote
    assert "unset OPENAI_API_KEY OPENROUTER_API_KEY" in remote


def test_final_pi_detach_revokes_before_persisting_attachment(tmp_path, monkeypatch):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **kwargs: calls.append(("revoke-openrouter", kwargs)),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex",
        lambda **kwargs: pytest.fail("Codex credential must not be touched"),
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "revoke-openrouter"
    assert calls[0][1]["agent_name"] == "pi-test"
    assert calls[0][1]["host"]["hostname"] == "wolf-i"
    assert calls[1] == "persist"
    assert load()["agents"]["pi-key"]["providers"] == []
    assert "detached provider 'router'" in result.output
