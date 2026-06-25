"""Tests for load-time pruning of the legacy `config.provider/providers/channels` mirror.

#794 stopped writing these keys; #795 strips any residue from existing
`hosts.json` files on load so the file shrinks on the next save round-trip.
Group B keys (`config.gateway/dashboard/api_server`) MUST be preserved
byte-for-byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawrium.core.hosts import (
    _PRESERVED_AGENT_CONFIG_KEYS,
    _PRUNED_AGENT_CONFIG_KEYS,
    HOSTS_FILE,
    load_hosts,
    read_gateway_auth,
    save_hosts,
    set_gateway_auth,
)


def _patch_config_dir(monkeypatch, config_dir: Path) -> None:
    """Route every config-dir lookup in hosts.py at `config_dir`."""
    monkeypatch.setattr("clawrium.core.hosts.get_config_dir", lambda: config_dir)
    monkeypatch.setattr("clawrium.core.hosts.init_config_dir", lambda: config_dir)


def _write_hosts(config_dir: Path, payload: list[dict]) -> None:
    # Compact; save_hosts re-serializes with indent=2.
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / HOSTS_FILE).write_text(json.dumps(payload))


def _agent_with_config(config: dict | None) -> dict:
    return {
        "hostname": "h1",
        "key_id": "h1",
        "user": "xclm",
        "port": 22,
        "os_family": "linux",
        "addresses": [{"address": "h1", "is_primary": True, "label": None}],
        "agents": {
            "demo": {
                "type": "hermes",
                "agent_name": "demo",
                "config": config,
            }
        },
    }


def test_module_invariant_group_b_never_in_pruned_set():
    """Belt-and-suspenders for the module-level assertion: regression
    test that locks Group A and Group B as disjoint."""
    assert not (_PRUNED_AGENT_CONFIG_KEYS & _PRESERVED_AGENT_CONFIG_KEYS)


@pytest.mark.parametrize(
    "stripped_key,stripped_value,preserved_key,preserved_value",
    [
        (
            "provider",
            {"name": "openai", "default_model": "openai/gpt-4o"},
            "gateway",
            {"port": 40000, "auth": "tok"},
        ),
        (
            "providers",
            [
                {"name": "openai", "default_model": "openai/gpt-4o"},
                {"name": "anthropic", "default_model": "claude-opus-4-7"},
            ],
            "dashboard",
            {"port": 45000},
        ),
        (
            "channels",
            {"discord": {"bot_token": "stale-secret", "app_token": "stale-app"}},
            "api_server",
            {"port": 41000},
        ),
    ],
    ids=["provider", "providers", "channels"],
)
def test_load_hosts_strips_group_a_key(
    tmp_path,
    monkeypatch,
    stripped_key,
    stripped_value,
    preserved_key,
    preserved_value,
):
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(
        config_dir,
        [
            _agent_with_config(
                {stripped_key: stripped_value, preserved_key: preserved_value}
            )
        ],
    )

    hosts = load_hosts()

    config = hosts[0]["agents"]["demo"]["config"]
    # Exact key set: nothing stripped beyond the named key, nothing added.
    assert set(config.keys()) == {preserved_key}
    assert config[preserved_key] == preserved_value


def test_load_hosts_preserves_group_b(tmp_path, monkeypatch):
    """Gateway / dashboard / api_server round-trip unchanged even when
    Group A keys live alongside them.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    group_b = {
        "gateway": {
            "port": 40123,
            "auth": "bearer-xyz",
            "host": "127.0.0.1",
        },
        "dashboard": {"port": 45123, "bind": "loopback"},
        "api_server": {"port": 41123},
    }
    _write_hosts(
        config_dir,
        [
            _agent_with_config(
                {
                    **group_b,
                    "provider": {"name": "openai"},
                    "providers": [{"name": "openai"}],
                    "channels": {"discord": {"bot_token": "x"}},
                }
            )
        ],
    )

    hosts = load_hosts()
    config = hosts[0]["agents"]["demo"]["config"]

    for key in _PRUNED_AGENT_CONFIG_KEYS:
        assert key not in config
    # Byte-for-byte preservation of Group B.
    assert config["gateway"] == group_b["gateway"]
    assert config["dashboard"] == group_b["dashboard"]
    assert config["api_server"] == group_b["api_server"]


def test_load_save_round_trip_is_idempotent(tmp_path, monkeypatch):
    """First load_hosts strips Group A; save_hosts persists the pruned
    shape; second round-trip is a no-op (file bytes unchanged).
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(
        config_dir,
        [
            _agent_with_config(
                {
                    "provider": {"name": "openai"},
                    "providers": [{"name": "openai"}],
                    "channels": {"discord": {"bot_token": "x"}},
                    "gateway": {"port": 40000, "auth": "tok"},
                }
            )
        ],
    )

    save_hosts(load_hosts())
    first_bytes = (config_dir / HOSTS_FILE).read_bytes()

    save_hosts(load_hosts())
    second_bytes = (config_dir / HOSTS_FILE).read_bytes()

    # The first save must have actually pruned (Group A keys absent
    # from raw bytes); the second must be a no-op (byte-stable).
    # File length pre/post first save can't be compared directly:
    # _write_hosts writes compact JSON while save_hosts uses indent=2.
    assert first_bytes == second_bytes
    for key in _PRUNED_AGENT_CONFIG_KEYS:
        assert f'"{key}"'.encode() not in first_bytes
    persisted = json.loads(first_bytes)
    config = persisted[0]["agents"]["demo"]["config"]
    for key in _PRUNED_AGENT_CONFIG_KEYS:
        assert key not in config
    assert config["gateway"] == {"port": 40000, "auth": "tok"}


def test_round_trip_clean_input_is_byte_stable(tmp_path, monkeypatch):
    """A hosts.json with no Group A residue must also round-trip
    byte-stably — proves the prune doesn't introduce key-ordering
    churn in `save_hosts`.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(
        config_dir,
        [_agent_with_config({"gateway": {"port": 40000, "auth": "tok"}})],
    )

    save_hosts(load_hosts())
    first_bytes = (config_dir / HOSTS_FILE).read_bytes()
    save_hosts(load_hosts())
    second_bytes = (config_dir / HOSTS_FILE).read_bytes()
    assert first_bytes == second_bytes


def test_load_hosts_no_op_when_keys_absent(tmp_path, monkeypatch):
    """Records without Group A keys must round-trip unchanged."""
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(
        config_dir,
        [
            _agent_with_config({"gateway": {"port": 40000, "auth": "tok"}}),
        ],
    )

    hosts = load_hosts()
    assert hosts[0]["agents"]["demo"]["config"] == {
        "gateway": {"port": 40000, "auth": "tok"}
    }


def test_load_hosts_handles_host_without_agents(tmp_path, monkeypatch):
    """Hosts with no `agents` dict (e.g. host registered but no agent
    installed yet) must not blow up.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(
        config_dir,
        [
            {
                "hostname": "h1",
                "key_id": "h1",
                "user": "xclm",
                "port": 22,
                "os_family": "linux",
                "addresses": [{"address": "h1", "is_primary": True, "label": None}],
            }
        ],
    )

    hosts = load_hosts()
    assert hosts[0]["hostname"] == "h1"
    assert "agents" not in hosts[0]


def test_load_hosts_handles_non_dict_agent_record(tmp_path, monkeypatch):
    """Malformed agent records (non-dict values) pass through untouched
    and don't break sibling pruning. Locks down the `isinstance(record,
    dict)` guard in `_prune_agent_config_mirror`.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    payload = [
        {
            "hostname": "h1",
            "key_id": "h1",
            "user": "xclm",
            "port": 22,
            "os_family": "linux",
            "addresses": [{"address": "h1", "is_primary": True, "label": None}],
            "agents": {
                "bogus": "not-a-dict",
                "demo": {
                    "type": "hermes",
                    "agent_name": "demo",
                    "config": {
                        "provider": {"name": "openai"},
                        "gateway": {"port": 40000, "auth": "tok"},
                    },
                },
            },
        }
    ]
    _write_hosts(config_dir, payload)

    hosts = load_hosts()

    assert hosts[0]["agents"]["bogus"] == "not-a-dict"
    sibling = hosts[0]["agents"]["demo"]["config"]
    assert "provider" not in sibling
    assert sibling["gateway"] == {"port": 40000, "auth": "tok"}


@pytest.mark.parametrize("config_value", [None, "string", 42, [1, 2, 3]])
def test_load_hosts_handles_non_dict_config(tmp_path, monkeypatch, config_value):
    """An agent record whose `config` is None or not a dict passes
    through untouched. Locks down the `isinstance(config, dict)` guard.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(config_dir, [_agent_with_config(config_value)])

    hosts = load_hosts()
    assert hosts[0]["agents"]["demo"]["config"] == config_value


def test_load_hosts_handles_agent_record_without_config_key(tmp_path, monkeypatch):
    """A freshly-created agent record may not have a `config` key at
    all; load_hosts must not introduce one.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)
    _write_hosts(
        config_dir,
        [
            {
                "hostname": "h1",
                "key_id": "h1",
                "user": "xclm",
                "port": 22,
                "os_family": "linux",
                "addresses": [{"address": "h1", "is_primary": True, "label": None}],
                "agents": {
                    "demo": {"type": "hermes", "agent_name": "demo"},
                },
            }
        ],
    )

    hosts = load_hosts()
    assert "config" not in hosts[0]["agents"]["demo"]


def test_load_hosts_prunes_across_multiple_hosts_and_agents(tmp_path, monkeypatch):
    """Multi-host × multi-agent fan-out. Catches a regression where the
    pruner only processes the first host or the first agent inside a
    host's `agents.values()`.
    """
    config_dir = tmp_path / "config"
    _patch_config_dir(monkeypatch, config_dir)

    def _host(hostname: str, agents: dict) -> dict:
        return {
            "hostname": hostname,
            "key_id": hostname,
            "user": "xclm",
            "port": 22,
            "os_family": "linux",
            "addresses": [{"address": hostname, "is_primary": True, "label": None}],
            "agents": agents,
        }

    payload = [
        _host(
            "h1",
            {
                "a": {
                    "type": "hermes",
                    "agent_name": "a",
                    "config": {
                        "provider": {"name": "openai"},
                        "gateway": {"port": 40001, "auth": "a1"},
                    },
                },
                "b": {
                    "type": "zeroclaw",
                    "agent_name": "b",
                    "config": {"gateway": {"port": 40002, "auth": "b1"}},
                },
                "c": {
                    "type": "openclaw",
                    "agent_name": "c",
                    "config": {
                        "channels": {"discord": {"bot_token": "stale"}},
                        "dashboard": {"port": 45001},
                    },
                },
            },
        ),
        _host(
            "h2",
            {
                "d": {
                    "type": "hermes",
                    "agent_name": "d",
                    "config": {
                        "providers": [{"name": "anthropic"}],
                        "api_server": {"port": 41001},
                    },
                },
            },
        ),
    ]
    _write_hosts(config_dir, payload)

    hosts = load_hosts()

    a = hosts[0]["agents"]["a"]["config"]
    assert "provider" not in a
    assert a["gateway"] == {"port": 40001, "auth": "a1"}

    b = hosts[0]["agents"]["b"]["config"]
    assert b == {"gateway": {"port": 40002, "auth": "b1"}}

    c = hosts[0]["agents"]["c"]["config"]
    assert "channels" not in c
    assert c["dashboard"] == {"port": 45001}

    d = hosts[1]["agents"]["d"]["config"]
    assert "providers" not in d
    assert d["api_server"] == {"port": 41001}


# #820: read/write helpers for `gateway.auth`. The contract is a
# single on-disk shape (bare string); `read_gateway_auth` tolerates the
# legacy dict shape so a manually patched hosts.json still renders.


@pytest.mark.parametrize(
    "gateway_blob,expected",
    [
        # Canonical bare-string shape.
        ({"auth": "deadbeef"}, "deadbeef"),
        # Legacy dict shape (the form `core/install.py` used to write
        # via the playbook template before #820, and the form
        # `~/.openclaw/openclaw.json` still carries on the agent host).
        ({"auth": {"mode": "token", "token": "deadbeef"}}, "deadbeef"),
        # Absent auth key.
        ({}, ""),
        # Explicit None auth.
        ({"auth": None}, ""),
        # Empty bare string.
        ({"auth": ""}, ""),
        # Dict missing the token key.
        ({"auth": {"mode": "token"}}, ""),
        # Dict with non-string token.
        ({"auth": {"mode": "token", "token": None}}, ""),
        # Unrecognized type (list / int) — return "" rather than
        # crash; `_clean_secret` downstream sees an empty string.
        ({"auth": ["x"]}, ""),
        ({"auth": 42}, ""),
        # Gateway blob itself is None / not a dict.
        (None, ""),
        # Whitespace-only bare-string: returned verbatim — the
        # reader is intentionally lenient. Collapsing whitespace at
        # the read side would silently mutate any token an operator
        # persisted with surrounding whitespace (e.g. a copy/paste
        # accident). Downstream (`_clean_secret` only strips NUL/
        # CR/LF) decides what to do with it.
        ({"auth": "   "}, "   "),
        # Same lenient contract for the dict shape.
        ({"auth": {"mode": "token", "token": "   "}}, "   "),
        # Wrong `mode` value: `read_gateway_auth` ignores `mode`
        # entirely and returns the embedded token. Pins the
        # "mode-agnostic" half of the lenient contract — if `mode`
        # validation is ever wanted, it lives at the write side, not
        # the read side.
        ({"auth": {"mode": "basic", "token": "x"}}, "x"),
    ],
)
def test_read_gateway_auth_shapes(gateway_blob, expected):
    assert read_gateway_auth(gateway_blob) == expected


def test_set_gateway_auth_writes_bare_string():
    block: dict = {"port": 40000}
    set_gateway_auth(block, "deadbeef")
    assert block == {"port": 40000, "auth": "deadbeef"}


def test_set_gateway_auth_normalizes_legacy_dict():
    """A block that already carries the legacy dict shape gets
    rewritten to the bare-string shape on the next write — this is
    what self-heals existing dict-shape hosts.json files on the
    first sync after the fix."""
    block: dict = {"auth": {"mode": "token", "token": "old"}, "port": 40000}
    set_gateway_auth(block, "new")
    assert block["auth"] == "new"


def test_read_then_set_normalizes_dict_to_bare_string():
    """The composition `set_gateway_auth(dst, read_gateway_auth(src))`
    — used by `cli/agent.py:_sync_provider_config` and
    `lifecycle.configure_agent` to propagate auth from the persisted
    record onto a fresh gateway_config block — must collapse a
    legacy dict-shape source to a bare-string destination. Pins the
    call-site contract directly, since the live function is wired to
    Ansible and not easy to unit-test end-to-end."""
    src = {"auth": {"mode": "token", "token": "deadbeef"}, "port": 40000}
    dst: dict = {"port": 40000}
    set_gateway_auth(dst, read_gateway_auth(src))
    assert dst["auth"] == "deadbeef"
    # And the canonical bare-string source must round-trip unchanged.
    src2 = {"auth": "cafef00d", "port": 40000}
    dst2: dict = {"port": 40000}
    set_gateway_auth(dst2, read_gateway_auth(src2))
    assert dst2["auth"] == "cafef00d"
