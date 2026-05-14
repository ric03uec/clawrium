"""B5: openclaw chat credentials live in the secrets store, not hosts.json.

These tests cover `_resolve_openclaw_credentials` — the helper that bridges
new installs (which write to the secrets store) and legacy installs (where
auth + private key live in hosts.json). On the legacy path the values are
copied into the secrets store on first use so subsequent reads stop touching
hosts.json.
"""

import pytest

from clawrium.gui.routes import agents as agents_module
from clawrium.gui.routes.agents import (
    _OPENCLAW_AUTH_SECRET,
    _OPENCLAW_PRIVKEY_SECRET,
    _resolve_openclaw_credentials,
)


@pytest.fixture
def fake_secrets(monkeypatch):
    """In-memory replacement for the secrets store."""
    store: dict[str, dict[str, dict]] = {}

    def fake_get(instance_key):
        return store.get(instance_key, {})

    def fake_set(instance_key, key, value, description=""):
        store.setdefault(instance_key, {})[key] = {
            "key": key,
            "value": value,
            "description": description,
        }
        return True

    monkeypatch.setattr(agents_module, "get_instance_secrets", fake_get)
    monkeypatch.setattr(agents_module, "set_instance_secret", fake_set)
    return store


def test_reads_from_secrets_store_when_present(fake_secrets):
    fake_secrets["box:openclaw:agent1"] = {
        _OPENCLAW_AUTH_SECRET: {"value": "secret-auth"},
        _OPENCLAW_PRIVKEY_SECRET: {"value": "secret-pk"},
    }
    # The gateway dict shouldn't even be consulted on the happy path.
    auth, pk = _resolve_openclaw_credentials("box:openclaw:agent1", gateway={})
    assert auth == "secret-auth"
    assert pk == "secret-pk"


def test_falls_back_to_hosts_json_and_migrates(fake_secrets):
    gateway = {"auth": "legacy-auth", "device": {"privateKey": "legacy-pk"}}
    auth, pk = _resolve_openclaw_credentials("box:openclaw:agent1", gateway)

    assert auth == "legacy-auth"
    assert pk == "legacy-pk"
    # Auto-migration: secrets store now has the values.
    stored = fake_secrets["box:openclaw:agent1"]
    assert stored[_OPENCLAW_AUTH_SECRET]["value"] == "legacy-auth"
    assert stored[_OPENCLAW_PRIVKEY_SECRET]["value"] == "legacy-pk"
    # Description carries the migration tag so operators can audit later.
    assert "Auto-migrated" in stored[_OPENCLAW_AUTH_SECRET]["description"]


def test_does_not_migrate_when_secrets_already_present(fake_secrets):
    fake_secrets["box:openclaw:agent1"] = {
        _OPENCLAW_AUTH_SECRET: {"value": "in-store-auth"},
        _OPENCLAW_PRIVKEY_SECRET: {"value": "in-store-pk"},
    }
    gateway = {"auth": "ignored", "device": {"privateKey": "ignored"}}
    auth, pk = _resolve_openclaw_credentials("box:openclaw:agent1", gateway)
    # Existing values win and no overwrite happens.
    assert auth == "in-store-auth"
    assert pk == "in-store-pk"
    assert fake_secrets["box:openclaw:agent1"][_OPENCLAW_AUTH_SECRET]["value"] == (
        "in-store-auth"
    )


def test_returns_none_when_neither_source_has_value(fake_secrets):
    auth, pk = _resolve_openclaw_credentials("box:openclaw:agent1", gateway={})
    assert auth is None
    assert pk is None
