"""Issue #448 — every per-agent secret callsite keys by host['key_id'].

Pure unit coverage on the helper that everyone consumes
(`get_instance_key`) plus a focused check on `get_installed_claw`,
which is the resolver every CLI secret command routes through.
"""

from __future__ import annotations

from unittest.mock import patch

from clawrium.core.secrets import get_installed_claw, get_instance_key


def _host(**over):
    base = {
        "hostname": "wolf.tailf7742d.ts.net",
        "key_id": "192.168.1.36",
        "agents": {
            "hermes": {
                "agent_name": "maurice",
                "name": "maurice",
                "type": "hermes",
            }
        },
    }
    base.update(over)
    return base


def test_get_installed_claw_returns_key_id_not_hostname():
    """If hostname has drifted away from key_id (post-IP→DNS migration),
    the resolver must return the stable key_id so secrets lookups land
    in the original slot."""
    with patch("clawrium.core.hosts.load_hosts", return_value=[_host()]):
        host_key, claw_type, name = get_installed_claw("maurice")
    assert host_key == "192.168.1.36"
    assert claw_type == "hermes"
    assert name == "maurice"


def test_get_installed_claw_falls_back_to_hostname_when_key_id_missing():
    """Legacy / hand-edited records without key_id must still resolve."""
    host = _host()
    host.pop("key_id")
    with patch("clawrium.core.hosts.load_hosts", return_value=[host]):
        host_key, _, _ = get_installed_claw("maurice")
    assert host_key == "wolf.tailf7742d.ts.net"


def test_instance_key_format():
    assert (
        get_instance_key("192.168.1.36", "hermes", "maurice")
        == "192.168.1.36:hermes:maurice"
    )


def test_get_installed_claw_resolves_type_from_data_not_dict_key():
    """Post-#448 follow-up: current-schema hosts.json records key the
    agents dict by agent name (e.g. `agents.maurice = {type: "hermes",
    ...}`), not by claw type. `get_installed_claw` must use
    `claw_data["type"]` for the claw_type segment, not the dict key —
    otherwise it produces `wolf-i:maurice:maurice` instead of the
    canonical `wolf-i:hermes:maurice`, and secret lookups for every
    current-schema agent silently return empty."""
    host = {
        "hostname": "wolf.tailf7742d.ts.net",
        "key_id": "wolf-i",
        "agents": {
            "maurice": {
                "agent_name": "maurice",
                "name": "maurice",
                "type": "hermes",
            }
        },
    }
    with patch("clawrium.core.hosts.load_hosts", return_value=[host]):
        host_key, claw_type, name = get_installed_claw("maurice")
    assert claw_type == "hermes", (
        f"claw_type must come from data.type, not dict_key; got {claw_type!r}"
    )
    assert get_instance_key(host_key, claw_type, name) == "wolf-i:hermes:maurice"


def test_get_installed_claw_legacy_schema_falls_back_to_dict_key():
    """Legacy schema keyed the agents dict by claw type and did not set
    a `type` field on the inner record. Backward-compat path: when
    `claw_data["type"]` is absent, fall back to the dict key."""
    host = {
        "hostname": "10.0.0.1",
        "key_id": "10.0.0.1",
        "agents": {
            "openclaw": {
                "name": "work",
                "agent_name": "opc-work",
            }
        },
    }
    with patch("clawrium.core.hosts.load_hosts", return_value=[host]):
        host_key, claw_type, name = get_installed_claw("work")
    assert claw_type == "openclaw"
    assert name == "opc-work"


def test_secrets_survive_hostname_mutation():
    """Repro of the maurice/wolf-i breakage: store the secret under the
    key_id slot, then mutate hostname; lookup must still find it."""
    host = _host()
    key_before = get_instance_key(
        host.get("key_id") or host["hostname"], "hermes", "maurice"
    )
    host["hostname"] = "10.0.0.7"  # operator renumbered the network
    key_after = get_instance_key(
        host.get("key_id") or host["hostname"], "hermes", "maurice"
    )
    assert key_before == key_after
