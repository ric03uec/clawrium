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
