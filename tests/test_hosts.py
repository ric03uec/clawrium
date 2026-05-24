"""Tests for host storage module."""

import json
import pytest
from clawrium.core.hosts import (
    load_hosts,
    save_hosts,
    add_host,
    remove_host,
    get_host,
    get_host_by_key_id,
    get_agent_by_name,
    update_host,
    remove_agent_from_host,
    add_address_to_host,
    remove_address_from_host,
    set_primary_address,
    get_host_addresses,
    HOSTS_FILE,
    HostsFileCorruptedError,
    DuplicateHostError,
    AddressError,
)


def test_load_hosts_no_file(isolated_config):
    """load_hosts() with no file returns []."""
    hosts = load_hosts()
    assert hosts == []


def test_load_hosts_valid_json(isolated_config):
    """load_hosts() with valid JSON returns list of dicts."""
    # Setup: create hosts.json with test data
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / HOSTS_FILE
    test_data = [
        {"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"},
        {"hostname": "192.168.1.20", "port": 22, "agent_name": "xclm"},
    ]
    hosts_path.write_text(json.dumps(test_data))

    # Test
    hosts = load_hosts()
    assert len(hosts) == 2
    # Check core fields (addresses is added by migration)
    assert hosts[0]["hostname"] == "192.168.1.10"
    assert hosts[1]["hostname"] == "192.168.1.20"
    # Verify addresses were migrated
    assert "addresses" in hosts[0]
    assert "addresses" in hosts[1]


def test_save_hosts_creates_file(isolated_config):
    """save_hosts([host]) writes JSON to config dir."""
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]

    save_hosts(test_hosts)

    hosts_path = isolated_config / HOSTS_FILE
    assert hosts_path.exists()

    with open(hosts_path) as f:
        saved_data = json.load(f)
    assert saved_data == test_hosts


def test_save_hosts_creates_dir(tmp_path, monkeypatch):
    """save_hosts creates config directory if it doesn't exist."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "clawrium"

    # Config dir doesn't exist yet
    assert not config_dir.exists()

    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    # Config dir should now exist
    assert config_dir.exists()
    assert (config_dir / HOSTS_FILE).exists()


def test_add_host_appends(isolated_config):
    """add_host(host) appends to file (loads, appends, saves)."""
    # Setup: create initial hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    initial_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(initial_hosts)

    # Add new host
    new_host = {"hostname": "192.168.1.20", "port": 22, "agent_name": "xclm"}
    add_host(new_host)

    # Verify
    hosts = load_hosts()
    assert len(hosts) == 2
    # Check core fields (addresses is added by migration/add_host)
    assert hosts[0]["hostname"] == "192.168.1.10"
    assert hosts[1]["hostname"] == "192.168.1.20"
    # Verify addresses were initialized
    assert "addresses" in hosts[1]


def test_remove_host_found(isolated_config):
    """remove_host(hostname) removes by hostname match, returns True."""
    # Setup: create hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"},
        {"hostname": "192.168.1.20", "port": 22, "agent_name": "xclm"},
    ]
    save_hosts(test_hosts)

    # Remove first host
    result = remove_host("192.168.1.10")

    # Verify
    assert result is True
    hosts = load_hosts()
    assert len(hosts) == 1
    assert hosts[0]["hostname"] == "192.168.1.20"


def test_remove_host_not_found(isolated_config):
    """remove_host(hostname) returns False if not found."""
    # Setup: create hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    # Try to remove non-existent host
    result = remove_host("192.168.1.99")

    # Verify
    assert result is False
    hosts = load_hosts()
    assert len(hosts) == 1  # Original host still there


def test_get_host_by_hostname(isolated_config):
    """get_host(identifier) finds by hostname."""
    # Setup: create hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"},
        {"hostname": "192.168.1.20", "port": 22, "agent_name": "xclm"},
    ]
    save_hosts(test_hosts)

    # Find by hostname
    host = get_host("192.168.1.10")

    # Verify
    assert host is not None
    assert host["hostname"] == "192.168.1.10"


def test_get_host_by_alias(isolated_config):
    """get_host(identifier) finds by alias."""
    # Setup: create hosts with aliases
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {
            "hostname": "192.168.1.10",
            "port": 22,
            "agent_name": "xclm",
            "alias": "server1",
        },
        {
            "hostname": "192.168.1.20",
            "port": 22,
            "agent_name": "xclm",
            "alias": "server2",
        },
    ]
    save_hosts(test_hosts)

    # Find by alias
    host = get_host("server1")

    # Verify
    assert host is not None
    assert host["hostname"] == "192.168.1.10"
    assert host["alias"] == "server1"


def test_get_host_not_found(isolated_config):
    """get_host(identifier) returns None if not found."""
    # Setup: create hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    # Try to find non-existent host
    host = get_host("192.168.1.99")

    # Verify
    assert host is None


def test_save_hosts_file_permissions(isolated_config):
    """save_hosts() creates file with 0600 permissions."""
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    hosts_path = isolated_config / HOSTS_FILE
    mode = hosts_path.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_load_hosts_invalid_json(isolated_config):
    """load_hosts() raises HostsFileCorruptedError on invalid JSON."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / HOSTS_FILE
    hosts_path.write_text("not valid json {{{")

    with pytest.raises(HostsFileCorruptedError) as exc_info:
        load_hosts()
    assert "corrupted" in str(exc_info.value).lower()


def test_load_hosts_non_list_json(isolated_config):
    """load_hosts() raises HostsFileCorruptedError when JSON is not a list."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / HOSTS_FILE
    hosts_path.write_text('{"key": "value"}')

    with pytest.raises(HostsFileCorruptedError) as exc_info:
        load_hosts()
    assert "not a list" in str(exc_info.value).lower()


def test_load_hosts_list_with_non_dict_items(isolated_config):
    """load_hosts() raises HostsFileCorruptedError when list contains non-dicts."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / HOSTS_FILE
    hosts_path.write_text('[1, 2, "string", null]')

    with pytest.raises(HostsFileCorruptedError) as exc_info:
        load_hosts()
    assert "invalid entries" in str(exc_info.value).lower()


def test_host_claw_tracking_installed(isolated_config):
    """After successful install, host record contains claws[claw_name] with status='installed'."""
    # Setup: create host
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "agent_name": "xclm",
        "key_id": "testhost",
    }
    save_hosts([test_host])

    # Simulate install success by updating host with claw tracking
    def add_claw_tracking(h: dict) -> dict:
        if "agents" not in h:
            h["agents"] = {}
        h["agents"]["openclaw"] = {
            "version": "0.1.0",
            "status": "installed",
            "installed_at": "2024-01-01T00:00:00Z",
            "error": None,
            "agent_name": "opc-testhost",
        }
        return h

    result = update_host("192.168.1.10", add_claw_tracking)
    assert result is True

    # Verify host record contains claw tracking
    hosts = load_hosts()
    assert len(hosts) == 1
    assert "agents" in hosts[0]
    assert "openclaw" in hosts[0]["agents"]
    assert hosts[0]["agents"]["openclaw"]["status"] == "installed"
    assert hosts[0]["agents"]["openclaw"]["version"] == "0.1.0"
    assert hosts[0]["agents"]["openclaw"]["installed_at"] == "2024-01-01T00:00:00Z"
    assert hosts[0]["agents"]["openclaw"]["error"] is None
    assert hosts[0]["agents"]["openclaw"]["agent_name"] == "opc-testhost"


def test_host_claw_tracking_failed(isolated_config):
    """After failed install, host record contains claws[claw_name] with status='failed' and error message."""
    # Setup: create host
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}
    save_hosts([test_host])

    # Simulate install failure by updating host with failed status
    def add_failed_claw(h: dict) -> dict:
        if "agents" not in h:
            h["agents"] = {}
        h["agents"]["openclaw"] = {
            "version": "0.1.0",
            "status": "failed",
            "installed_at": "2024-01-01T00:00:00Z",
            "error": "Base playbook failed: timeout",
            "agent_name": None,
        }
        return h

    result = update_host("192.168.1.10", add_failed_claw)
    assert result is True

    # Verify host record contains failure tracking
    hosts = load_hosts()
    assert len(hosts) == 1
    assert "agents" in hosts[0]
    assert "openclaw" in hosts[0]["agents"]
    assert hosts[0]["agents"]["openclaw"]["status"] == "failed"
    assert hosts[0]["agents"]["openclaw"]["error"] == "Base playbook failed: timeout"


def test_update_host_not_found(isolated_config):
    """update_host returns False when hostname not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    def noop(h: dict) -> dict:
        return h

    result = update_host("nonexistent-host", noop)

    assert result is False
    # Original hosts unchanged
    hosts = load_hosts()
    assert len(hosts) == 1
    assert hosts[0]["hostname"] == "192.168.1.10"


def test_add_host_duplicate_raises(isolated_config):
    """add_host raises DuplicateHostError when hostname already exists."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    # Try to add duplicate hostname
    duplicate = {"hostname": "192.168.1.10", "port": 22, "agent_name": "different"}

    with pytest.raises(DuplicateHostError) as exc_info:
        add_host(duplicate)

    assert "already exists" in str(exc_info.value).lower()
    # Original hosts unchanged
    hosts = load_hosts()
    assert len(hosts) == 1


def test_get_host_by_key_id_found(isolated_config):
    """get_host_by_key_id finds host by key_id field."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {
            "hostname": "192.168.1.10",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "server1-key",
        },
        {
            "hostname": "192.168.1.20",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "server2-key",
        },
    ]
    save_hosts(test_hosts)

    host = get_host_by_key_id("server1-key")

    assert host is not None
    assert host["hostname"] == "192.168.1.10"
    assert host["key_id"] == "server1-key"


def test_get_host_by_key_id_not_found(isolated_config):
    """get_host_by_key_id returns None when key_id not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {
            "hostname": "192.168.1.10",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "known-key",
        }
    ]
    save_hosts(test_hosts)

    host = get_host_by_key_id("unknown-key")

    assert host is None


def test_remove_claw_from_host_success(isolated_config):
    """remove_claw_from_host removes claw from host's claws dict."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {
            "hostname": "192.168.1.10",
            "port": 22,
            "agent_name": "xclm",
            "agents": {
                "openclaw": {"version": "1.0.0", "agent_name": "opc-test"},
                "zeroclaw": {"version": "2.0.0", "agent_name": "zc-test"},
            },
        }
    ]
    save_hosts(test_hosts)

    result = remove_agent_from_host("192.168.1.10", "openclaw")

    assert result is True
    hosts = load_hosts()
    assert "openclaw" not in hosts[0]["agents"]
    assert "zeroclaw" in hosts[0]["agents"]  # Other claws remain


def test_remove_claw_from_host_not_found(isolated_config):
    """remove_claw_from_host returns True even if claw not in dict."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {
            "hostname": "192.168.1.10",
            "port": 22,
            "agent_name": "xclm",
            "agents": {"zeroclaw": {"version": "2.0.0"}},
        }
    ]
    save_hosts(test_hosts)

    # Try to remove non-existent claw
    result = remove_agent_from_host("192.168.1.10", "openclaw")

    assert result is True  # Operation succeeds idempotently
    hosts = load_hosts()
    assert "openclaw" not in hosts[0]["agents"]
    assert "zeroclaw" in hosts[0]["agents"]


def test_remove_claw_from_host_no_claws_dict(isolated_config):
    """remove_claw_from_host handles host with no claws dict."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    result = remove_agent_from_host("192.168.1.10", "openclaw")

    assert result is True  # Operation succeeds idempotently


def test_remove_claw_from_host_unknown_host(isolated_config):
    """remove_claw_from_host returns False for unknown host."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "agent_name": "xclm"}]
    save_hosts(test_hosts)

    result = remove_agent_from_host("192.168.1.99", "openclaw")

    assert result is False


def test_get_agent_by_name_unique_match(isolated_config):
    """get_agent_by_name returns matching host and agent tuple."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts = [
        {
            "hostname": "192.168.1.10",
            "alias": "alpha",
            "agents": {
                "openclaw": {
                    "agent_name": "opc-alpha",
                    "config": {
                        "gateway": {
                            "url": "ws://192.168.1.10:40123",
                            "auth": "token-a",
                        }
                    },
                }
            },
        }
    ]
    save_hosts(hosts)

    resolved = get_agent_by_name("opc-alpha")

    assert resolved is not None
    host, agent_type, record = resolved
    assert host["hostname"] == "192.168.1.10"
    assert agent_type == "openclaw"
    assert record["agent_name"] == "opc-alpha"


def test_get_agent_by_name_ambiguous_raises(isolated_config):
    """get_agent_by_name raises ValueError when name appears on multiple hosts."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts = [
        {
            "hostname": "192.168.1.10",
            "alias": "alpha",
            "agents": {"openclaw": {"agent_name": "opc-shared"}},
        },
        {
            "hostname": "192.168.1.11",
            "alias": "beta",
            "agents": {"openclaw": {"agent_name": "opc-shared"}},
        },
    ]
    save_hosts(hosts)

    with pytest.raises(ValueError) as exc_info:
        get_agent_by_name("opc-shared")

    assert "ambiguous" in str(exc_info.value).lower()


def test_get_agent_by_name_empty_returns_none():
    """get_agent_by_name returns None for blank query."""
    assert get_agent_by_name("   ") is None


# Tests for address management


def test_ensure_addresses_migration(isolated_config):
    """Hosts without addresses get migrated on load."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    # Create host without addresses field (old format)
    old_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    hosts_path = isolated_config / HOSTS_FILE
    hosts_path.write_text(json.dumps([old_host]))

    # Load should migrate
    hosts = load_hosts()

    assert len(hosts) == 1
    assert "addresses" in hosts[0]
    assert len(hosts[0]["addresses"]) == 1
    assert hosts[0]["addresses"][0]["address"] == "192.168.1.10"
    assert hosts[0]["addresses"][0]["is_primary"] is True


def test_add_address_success(isolated_config):
    """add_address_to_host adds new address correctly."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    add_address_to_host("192.168.1.10", "10.0.0.10", label="vpn")

    hosts = load_hosts()
    assert len(hosts[0]["addresses"]) == 2
    # Second address should not be primary
    secondary = [a for a in hosts[0]["addresses"] if a["address"] == "10.0.0.10"][0]
    assert secondary["is_primary"] is False
    assert secondary["label"] == "vpn"


def test_add_address_duplicate(isolated_config):
    """add_address_to_host raises AddressError for duplicate address."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        add_address_to_host("192.168.1.10", "192.168.1.10")

    assert "already exists" in str(exc_info.value)


def test_remove_address_success(isolated_config):
    """remove_address_from_host removes non-primary address."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "addresses": [
            {
                "address": "192.168.1.10",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.10",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    remove_address_from_host("192.168.1.10", "10.0.0.10")

    hosts = load_hosts()
    assert len(hosts[0]["addresses"]) == 1
    assert hosts[0]["addresses"][0]["address"] == "192.168.1.10"


def test_remove_address_primary_fails(isolated_config):
    """remove_address_from_host raises AddressError for primary address."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "addresses": [
            {
                "address": "192.168.1.10",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.10",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        remove_address_from_host("192.168.1.10", "192.168.1.10")

    assert "Cannot remove primary" in str(exc_info.value)


def test_remove_address_not_found(isolated_config):
    """remove_address_from_host raises AddressError when address not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        remove_address_from_host("192.168.1.10", "10.0.0.99")

    assert "not found" in str(exc_info.value)


def test_set_primary_success(isolated_config):
    """set_primary_address switches primary and syncs hostname."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "addresses": [
            {
                "address": "192.168.1.10",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.10",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    set_primary_address("192.168.1.10", "10.0.0.10")

    hosts = load_hosts()
    # hostname should be updated
    assert hosts[0]["hostname"] == "10.0.0.10"
    # Primary flags should be switched
    for addr in hosts[0]["addresses"]:
        if addr["address"] == "10.0.0.10":
            assert addr["is_primary"] is True
        else:
            assert addr["is_primary"] is False


def test_set_primary_not_found(isolated_config):
    """set_primary_address raises AddressError when address not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        set_primary_address("192.168.1.10", "10.0.0.99")

    assert "not found" in str(exc_info.value)


def test_get_host_addresses(isolated_config):
    """get_host_addresses returns correct list."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "addresses": [
            {
                "address": "192.168.1.10",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.10",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    addresses = get_host_addresses("192.168.1.10")

    assert len(addresses) == 2
    assert addresses[0]["address"] == "192.168.1.10"
    assert addresses[1]["address"] == "10.0.0.10"


def test_get_host_addresses_not_found(isolated_config):
    """get_host_addresses raises AddressError when host not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    with pytest.raises(AddressError) as exc_info:
        get_host_addresses("nonexistent")

    assert "not found" in str(exc_info.value)


# Tests for address validation


def test_add_address_empty_string(isolated_config):
    """add_address_to_host rejects empty address."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        add_address_to_host("192.168.1.10", "")

    assert "empty" in str(exc_info.value).lower()


def test_add_address_whitespace_only(isolated_config):
    """add_address_to_host rejects whitespace-only address."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        add_address_to_host("192.168.1.10", "   ")

    assert "empty" in str(exc_info.value).lower()


def test_add_address_shell_injection(isolated_config):
    """add_address_to_host rejects addresses with shell metacharacters."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    dangerous_addresses = [
        "host; rm -rf /",
        "host$(whoami)",
        "host`id`",
        "host|cat /etc/passwd",
        "host&& echo pwned",
        "host'injection",
        'host"injection',
    ]

    for addr in dangerous_addresses:
        with pytest.raises(AddressError) as exc_info:
            add_address_to_host("192.168.1.10", addr)
        assert "invalid characters" in str(exc_info.value).lower()


def test_add_address_user_prefix(isolated_config):
    """add_address_to_host rejects addresses with @ symbol."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_host = {
        "hostname": "192.168.1.10",
        "port": 22,
        "metadata": {"added_at": "2024-01-01T00:00:00Z"},
    }
    save_hosts([test_host])

    with pytest.raises(AddressError) as exc_info:
        add_address_to_host("192.168.1.10", "user@host.example.com")

    assert "@" in str(exc_info.value)


def test_add_address_host_not_found(isolated_config):
    """add_address_to_host raises AddressError when host not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    with pytest.raises(AddressError) as exc_info:
        add_address_to_host("nonexistent-host", "10.0.0.1")

    assert "not found" in str(exc_info.value).lower()
