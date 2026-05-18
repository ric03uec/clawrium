"""Tests for the topology route's provider_endpoint enrichment."""

from clawrium.core.health import ClawStatus
from clawrium.gui.routes import topology as topology_mod


def _make_agent(
    agent_key: str,
    *,
    host: str = "wolf-i",
    agent_type: str = "openclaw",
    provider: str | None = "clm-bedrock",
    provider_type: str | None = "bedrock",
):
    return {
        "agent_key": agent_key,
        "agent_name": agent_key,
        "agent_type": agent_type,
        "host": host,
        "host_alias": host,
        "version": "1.0.0",
        "status": ClawStatus.RUNNING,
        "model": "model-x",
        "uptime": "1m",
        "provider": provider,
        "provider_type": provider_type,
    }


def _make_host(hostname: str = "wolf-i"):
    return {
        "hostname": hostname,
        "alias": hostname,
        "user": "alice",
        "addresses": [],
        "key_id": "key-1",
        "agents": {},
    }


def _stub_get_fleet_data(agents, summary=None):
    summary = summary or {"total": len(agents), "running": len(agents), "hosts": 1}

    def _inner(_filter):
        return agents, summary

    return _inner


def test_provider_endpoint_attached_when_provider_has_endpoint(monkeypatch):
    agents = [_make_agent("a1", provider="local-inx", provider_type="ollama")]
    hosts = [_make_host()]
    providers = [
        {"name": "local-inx", "type": "ollama", "endpoint": "http://10.0.0.5:11434"}
    ]

    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: hosts)
    monkeypatch.setattr(topology_mod, "load_providers", lambda: providers)

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    agent_payload = result["hosts"][0]["agents"][0]
    assert agent_payload["provider"] == "local-inx"
    assert agent_payload["provider_type"] == "ollama"
    assert agent_payload["provider_endpoint"] == "http://10.0.0.5:11434"


def test_provider_endpoint_is_none_for_provider_without_endpoint(monkeypatch):
    agents = [_make_agent("a1", provider="clm-bedrock", provider_type="bedrock")]
    hosts = [_make_host()]
    providers = [{"name": "clm-bedrock", "type": "bedrock"}]

    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: hosts)
    monkeypatch.setattr(topology_mod, "load_providers", lambda: providers)

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    assert result["hosts"][0]["agents"][0]["provider_endpoint"] is None


def test_provider_endpoint_is_none_for_unconfigured_agent(monkeypatch):
    agents = [_make_agent("a1", provider=None, provider_type=None)]
    hosts = [_make_host()]

    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: hosts)
    monkeypatch.setattr(topology_mod, "load_providers", lambda: [])

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    payload = result["hosts"][0]["agents"][0]
    assert payload["provider"] is None
    assert payload["provider_endpoint"] is None


def test_load_provider_endpoints_returns_empty_when_corrupted(monkeypatch):
    from clawrium.core.providers.storage import ProvidersFileCorruptedError

    def boom():
        raise ProvidersFileCorruptedError("bad json")

    monkeypatch.setattr(topology_mod, "load_providers", boom)
    assert topology_mod._load_provider_endpoints() == {}


def test_load_provider_endpoints_returns_empty_on_permission_error(monkeypatch):
    def boom():
        raise PermissionError("no read")

    monkeypatch.setattr(topology_mod, "load_providers", boom)
    assert topology_mod._load_provider_endpoints() == {}


def test_load_provider_endpoints_returns_empty_on_os_error(monkeypatch):
    def boom():
        raise OSError("disk error")

    monkeypatch.setattr(topology_mod, "load_providers", boom)
    assert topology_mod._load_provider_endpoints() == {}


def test_load_provider_endpoints_normalizes_empty_string_to_none(monkeypatch):
    monkeypatch.setattr(
        topology_mod,
        "load_providers",
        lambda: [{"name": "weird", "type": "ollama", "endpoint": ""}],
    )
    assert topology_mod._load_provider_endpoints() == {"weird": None}


def test_get_topology_assigns_agents_to_correct_hosts(monkeypatch):
    agents = [
        _make_agent("a1", host="wolf-i"),
        _make_agent("b1", host="wolf-ii"),
    ]
    hosts = [_make_host("wolf-i"), _make_host("wolf-ii")]
    monkeypatch.setattr(
        topology_mod,
        "get_fleet_data_local",
        _stub_get_fleet_data(
            agents, {"total": 2, "running": 2, "hosts": 2}
        ),
    )
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: hosts)
    monkeypatch.setattr(topology_mod, "load_providers", lambda: [])

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    by_host = {h["hostname"]: h for h in result["hosts"]}
    assert [a["agent_key"] for a in by_host["wolf-i"]["agents"]] == ["a1"]
    assert [a["agent_key"] for a in by_host["wolf-ii"]["agents"]] == ["b1"]


def test_load_provider_endpoints_normalizes_whitespace_to_none(monkeypatch):
    monkeypatch.setattr(
        topology_mod,
        "load_providers",
        lambda: [{"name": "weird", "type": "ollama", "endpoint": "   "}],
    )
    assert topology_mod._load_provider_endpoints() == {"weird": None}


def test_host_includes_hardware_block_when_present(monkeypatch):
    agents = [_make_agent("a1")]
    host = _make_host()
    host["hardware"] = {
        "architecture": "aarch64",
        "processor_cores": 32,
        "memtotal_mb": 65536,
        "gpu": {"present": True, "vendor": "nvidia", "error": None},
        "product_name": "DGX Spark",
        "system_vendor": "nvidia",
    }

    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: [host])
    monkeypatch.setattr(topology_mod, "load_providers", lambda: [])

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    hw = result["hosts"][0]["hardware"]
    assert hw is not None
    assert hw["architecture"] == "aarch64"
    assert hw["cores"] == 32
    assert hw["memtotal_mb"] == 65536
    assert hw["gpu"] == {"present": True, "vendor": "nvidia", "error": None}
    assert hw["product_name"] == "DGX Spark"
    assert hw["system_vendor"] == "nvidia"


def test_host_hardware_is_null_when_absent(monkeypatch):
    agents = [_make_agent("a1")]
    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: [_make_host()])
    monkeypatch.setattr(topology_mod, "load_providers", lambda: [])

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    assert result["hosts"][0]["hardware"] is None


def test_host_hardware_gpu_defaults_when_only_partial(monkeypatch):
    agents = [_make_agent("a1")]
    host = _make_host()
    host["hardware"] = {"architecture": "x86_64"}

    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: [host])
    monkeypatch.setattr(topology_mod, "load_providers", lambda: [])

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    hw = result["hosts"][0]["hardware"]
    assert hw["architecture"] == "x86_64"
    assert hw["gpu"] == {"present": False, "vendor": None, "error": None}
    assert hw["product_name"] is None
    assert hw["system_vendor"] is None


def test_provider_endpoint_is_none_when_provider_not_in_providers_file(monkeypatch):
    agents = [_make_agent("a1", provider="ghost", provider_type="ollama")]
    hosts = [_make_host()]
    providers = [
        {"name": "local-inx", "type": "ollama", "endpoint": "http://10.0.0.5:11434"}
    ]

    monkeypatch.setattr(topology_mod, "get_fleet_data_local", _stub_get_fleet_data(agents))
    monkeypatch.setattr(topology_mod, "load_hosts_safe", lambda: hosts)
    monkeypatch.setattr(topology_mod, "load_providers", lambda: providers)

    import asyncio

    result = asyncio.run(topology_mod.get_topology())

    payload = result["hosts"][0]["agents"][0]
    assert payload["provider"] == "ghost"
    assert payload["provider_endpoint"] is None
