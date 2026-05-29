"""Tests for core/lifecycle_macos.py (issue #469, step 7).

Covers:
  - resolve_lifecycle_backend dispatch.
  - launchctl command shape per operation (assert on the exact strings
    sent to paramiko.exec_command).
  - "already loaded" and "not loaded" tolerance.

E2E (actually invoking launchctl on a Mac) is covered by step 11's
slow nightly suite.
"""

from io import StringIO

import pytest

from clawrium.core import lifecycle_macos
from clawrium.core.launchd import label_for, plist_path_for
from clawrium.core.playbook_resolver import resolve_lifecycle_backend


class _Chan:
    def __init__(self, exit_status: int = 0):
        self.exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self.exit_status


class _Out:
    def __init__(self, content: str = "", exit_status: int = 0):
        self._content = content.encode()
        self.channel = _Chan(exit_status)

    def read(self) -> bytes:
        return self._content


class _FakeClient:
    """Records every exec_command invocation; returns scripted responses."""

    def __init__(self, responses: list[tuple[int, str, str]] | None = None):
        self.commands: list[str] = []
        self._responses = list(responses or [])

    def exec_command(self, cmd):  # noqa: ANN001
        self.commands.append(cmd)
        if self._responses:
            rc, out, err = self._responses.pop(0)
        else:
            rc, out, err = 0, "", ""
        return StringIO(), _Out(out, rc), _Out(err, rc)

    # Methods needed by paramiko-compatible context use; lifecycle_macos
    # calls .close() in a finally block. SFTP is not exercised in these
    # tests (write_plist is tested separately in test_launchd).
    def close(self):
        pass

    def open_sftp(self):  # used only by install_service via write_plist
        raise RuntimeError("SFTP not exercised in this unit test")


def test_resolve_lifecycle_backend_linux():
    backend = resolve_lifecycle_backend("linux")
    assert backend.__name__ == "clawrium.core.lifecycle"


def test_resolve_lifecycle_backend_darwin():
    backend = resolve_lifecycle_backend("darwin")
    assert backend is lifecycle_macos


def test_resolve_lifecycle_backend_unknown_raises():
    with pytest.raises(ValueError, match="unsupported"):
        resolve_lifecycle_backend("windows")


def test_bootstrap_command_shape():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._bootstrap(client, "h1")
    assert client.commands == [
        f"sudo launchctl bootstrap system {plist_path_for('h1')}"
    ]


def test_bootout_command_shape():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._bootout(client, "h1")
    assert client.commands == [
        f"sudo launchctl bootout system/{label_for('h1')}"
    ]


def test_kickstart_command_shape_kill_false():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._kickstart(client, "h1", kill=False)
    assert client.commands == [
        f"sudo launchctl kickstart system/{label_for('h1')}"
    ]


def test_kickstart_command_shape_kill_true():
    client = _FakeClient(responses=[(0, "", "")])
    lifecycle_macos._kickstart(client, "h1", kill=True)
    assert client.commands == [
        f"sudo launchctl kickstart -k system/{label_for('h1')}"
    ]


def test_stop_tolerates_not_loaded(monkeypatch):
    """`launchctl bootout` against an absent unit must return success."""
    client = _FakeClient(
        responses=[(113, "", "Could not find service\n")]
    )
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    ok, err = lifecycle_macos.stop_agent_macos({"hostname": "x"}, "h1")
    assert ok is True
    assert err is None


def test_stop_reports_real_error():
    """Non-not-loaded errors must surface."""

    class _C(_FakeClient):
        pass

    client = _C(responses=[(2, "", "permission denied\n")])
    import clawrium.core.lifecycle_macos as lm

    original_ssh = lm._ssh
    lm._ssh = lambda host: client
    try:
        ok, err = lm.stop_agent_macos({"hostname": "x"}, "h1")
    finally:
        lm._ssh = original_ssh

    assert ok is False
    assert "permission denied" in (err or "")


# ===== B7: restart_agent_macos coverage =====
# happy path (kickstart succeeds) + cold-host fallback path
# (kickstart fails with "could not find service" → install + bootstrap).


def test_restart_macos_kickstart_when_loaded(monkeypatch):
    """Happy path: both labels are loaded, kickstart -k for each succeeds."""
    # Responses are consumed in order for every _run / exec_command.
    # restart_agent_macos with dashboard_port iterates ("dashboard",
    # "gateway") — exactly two kickstart -k calls. Both rc=0.
    client = _FakeClient(responses=[(0, "", ""), (0, "", "")])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    host = {
        "hostname": "x",
        "agents": {"h1": {"config": {"dashboard": {"port": 45112}}}},
    }
    ok, err = lifecycle_macos.restart_agent_macos(host, "h1")
    assert ok is True
    assert err is None
    # Exactly two kickstart -k commands; no install_service path.
    assert len(client.commands) == 2
    assert all("kickstart -k" in c for c in client.commands)
    assert "system/ai.clawrium.hermes.h1.dashboard" in client.commands[0]
    assert "system/ai.clawrium.hermes.h1" in client.commands[1]


def test_restart_macos_falls_back_to_bootstrap_when_not_loaded(monkeypatch):
    """Cold host (kickstart fails with 'could not find service') → fallback
    re-installs both plists and bootstraps both labels."""
    # First kickstart -k (dashboard) returns "not loaded" → trigger fallback.
    # Then: install_service writes both plists (2 exec_commands: sudo
    #   install gateway, sudo install dashboard, plus the logs mkdir),
    #   then bootstrap dashboard (rc=0), kickstart dashboard (rc=0),
    #   bootstrap gateway (rc=0), kickstart gateway (rc=0).
    # SFTP path is exercised by install_service via the real write_plist;
    # mock that path off so the test stays unit-level.
    client = _FakeClient(
        responses=[
            (113, "", "Could not find service\n"),  # kickstart -k dashboard
            # install_service body: sudo install gateway, then sudo install
            # dashboard, then sudo mkdir + chown logs dir → 3 _run calls.
            (0, "", ""),
            (0, "", ""),
            (0, "", ""),
            (0, "", ""),  # bootstrap dashboard
            (0, "", ""),  # kickstart dashboard
            (0, "", ""),  # bootstrap gateway
            (0, "", ""),  # kickstart gateway
        ]
    )

    # Patch write_plist (SFTP) and render_plist (jinja2) so the test
    # focuses on the launchctl command sequence shape.
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)
    monkeypatch.setattr(
        lifecycle_macos, "write_plist", lambda c, n, contents, **kw: "/tmp/dummy"
    )
    monkeypatch.setattr(
        lifecycle_macos, "render_plist", lambda *a, **kw: "<plist/>"
    )

    host = {
        "hostname": "x",
        "agents": {"h1": {"config": {"dashboard": {"port": 45112}}}},
    }
    ok, err = lifecycle_macos.restart_agent_macos(host, "h1")
    assert ok is True, err

    cmd_log = "\n".join(client.commands)
    # The fallback must touch both labels' bootstrap path.
    assert "launchctl bootstrap system" in cmd_log
    assert "ai.clawrium.hermes.h1.dashboard" in cmd_log
    # And a kickstart for the gateway too.
    assert "system/ai.clawrium.hermes.h1" in cmd_log


# ===== B8: stop iterates dashboard before gateway =====


def test_stop_agent_macos_boots_out_dashboard_then_gateway(monkeypatch):
    """When a dashboard is configured, stop must bootout dashboard FIRST,
    then gateway. Confirms the explicit iteration order in
    stop_agent_macos so launchd lifecycle isn't reversed."""
    client = _FakeClient(responses=[(0, "", ""), (0, "", "")])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    host = {
        "hostname": "x",
        "agents": {"h1": {"config": {"dashboard": {"port": 45112}}}},
    }
    ok, err = lifecycle_macos.stop_agent_macos(host, "h1")
    assert ok is True
    assert err is None
    assert len(client.commands) == 2
    # Order is invariant: dashboard then gateway.
    assert "ai.clawrium.hermes.h1.dashboard" in client.commands[0]
    assert client.commands[1].endswith("system/ai.clawrium.hermes.h1")


# ===== B9: _bootstrap_with_tolerance variants =====


@pytest.mark.parametrize(
    ("rc", "stderr", "expected_ok", "error_marker"),
    [
        (37, "Service already loaded\n", True, None),
        (5, "Bootstrap failed: 5: Input/output error\n", True, None),
        (2, "Bootstrap failed: permission denied\n", False, "permission denied"),
    ],
)
def test_bootstrap_with_tolerance_variants(monkeypatch, rc, stderr, expected_ok, error_marker):
    client = _FakeClient(responses=[(rc, "", stderr)])
    monkeypatch.setattr(lifecycle_macos, "_ssh", lambda host: client)

    ok, err = lifecycle_macos._bootstrap_with_tolerance(client, "h1", kind="gateway")
    assert ok is expected_ok
    if expected_ok:
        assert err is None
    else:
        assert error_marker in (err or "")


# ===== Iteration 3 B5: configure_agent / sync_agent restart wiring =====


def test_configure_agent_injects_macos_playbook_and_restarts(monkeypatch):
    """`lifecycle_macos.configure_agent` MUST (a) inject the macOS configure
    playbook via `playbook_path_override` and (b) call
    `restart_agent_macos` exactly once after a successful core configure."""
    called: dict = {}

    def fake_core_configure(**kwargs):
        called["playbook"] = kwargs.get("playbook_path_override")
        called["claw_name"] = kwargs.get("claw_name")
        return True, None

    fake_host = {
        "hostname": "x",
        "os_family": "darwin",
        "agents": {"h1": {"type": "hermes", "agent_name": "h1", "config": {}}},
    }
    monkeypatch.setattr(
        "clawrium.core.lifecycle.configure_agent", fake_core_configure
    )
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _h: fake_host)

    restart_calls: list = []

    def fake_restart(host, agent_name, on_event=None):
        restart_calls.append((host["hostname"], agent_name))
        return True, None

    monkeypatch.setattr(lifecycle_macos, "restart_agent_macos", fake_restart)

    ok, err = lifecycle_macos.configure_agent(
        hostname="x", claw_name="hermes", config_data={}, agent_name="h1"
    )
    assert ok is True
    assert err is None
    # macOS playbook injected (configure_macos.yaml path).
    assert called["playbook"] is not None
    assert "configure_macos.yaml" in str(called["playbook"])
    # restart_agent_macos called exactly once.
    assert restart_calls == [("x", "h1")]


def test_configure_agent_propagates_core_failure(monkeypatch):
    """A core configure failure must surface and NOT trigger restart."""

    def fake_core_configure(**_):
        return False, "ansible exit 2"

    monkeypatch.setattr(
        "clawrium.core.lifecycle.configure_agent", fake_core_configure
    )

    restart_calls: list = []
    monkeypatch.setattr(
        lifecycle_macos,
        "restart_agent_macos",
        lambda *a, **kw: restart_calls.append("called") or (True, None),
    )

    ok, err = lifecycle_macos.configure_agent(
        hostname="x", claw_name="hermes", config_data={}, agent_name="h1"
    )
    assert ok is False
    assert "ansible exit 2" in (err or "")
    assert restart_calls == []  # restart NOT attempted on configure failure


def test_configure_agent_surfaces_restart_failure(monkeypatch):
    """If restart_agent_macos fails after a clean configure, that error
    must bubble up — silent success is unacceptable."""
    monkeypatch.setattr(
        "clawrium.core.lifecycle.configure_agent",
        lambda **_kw: (True, None),
    )
    fake_host = {
        "hostname": "x",
        "os_family": "darwin",
        "agents": {"h1": {"type": "hermes", "agent_name": "h1", "config": {}}},
    }
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _h: fake_host)
    monkeypatch.setattr(
        lifecycle_macos,
        "restart_agent_macos",
        lambda *a, **kw: (False, "launchctl bootout (gateway) failed"),
    )

    ok, err = lifecycle_macos.configure_agent(
        hostname="x", claw_name="hermes", config_data={}, agent_name="h1"
    )
    assert ok is False
    assert "Post-configure restart failed" in (err or "")
    assert "launchctl bootout" in (err or "")


def test_sync_agent_injects_macos_playbook_and_restarts(monkeypatch):
    """`lifecycle_macos.sync_agent` mirrors configure_agent's contract:
    inject the macOS playbook, then restart on success."""
    sync_called: dict = {}

    def fake_core_sync(**kwargs):
        sync_called["playbook"] = kwargs.get("playbook_path_override")
        return {
            "success": True,
            "agent": "h1",
            "host": kwargs.get("hostname"),
            "operation": "sync",
            "error": None,
        }

    fake_host = {
        "hostname": "x",
        "os_family": "darwin",
        "agents": {"h1": {"type": "hermes", "agent_name": "h1", "config": {}}},
    }
    monkeypatch.setattr("clawrium.core.lifecycle.sync_agent", fake_core_sync)
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _h: fake_host)

    restart_calls: list = []
    monkeypatch.setattr(
        lifecycle_macos,
        "restart_agent_macos",
        lambda host, agent, on_event=None: restart_calls.append((host["hostname"], agent)) or (True, None),
    )

    result = lifecycle_macos.sync_agent(
        hostname="x", claw_name="hermes", agent_name="h1"
    )
    assert result["success"] is True
    assert "configure_macos.yaml" in str(sync_called["playbook"])
    assert restart_calls == [("x", "h1")]


def test_sync_agent_skips_restart_on_core_failure(monkeypatch):
    monkeypatch.setattr(
        "clawrium.core.lifecycle.sync_agent",
        lambda **kw: {
            "success": False,
            "agent": "h1",
            "host": kw.get("hostname"),
            "operation": "sync",
            "error": "Configure failed: ansible exit 2",
        },
    )
    restart_calls: list = []
    monkeypatch.setattr(
        lifecycle_macos,
        "restart_agent_macos",
        lambda *a, **kw: restart_calls.append("called") or (True, None),
    )

    result = lifecycle_macos.sync_agent(
        hostname="x", claw_name="hermes", agent_name="h1"
    )
    assert result["success"] is False
    assert restart_calls == []


def test_sync_agent_surfaces_restart_failure(monkeypatch):
    """ATX iter-3 B6: mirror of `test_configure_agent_surfaces_restart_failure`.
    If `restart_agent_macos` fails after a clean core sync, the sync
    result MUST flip to success=False with an error mentioning the
    restart failure — silent success would let a stale daemon
    masquerade as a successful sync."""
    monkeypatch.setattr(
        "clawrium.core.lifecycle.sync_agent",
        lambda **kw: {
            "success": True,
            "agent": "h1",
            "host": kw.get("hostname"),
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": None,
        },
    )
    fake_host = {
        "hostname": "x",
        "os_family": "darwin",
        "agents": {"h1": {"type": "hermes", "agent_name": "h1", "config": {}}},
    }
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _h: fake_host)
    monkeypatch.setattr(
        lifecycle_macos,
        "restart_agent_macos",
        lambda *a, **kw: (False, "launchctl bootout (gateway) failed"),
    )

    result = lifecycle_macos.sync_agent(
        hostname="x", claw_name="hermes", agent_name="h1"
    )
    assert result["success"] is False
    assert "Post-sync restart failed" in (result.get("error") or "")
    assert "launchctl bootout" in (result.get("error") or "")


# ===== Iteration 3 B4 (warning): static-grep invariant =====


def test_lifecycle_module_has_no_darwin_branches():
    """ATX iter-2: regression guard for the dispatcher-only OS fork rule
    (.itx/469/01_EXECUTION.md §Decisions item 2). No `if Darwin`-style
    branch may live in core/lifecycle.py."""
    import re
    from pathlib import Path

    from clawrium.core import lifecycle as _lifecycle

    source = Path(_lifecycle.__file__).read_text()
    # Strip docstring / comment mentions — they are descriptive, not
    # branching. The invariant targets executable code: `if .*darwin`
    # in an `if`/`elif` statement.
    code_lines = [
        line
        for line in source.splitlines()
        if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    pattern = re.compile(r"^\s*(?:if|elif)\b.*\bdarwin\b", re.IGNORECASE | re.MULTILINE)
    matches = pattern.findall(code)
    assert matches == [], (
        f"core/lifecycle.py must not branch on Darwin (found {matches}). "
        "Move OS-family dispatch to the CLI layer via "
        "resolve_lifecycle_backend(os_family)."
    )
