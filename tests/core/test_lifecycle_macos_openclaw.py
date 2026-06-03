"""Openclaw-specific lifecycle_macos tests (issue #604).

Hermes coverage stays in test_lifecycle_macos.py. These tests assert
agent_type='openclaw' threads through to the launchctl command shape
and that openclaw's lifecycle does NOT iterate the dashboard kind
(openclaw has no separate dashboard unit).
"""

from io import StringIO

from clawrium.core import lifecycle_macos


class _Chan:
    def __init__(self, exit_status=0):
        self.exit_status = exit_status

    def recv_exit_status(self):
        return self.exit_status


class _Out:
    def __init__(self, content="", exit_status=0):
        self._content = content.encode()
        self.channel = _Chan(exit_status)

    def read(self):
        return self._content


class _FakeClient:
    def __init__(self, responses=None):
        self.commands = []
        self._responses = list(responses or [])

    def exec_command(self, cmd):
        self.commands.append(cmd)
        rc, out, err = self._responses.pop(0) if self._responses else (0, "", "")
        return StringIO(), _Out(out, rc), _Out(err, rc)

    def close(self):
        pass

    def open_sftp(self):
        raise RuntimeError("SFTP not exercised in this unit test")


def _fake_ssh(host):  # noqa: ARG001
    return _FakeClient()


def test_start_agent_macos_openclaw_uses_openclaw_label(monkeypatch):
    """start_agent_macos with agent_type=openclaw must hit the
    `ai.clawrium.openclaw.<name>` label, NOT the hermes prefix."""
    client = _FakeClient(responses=[(0, "", "") for _ in range(10)])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)
    monkeypatch.setattr(lifecycle_macos, "install_service", lambda *a, **k: "/p")

    ok, err = lifecycle_macos.start_agent_macos(
        {"hostname": "x"}, "o1", agent_type="openclaw"
    )
    assert ok is True
    assert err is None
    joined = "\n".join(client.commands)
    assert "ai.clawrium.openclaw.o1" in joined
    # Openclaw must NEVER bootstrap a dashboard unit.
    assert "dashboard" not in joined
    assert "ai.clawrium.hermes" not in joined


def test_stop_agent_macos_openclaw_skips_dashboard(monkeypatch):
    client = _FakeClient(responses=[(0, "", "")])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)

    ok, err = lifecycle_macos.stop_agent_macos(
        {"hostname": "x"}, "o1", agent_type="openclaw"
    )
    assert ok is True
    assert err is None
    # Exactly one bootout — the openclaw gateway. No dashboard.
    bootouts = [c for c in client.commands if "bootout" in c]
    assert len(bootouts) == 1
    assert "ai.clawrium.openclaw.o1" in bootouts[0]


def test_remove_service_macos_openclaw_skips_dashboard(monkeypatch):
    client = _FakeClient(responses=[(0, "", "") for _ in range(4)])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)

    ok, err = lifecycle_macos.remove_service_macos(
        {"hostname": "x"}, "o1", agent_type="openclaw"
    )
    assert ok is True
    assert err is None
    cmds = "\n".join(client.commands)
    assert "ai.clawrium.openclaw.o1" in cmds
    assert "dashboard" not in cmds


def test_restart_agent_macos_openclaw_skips_dashboard(monkeypatch):
    client = _FakeClient(responses=[(0, "", "")])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)

    ok, err = lifecycle_macos.restart_agent_macos(
        {"hostname": "x", "agents": {"o1": {"type": "openclaw", "config": {}}}},
        "o1",
        agent_type="openclaw",
    )
    assert ok is True
    cmds = "\n".join(client.commands)
    assert "ai.clawrium.openclaw.o1" in cmds
    assert "dashboard" not in cmds


def test_install_service_openclaw_routes_to_openclaw_template(monkeypatch):
    """B2: install_service(agent_type='openclaw') must select the
    openclaw plist template + .openclaw/logs dir, not the hermes paths."""
    captured: dict = {}

    def fake_render(agent_name, template_name="gateway.plist.j2", **kw):
        captured["template"] = template_name
        captured["agent_type"] = kw.get("agent_type")
        return "<plist/>"

    def fake_write(_c, _n, _contents, **kw):
        captured["write_agent_type"] = kw.get("agent_type")
        return "/Library/LaunchDaemons/ai.clawrium.openclaw.o1.plist"

    monkeypatch.setattr(lifecycle_macos, "render_plist", fake_render)
    monkeypatch.setattr(lifecycle_macos, "write_plist", fake_write)

    client = _FakeClient(responses=[(0, "", "")])
    path = lifecycle_macos.install_service(client, "o1", agent_type="openclaw")
    assert path.endswith("ai.clawrium.openclaw.o1.plist")
    assert captured["template"] == "openclaw.plist.j2"
    assert captured["agent_type"] == "openclaw"
    assert captured["write_agent_type"] == "openclaw"
    # The mkdir target must be the openclaw logs dir.
    mkdir_cmds = [c for c in client.commands if "mkdir" in c]
    assert mkdir_cmds and "/Users/o1/.openclaw/logs" in mkdir_cmds[0]
    assert "/.hermes/" not in mkdir_cmds[0]


def test_install_service_surfaces_logdir_failure(monkeypatch):
    """W6 regression: mkdir/chown failure must raise — silent pass leads
    to launchd ENOENT on StandardOutPath."""
    import pytest

    monkeypatch.setattr(lifecycle_macos, "render_plist", lambda *a, **k: "<p/>")
    monkeypatch.setattr(lifecycle_macos, "write_plist", lambda *a, **k: "/p")
    client = _FakeClient(responses=[(1, "", "permission denied")])
    with pytest.raises(RuntimeError, match="failed to prepare logs dir"):
        lifecycle_macos.install_service(client, "o1", agent_type="openclaw")


def test_configure_agent_openclaw_injects_openclaw_playbook(monkeypatch):
    """B3: configure_agent for claw_name='openclaw' must resolve the
    openclaw macOS playbook + restart with agent_type='openclaw'."""
    called: dict = {}

    def fake_core_configure(**kw):
        called["playbook"] = kw.get("playbook_path_override")
        return True, None

    fake_host = {
        "hostname": "x",
        "os_family": "darwin",
        "agents": {"o1": {"type": "openclaw", "agent_name": "o1", "config": {}}},
    }
    monkeypatch.setattr(
        "clawrium.core.lifecycle.configure_agent", fake_core_configure
    )
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _h: fake_host)

    restart_calls: list = []

    def fake_restart(host, agent_name, on_event=None, agent_type="hermes"):
        restart_calls.append((host["hostname"], agent_name, agent_type))
        return True, None

    monkeypatch.setattr(lifecycle_macos, "restart_agent_macos", fake_restart)

    ok, err = lifecycle_macos.configure_agent(
        hostname="x", claw_name="openclaw", config_data={}, agent_name="o1"
    )
    assert ok is True
    assert err is None
    assert "registry/openclaw/playbooks/configure_macos.yaml" in str(called["playbook"])
    assert restart_calls == [("x", "o1", "openclaw")]


def test_sync_agent_openclaw_injects_openclaw_playbook(monkeypatch):
    """B3 sibling: sync_agent for openclaw mirrors configure_agent."""
    sync_called: dict = {}

    def fake_core_sync(**kw):
        sync_called["playbook"] = kw.get("playbook_path_override")
        return {
            "success": True,
            "agent": "o1",
            "host": kw.get("hostname"),
            "operation": "sync",
        }

    fake_host = {
        "hostname": "x",
        "os_family": "darwin",
        "agents": {"o1": {"type": "openclaw", "agent_name": "o1", "config": {}}},
    }
    monkeypatch.setattr("clawrium.core.lifecycle.sync_agent", fake_core_sync)
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _h: fake_host)

    restart_calls: list = []
    monkeypatch.setattr(
        lifecycle_macos,
        "restart_agent_macos",
        lambda host, agent, on_event=None, agent_type="hermes": restart_calls.append(
            (host["hostname"], agent, agent_type)
        )
        or (True, None),
    )

    result = lifecycle_macos.sync_agent(
        hostname="x", claw_name="openclaw", agent_name="o1"
    )
    assert result["success"] is True
    assert "registry/openclaw/playbooks/configure_macos.yaml" in str(
        sync_called["playbook"]
    )
    assert restart_calls == [("x", "o1", "openclaw")]


def test_start_agent_macos_openclaw_kickstart_failure(monkeypatch):
    """B4: kickstart returning non-zero must surface as (False, error)
    without falsely reporting the daemon up."""
    monkeypatch.setattr(lifecycle_macos, "install_service", lambda *a, **k: "/p")
    client = _FakeClient(
        responses=[
            (0, "", ""),  # bootstrap ok
            (1, "", "kickstart broke"),  # kickstart fails
        ]
    )
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)

    ok, err = lifecycle_macos.start_agent_macos(
        {"hostname": "x"}, "o1", agent_type="openclaw"
    )
    assert ok is False
    assert err and "kickstart" in err
    assert "openclaw" in (err.lower() + "".join(client.commands).lower())


def test_stop_agent_macos_openclaw_real_error(monkeypatch):
    """B4: rc != 0 with non-"not loaded" stderr must surface as failure."""
    client = _FakeClient(responses=[(5, "", "Operation not permitted")])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)

    ok, err = lifecycle_macos.stop_agent_macos(
        {"hostname": "x"}, "o1", agent_type="openclaw"
    )
    assert ok is False
    assert err and "bootout" in err and "Operation not permitted" in err


def test_remove_service_macos_bails_on_real_bootout_error(monkeypatch):
    """B1 regression: bootout returning rc=5 (not "not loaded") must
    short-circuit BEFORE remove_plist runs — otherwise the daemon
    keeps running while hosts.json declares the agent gone."""
    deleted: list = []

    def fake_remove_plist(_c, _n, **kw):
        deleted.append(kw)

    monkeypatch.setattr(lifecycle_macos, "remove_plist", fake_remove_plist)
    client = _FakeClient(responses=[(5, "", "Operation not permitted")])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda _h: client)

    ok, err = lifecycle_macos.remove_service_macos(
        {"hostname": "x"}, "o1", agent_type="openclaw"
    )
    assert ok is False
    assert err and "bootout" in err
    # CRITICAL: plist not removed → operator sees a clear failure.
    assert deleted == []


def test_launchd_helpers_reject_shell_metacharacter_agent_name():
    """B5: defense-in-depth — agent_name with shell metacharacters must
    be refused by write_plist / remove_plist before any sudo runs."""
    import pytest

    from clawrium.core.launchd import _validate_agent_name

    for bad in ("a;rm -rf /", "a$(id)", "a b", "../x", "A1", "", "1abc"):
        with pytest.raises(ValueError, match="invalid agent_name"):
            _validate_agent_name(bad)

    # Sanity: real names pass.
    for good in ("o1", "openclaw-mactest", "h_1", "abc"):
        _validate_agent_name(good)
