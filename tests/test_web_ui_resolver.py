"""Tests for the `clawrium.core.web_ui` resolver (issue #481).

These tests cover Phase 1 mechanism only: the resolver returns
`ResolvedUI` when the manifest declares `features.web_ui` and `None`
otherwise. URL construction, tunnel spawning, and live health checks
live in later phases.
"""

from clawrium.core import web_ui as web_ui_module
from clawrium.core.web_ui import ResolvedUI, resolve


def _host(hostname: str = "hermes-box", user: str = "xclm") -> dict:
    return {
        "hostname": hostname,
        "user": user,
        "addresses": [
            {"address": hostname, "is_primary": True, "label": None},
        ],
    }


def _patch_agent(monkeypatch, host: dict, agent_type: str, agent_record: dict) -> None:
    monkeypatch.setattr(
        web_ui_module,
        "get_agent_by_name",
        lambda _key: (host, agent_type, agent_record),
    )


def test_resolve_hermes_returns_default_port(monkeypatch):
    """A hermes agent with no persisted dashboard port resolves to the manifest default."""
    _patch_agent(
        monkeypatch,
        host=_host("hermes.local"),
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )

    resolved = resolve("demo")

    assert isinstance(resolved, ResolvedUI)
    assert resolved.host == "hermes.local"
    assert resolved.remote_port == 9119
    assert resolved.bind == "loopback"
    assert resolved.ssh_config.get("user") == "xclm"


def test_resolve_hermes_uses_persisted_port(monkeypatch):
    """When `config.dashboard.port` is persisted, the resolver returns it."""
    agent_record = {
        "agent_name": "demo",
        "type": "hermes",
        "config": {"dashboard": {"port": 45123, "host": "127.0.0.1"}},
    }
    _patch_agent(monkeypatch, host=_host(), agent_type="hermes", agent_record=agent_record)

    resolved = resolve("demo")
    assert resolved is not None
    assert resolved.remote_port == 45123


def test_resolve_openclaw_returns_none(monkeypatch):
    """openclaw's manifest does not declare `features.web_ui`."""
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="openclaw",
        agent_record={"agent_name": "oc", "type": "openclaw", "config": {}},
    )
    assert resolve("oc") is None


def test_resolve_zeroclaw_returns_none(monkeypatch):
    """zeroclaw's manifest does not declare `features.web_ui`."""
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="zeroclaw",
        agent_record={"agent_name": "zc", "type": "zeroclaw", "config": {}},
    )
    assert resolve("zc") is None


def test_resolve_missing_agent_returns_none(monkeypatch):
    """Unknown agent name → `None` (caller decides how to surface)."""
    monkeypatch.setattr(web_ui_module, "get_agent_by_name", lambda _key: None)
    assert resolve("ghost") is None


def test_resolve_ambiguous_agent_returns_none(monkeypatch):
    """Ambiguous name (matches multiple hosts) → swallowed to `None`.

    `clm chat` and similar surfaces raise an interactive prompt for this
    case; the resolver returns `None` so the caller can render a static
    "Native UI not available" rather than a stack trace.
    """

    def raise_ambiguous(_key):
        raise ValueError("ambiguous across hosts")

    monkeypatch.setattr(web_ui_module, "get_agent_by_name", raise_ambiguous)
    assert resolve("dupe") is None


def test_resolve_empty_agent_key_returns_none():
    assert resolve("") is None
    assert resolve("   ") is None


def test_resolve_uses_primary_address_when_distinct_from_hostname(monkeypatch):
    """When the host has a distinct primary address, the resolver returns it."""
    host = {
        "hostname": "alias",
        "user": "ops",
        "addresses": [
            {"address": "10.0.0.5", "is_primary": True, "label": None},
            {"address": "alias", "is_primary": False, "label": None},
        ],
    }
    _patch_agent(
        monkeypatch,
        host=host,
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )

    resolved = resolve("demo")
    assert resolved is not None
    assert resolved.host == "10.0.0.5"
    assert resolved.ssh_config.get("user") == "ops"


def test_resolve_falls_back_to_default_port_for_invalid_persisted(monkeypatch):
    """A non-int (or out-of-range) persisted port is ignored; default wins."""
    agent_record = {
        "agent_name": "demo",
        "type": "hermes",
        "config": {"dashboard": {"port": "not-a-port"}},
    }
    _patch_agent(monkeypatch, host=_host(), agent_type="hermes", agent_record=agent_record)

    resolved = resolve("demo")
    assert resolved is not None
    assert resolved.remote_port == 9119


def test_resolve_handles_unknown_agent_type(monkeypatch):
    """If the agent record references an unknown type, return `None` instead of crashing."""
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="nosuch",
        agent_record={"agent_name": "x", "type": "nosuch", "config": {}},
    )
    assert resolve("x") is None


def test_resolve_returns_none_when_enabled_false(monkeypatch):
    """`features.web_ui.enabled: false` should be treated as "no UI"."""
    # Sanity check that the resolver depends on enabled=True. Mock the manifest
    # to flip `enabled` off.
    manifest = {
        "agent": {"type": "hermes", "description": "test"},
        "platforms": [],
        "features": {
            "web_ui": {
                "enabled": False,
                "bind": "loopback",
                "default_port": 9119,
                "port_field": "dashboard.port",
            }
        },
    }
    monkeypatch.setattr(web_ui_module, "load_manifest", lambda _t: manifest)
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )
    assert resolve("demo") is None
