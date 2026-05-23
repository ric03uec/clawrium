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


def test_resolve_hermes_without_persisted_port_returns_none(monkeypatch, caplog):
    """A hermes agent without persisted `dashboard.port` resolves to None.

    Issue #491: the hermes manifest no longer carries a `default_port`
    fallback (install.py computes a per-instance port in 45000..46999
    and persists it). When the persisted value is missing the resolver
    must surface "no UI available" rather than inventing a port that
    would land us on whichever instance happened to bind 9119.
    """
    _patch_agent(
        monkeypatch,
        host=_host("hermes.local"),
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )

    with caplog.at_level("WARNING", logger="clawrium.core.web_ui"):
        assert resolve("demo") is None
    assert any("dashboard.port" in rec.message for rec in caplog.records)


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


def test_resolve_zeroclaw_returns_gateway_port(monkeypatch):
    """zeroclaw resolves to its persisted `gateway.port` (mirror of #478)."""
    agent_record = {
        "agent_name": "zc",
        "type": "zeroclaw",
        "config": {"gateway": {"port": 40123}},
    }
    _patch_agent(
        monkeypatch,
        host=_host("zero.local"),
        agent_type="zeroclaw",
        agent_record=agent_record,
    )

    resolved = resolve("zc")

    assert isinstance(resolved, ResolvedUI)
    assert resolved.host == "zero.local"
    assert resolved.remote_port == 40123
    assert resolved.bind == "wildcard"


def test_resolve_zeroclaw_without_persisted_port_returns_none(monkeypatch, caplog):
    """zeroclaw without persisted `gateway.port` resolves to None (#491).

    Same rationale as the hermes test above: zeroclaw computes a
    per-instance port at install time, so inventing a default would
    silently serve a different instance's UI.
    """
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="zeroclaw",
        agent_record={"agent_name": "zc", "type": "zeroclaw", "config": {}},
    )
    with caplog.at_level("WARNING", logger="clawrium.core.web_ui"):
        assert resolve("zc") is None
    assert any("gateway.port" in rec.message for rec in caplog.records)


def test_resolve_missing_agent_returns_none(monkeypatch):
    """Unknown agent name → `None` (caller decides how to surface)."""
    monkeypatch.setattr(web_ui_module, "get_agent_by_name", lambda _key: None)
    assert resolve("ghost") is None


def test_resolve_ambiguous_agent_returns_none(monkeypatch, caplog):
    """Ambiguous name (matches multiple hosts) → `None` and a WARNING log.

    `clm chat` and similar surfaces raise an interactive prompt for this
    case; the resolver returns `None` so the caller can render a static
    "Native UI not available" rather than a stack trace. The log surfaces
    the disambiguation hint to operators.
    """

    def raise_ambiguous(_key):
        raise ValueError("ambiguous across hosts: demo@hostA, demo@hostB")

    monkeypatch.setattr(web_ui_module, "get_agent_by_name", raise_ambiguous)
    with caplog.at_level("WARNING", logger="clawrium.core.web_ui"):
        assert resolve("dupe") is None
    assert any("ambiguous" in rec.message for rec in caplog.records)


def test_resolve_returns_none_on_invalid_agent_type(monkeypatch):
    """A tampered hosts.json with a path-traversal `type` value yields `None`."""
    from clawrium.core.registry import InvalidAgentTypeError

    def boom(_t):
        raise InvalidAgentTypeError("path traversal in agent type")

    monkeypatch.setattr(web_ui_module, "load_manifest", boom)
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="../evil",
        agent_record={"agent_name": "demo", "type": "../evil", "config": {}},
    )
    assert resolve("demo") is None


def test_resolve_logs_warning_on_manifest_parse_error(monkeypatch, caplog):
    """A corrupt manifest is operator-actionable → logged at WARNING."""
    from clawrium.core.registry import ManifestParseError

    def boom(_t):
        raise ManifestParseError("corrupt manifest bytes")

    monkeypatch.setattr(web_ui_module, "load_manifest", boom)
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )
    with caplog.at_level("WARNING", logger="clawrium.core.web_ui"):
        assert resolve("demo") is None
    assert any("corrupted" in rec.message for rec in caplog.records)


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
        agent_record={
            "agent_name": "demo",
            "type": "hermes",
            "config": {"dashboard": {"port": 45123}},
        },
    )

    resolved = resolve("demo")
    assert resolved is not None
    assert resolved.host == "10.0.0.5"
    assert resolved.ssh_config.get("user") == "ops"


def test_resolve_returns_none_for_invalid_persisted_when_no_default(monkeypatch, caplog):
    """A non-int (or out-of-range) persisted port with no `default_port`
    in the manifest → None (#491).

    Previously the resolver fell back to `default_port`. Now that the
    bundled hermes/zeroclaw manifests no longer carry a default (a
    manifest-wide default would collide for hosts running multiple
    instances), an invalid persisted port must surface as "no UI".
    """
    agent_record = {
        "agent_name": "demo",
        "type": "hermes",
        "config": {"dashboard": {"port": "not-a-port"}},
    }
    _patch_agent(monkeypatch, host=_host(), agent_type="hermes", agent_record=agent_record)

    with caplog.at_level("WARNING", logger="clawrium.core.web_ui"):
        assert resolve("demo") is None
    assert any("dashboard.port" in rec.message for rec in caplog.records)


def test_resolve_uses_manifest_default_when_present(monkeypatch):
    """If a manifest *does* declare `default_port`, the resolver still
    honors it (back-compat for third-party manifests that opt in).

    The bundled hermes/zeroclaw manifests omit `default_port` post-#491
    on purpose, but the schema still accepts it. Lock in the fallback
    path against a mocked manifest so the behaviour doesn't regress for
    out-of-tree consumers.
    """
    manifest = {
        "agent": {"type": "third-party", "description": "t"},
        "platforms": [],
        "features": {
            "web_ui": {
                "enabled": True,
                "bind": "loopback",
                "default_port": 8080,
                "port_field": "dashboard.port",
            }
        },
    }
    monkeypatch.setattr(web_ui_module, "load_manifest", lambda _t: manifest)
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="third-party",
        agent_record={"agent_name": "tp", "type": "third-party", "config": {}},
    )

    resolved = resolve("tp")
    assert resolved is not None
    assert resolved.remote_port == 8080


def test_resolve_handles_unknown_agent_type(monkeypatch):
    """If the agent record references an unknown type, return `None` instead of crashing."""
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="nosuch",
        agent_record={"agent_name": "x", "type": "nosuch", "config": {}},
    )
    assert resolve("x") is None


def test_resolve_returns_none_for_host_without_address(monkeypatch):
    """A host with no primary address and no `hostname` must yield `None`.

    Otherwise the resolver would silently produce `ResolvedUI(host="")`,
    a truthy non-None object that would feed an empty positional arg to
    `ssh` in Phase 2.
    """
    host_record = {"user": "ops", "addresses": []}
    _patch_agent(
        monkeypatch,
        host=host_record,
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )
    assert resolve("demo") is None


def test_resolve_ssh_config_resolves_identity_via_key_id(monkeypatch, tmp_path):
    """ssh_config.identity_file is resolved via get_host_private_key(key_id).

    Real clm host records store `key_id` (e.g. "wolf-i") and the private
    key lives under ~/.config/clawrium/keys/<key_id>/xclm_ed25519. The
    resolver MUST go through `get_host_private_key`, not look at an
    inline `ssh_key` / `identity_file` field that does not exist in real
    records. Regression anchor for the bug that caused
    `Permission denied (publickey)` when the GUI / `clm agent open`
    tried to tunnel to a hermes dashboard.
    """
    key_file = tmp_path / "xclm_ed25519"
    key_file.write_text("fake-private-key")

    calls = []

    def fake_lookup(kid):
        calls.append(kid)
        return key_file if kid == "wolf-i" else None

    monkeypatch.setattr(web_ui_module, "get_host_private_key", fake_lookup)

    host_record = {
        "hostname": "wolf.tailf7742d.ts.net",
        "user": "xclm",
        "port": 22,
        "key_id": "wolf-i",
        "auth_method": "key",
        "addresses": [
            {"address": "wolf.tailf7742d.ts.net", "is_primary": True, "label": None}
        ],
    }
    _patch_agent(
        monkeypatch,
        host=host_record,
        agent_type="hermes",
        agent_record={
            "agent_name": "demo",
            "type": "hermes",
            "config": {"dashboard": {"port": 45123}},
        },
    )

    resolved = resolve("demo")
    assert resolved is not None
    assert resolved.ssh_config == {
        "user": "xclm",
        "port": 22,
        "identity_file": str(key_file),
    }
    assert calls == ["wolf-i"]


def test_resolve_ssh_config_falls_back_to_hostname_when_key_id_missing(
    monkeypatch, tmp_path
):
    """Legacy host records without `key_id` fall back to looking up by hostname.

    Matches the established `key_id = host.get("key_id") or hostname`
    fallback at skills_apply.py:392 and lifecycle.py:296.
    """
    key_file = tmp_path / "xclm_ed25519"
    key_file.write_text("fake")

    calls = []

    def fake_lookup(kid):
        calls.append(kid)
        return key_file if kid == "legacy-host" else None

    monkeypatch.setattr(web_ui_module, "get_host_private_key", fake_lookup)

    host_record = {
        "hostname": "legacy-host",
        "user": "xclm",
        "port": 22,
        "addresses": [{"address": "legacy-host", "is_primary": True, "label": None}],
    }
    _patch_agent(
        monkeypatch,
        host=host_record,
        agent_type="hermes",
        agent_record={
            "agent_name": "demo",
            "type": "hermes",
            "config": {"dashboard": {"port": 45123}},
        },
    )

    resolved = resolve("demo")
    assert resolved is not None
    assert resolved.ssh_config.get("identity_file") == str(key_file)
    assert calls == ["legacy-host"]


def test_resolve_ssh_config_omits_identity_when_key_missing(monkeypatch):
    """When no private key is found for the host, identity_file is absent.

    The rest of ssh_config (user, port) must still be populated so the
    caller can surface a meaningful diagnostic ("no key for host X") and
    so unrelated tunnel-spawning code can still run.
    """
    monkeypatch.setattr(web_ui_module, "get_host_private_key", lambda _kid: None)

    host_record = {
        "hostname": "wolf.tailf7742d.ts.net",
        "user": "xclm",
        "port": 22,
        "key_id": "wolf-i",
        "addresses": [
            {"address": "wolf.tailf7742d.ts.net", "is_primary": True, "label": None}
        ],
    }
    _patch_agent(
        monkeypatch,
        host=host_record,
        agent_type="hermes",
        agent_record={
            "agent_name": "demo",
            "type": "hermes",
            "config": {"dashboard": {"port": 45123}},
        },
    )

    resolved = resolve("demo")
    assert resolved is not None
    assert "identity_file" not in resolved.ssh_config
    assert resolved.ssh_config.get("user") == "xclm"
    assert resolved.ssh_config.get("port") == 22


def test_resolve_ssh_config_drops_identity_with_shell_metachars_in_resolved_path(
    monkeypatch, tmp_path
):
    """A resolved key path containing shell metachars / newlines is dropped.

    Defense in depth: even though `get_host_private_key` only ever
    returns paths under `~/.config/clawrium/keys/`, a malicious or
    corrupted directory layout could in principle yield a path with a
    newline. `_safe_identity_file` must reject it.
    """
    from pathlib import Path

    bad_path = Path(str(tmp_path) + "/key\nmalicious")
    monkeypatch.setattr(
        web_ui_module, "get_host_private_key", lambda _kid: bad_path
    )

    host_record = {
        "hostname": "wolf.tailf7742d.ts.net",
        "user": "xclm",
        "port": 22,
        "key_id": "wolf-i",
        "addresses": [
            {"address": "wolf.tailf7742d.ts.net", "is_primary": True, "label": None}
        ],
    }
    _patch_agent(
        monkeypatch,
        host=host_record,
        agent_type="hermes",
        agent_record={
            "agent_name": "demo",
            "type": "hermes",
            "config": {"dashboard": {"port": 45123}},
        },
    )

    resolved = resolve("demo")
    assert resolved is not None
    assert "identity_file" not in resolved.ssh_config


def test_resolve_returns_none_on_manifest_parse_error(monkeypatch):
    """A `ManifestParseError` from `load_manifest` is treated as 'no UI available'."""
    from clawrium.core.registry import ManifestParseError

    def boom(_t):
        raise ManifestParseError("corrupt manifest")

    monkeypatch.setattr(web_ui_module, "load_manifest", boom)
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )
    assert resolve("demo") is None


def test_resolve_returns_none_when_manifest_lacks_web_ui_key(monkeypatch):
    """A manifest with `features` but no `web_ui` returns `None` (mock-based regression anchor)."""
    manifest = {
        "agent": {"type": "hermes", "description": "test"},
        "platforms": [],
        "features": {"memory": True, "chat": {"type": "openai"}},
    }
    monkeypatch.setattr(web_ui_module, "load_manifest", lambda _t: manifest)
    _patch_agent(
        monkeypatch,
        host=_host(),
        agent_type="hermes",
        agent_record={"agent_name": "demo", "type": "hermes", "config": {}},
    )
    assert resolve("demo") is None


def test_bind_address_map_covers_loopback():
    """`BIND_ADDRESS_MAP` is the canonical loopback → 127.0.0.1 mapping."""
    from clawrium.core.web_ui import BIND_ADDRESS_MAP

    assert BIND_ADDRESS_MAP["loopback"] == "127.0.0.1"


def test_bind_address_map_covers_wildcard():
    """`wildcard` agents (zeroclaw) still tunnel to remote loopback."""
    from clawrium.core.web_ui import BIND_ADDRESS_MAP

    assert BIND_ADDRESS_MAP["wildcard"] == "127.0.0.1"


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
