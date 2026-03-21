"""Tests for host storage module."""

import json
import pytest
from pathlib import Path
from clawrium.core.hosts import (
    load_hosts,
    save_hosts,
    add_host,
    remove_host,
    get_host,
    HOSTS_FILE,
    HostsFileCorruptedError,
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
        {"hostname": "192.168.1.10", "port": 22, "user": "xclm"},
        {"hostname": "192.168.1.20", "port": 22, "user": "xclm"},
    ]
    hosts_path.write_text(json.dumps(test_data))

    # Test
    hosts = load_hosts()
    assert hosts == test_data


def test_save_hosts_creates_file(isolated_config):
    """save_hosts([host]) writes JSON to config dir."""
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "user": "xclm"}]

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

    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "user": "xclm"}]
    save_hosts(test_hosts)

    # Config dir should now exist
    assert config_dir.exists()
    assert (config_dir / HOSTS_FILE).exists()


def test_add_host_appends(isolated_config):
    """add_host(host) appends to file (loads, appends, saves)."""
    # Setup: create initial hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    initial_hosts = [{"hostname": "192.168.1.10", "port": 22, "user": "xclm"}]
    save_hosts(initial_hosts)

    # Add new host
    new_host = {"hostname": "192.168.1.20", "port": 22, "user": "xclm"}
    add_host(new_host)

    # Verify
    hosts = load_hosts()
    assert len(hosts) == 2
    assert hosts[0] == initial_hosts[0]
    assert hosts[1] == new_host


def test_remove_host_found(isolated_config):
    """remove_host(hostname) removes by hostname match, returns True."""
    # Setup: create hosts
    isolated_config.mkdir(parents=True, exist_ok=True)
    test_hosts = [
        {"hostname": "192.168.1.10", "port": 22, "user": "xclm"},
        {"hostname": "192.168.1.20", "port": 22, "user": "xclm"},
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
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "user": "xclm"}]
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
        {"hostname": "192.168.1.10", "port": 22, "user": "xclm"},
        {"hostname": "192.168.1.20", "port": 22, "user": "xclm"},
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
        {"hostname": "192.168.1.10", "port": 22, "user": "xclm", "alias": "server1"},
        {"hostname": "192.168.1.20", "port": 22, "user": "xclm", "alias": "server2"},
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
    test_hosts = [{"hostname": "192.168.1.10", "port": 22, "user": "xclm"}]
    save_hosts(test_hosts)

    # Try to find non-existent host
    host = get_host("192.168.1.99")

    # Verify
    assert host is None
