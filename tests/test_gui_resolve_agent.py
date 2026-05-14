"""Tests for the shared agent resolver used by every GUI route handler."""

import pytest

from clawrium.core.hosts import HostsFileCorruptedError
from clawrium.gui.routes import _common
from clawrium.gui.routes._common import resolve_agent


def test_returns_tuple_when_get_agent_by_name_resolves(monkeypatch):
    host = {"hostname": "mybox"}
    agent_type = "openclaw"
    agent_record = {"agent_name": "demo"}

    monkeypatch.setattr(
        _common, "get_agent_by_name", lambda key: (host, agent_type, agent_record)
    )

    result = resolve_agent("demo")
    assert result == (host, agent_type, agent_record)


def test_returns_none_on_hosts_file_corrupted(monkeypatch):
    def boom(_key):
        raise HostsFileCorruptedError("bad json")

    monkeypatch.setattr(_common, "get_agent_by_name", boom)
    assert resolve_agent("anything") is None


def test_returns_none_on_value_error(monkeypatch):
    def boom(_key):
        raise ValueError("multiple agents match")

    monkeypatch.setattr(_common, "get_agent_by_name", boom)
    assert resolve_agent("ambiguous") is None


def test_returns_none_on_os_error(monkeypatch):
    def boom(_key):
        raise PermissionError("hosts.json not readable")

    monkeypatch.setattr(_common, "get_agent_by_name", boom)
    assert resolve_agent("any") is None


def test_returns_none_when_get_agent_by_name_returns_none(monkeypatch):
    monkeypatch.setattr(_common, "get_agent_by_name", lambda _key: None)
    assert resolve_agent("unknown") is None


def test_unexpected_exception_propagates(monkeypatch):
    """A KeyError isn't expected — surfacing it lets the bug get a stack trace."""

    def boom(_key):
        raise KeyError("programmer error")

    monkeypatch.setattr(_common, "get_agent_by_name", boom)
    with pytest.raises(KeyError):
        resolve_agent("any")
