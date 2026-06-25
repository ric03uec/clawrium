"""Tests for the macOS dispatch path in `core/lifecycle_canonical.py`.

The canonical sync pipeline branches on `host['hardware']['os'] == 'macos'`
at three points (atomic file replace, unit restart, health verify) and
routes to helpers in `lifecycle_macos.py` rather than running the Linux
systemctl/`-g {agent_name}` path. This module asserts the exact wire
commands issued on the macOS branch, the dual-label restart for hermes,
the bootstrap-fallback on a not-loaded unit, and the nc-probe behavior
for verify_health.

The Linux path is already covered by tests in `test_lifecycle_canonical.py`
and `test_workspace_*.py`; this file pins the macOS leg so the
dispatcher-only OS fork invariant (AGENTS.md) cannot regress silently.
"""

from __future__ import annotations

from io import StringIO

import pytest

from clawrium.core import lifecycle_canonical as lc
from clawrium.core import lifecycle_macos as lm
from clawrium.core.launchd import label_for


class _Stream:
    def __init__(self, payload: bytes = b"", exit_status: int = 0) -> None:
        self._payload = payload

        class _Ch:
            def __init__(self, rc):
                self._rc = rc

            def recv_exit_status(self):
                return self._rc

        self.channel = _Ch(exit_status)

    def read(self) -> bytes:
        return self._payload


class _SftpFile:
    def __init__(self, written: dict[str, bytes], path: str) -> None:
        self._written = written
        self._path = path
        self._buf: list[bytes] = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self._written[self._path] = b"".join(self._buf)
        return False

    def write(self, data: bytes) -> None:
        self._buf.append(data)


class _Sftp:
    def __init__(self, written: dict[str, bytes]) -> None:
        self._written = written
        self.closed = False

    def file(self, path: str, mode: str):
        return _SftpFile(self._written, path)

    def close(self):
        self.closed = True


class _Client:
    """Fake paramiko SSHClient. Each entry in `script` is
    (substring, exit_status, stdout_bytes, stderr_bytes). First match
    is consumed. Unmatched commands raise so a typo fails loudly."""

    def __init__(
        self,
        script: list[tuple[str, int, bytes, bytes]] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._script = list(script or [])
        self.sftp_writes: dict[str, bytes] = {}

    def exec_command(self, cmd: str, timeout: int | None = None):
        self.calls.append(cmd)
        for i, (needle, rc, out, err) in enumerate(self._script):
            if needle in cmd:
                self._script.pop(i)
                return StringIO(), _Stream(out, rc), _Stream(err, rc)
        raise AssertionError(f"unscripted command: {cmd!r}")

    def open_sftp(self):
        return _Sftp(self.sftp_writes)


class _FailingSftp:
    """Sftp stub whose `file()` raises — exercises the SFTP-failure
    branch in atomic_write_macos (W9)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.closed = False

    def file(self, path: str, mode: str):
        raise self._exc

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# _atomic_write: macOS uses group="staff" (not per-user group)
# ---------------------------------------------------------------------------


class TestAtomicWriteMacosDispatch:
    @pytest.mark.parametrize(
        "os_value, expected_group_flag, expected_dir_root, pass_host",
        [
            # ATX W12: parametrize the OS branch so a regression that
            # drops one side of the dispatch is caught by the same test.
            ("macos", "-g staff", "/Users/", True),
            ("ubuntu", "-g alpha", "/home/", True),
            ("debian", "-g alpha", "/home/", True),
            # S5 iter-3: when `host=None` the dispatcher must fall
            # through to the Linux path (per-user group). A regression
            # that defaulted to macOS would corrupt Linux hosts.
            (None, "-g alpha", "/home/", False),
        ],
    )
    def test_install_command_group_flag_per_os(
        self, os_value, expected_group_flag, expected_dir_root, pass_host
    ):
        client = _Client(
            [
                ("mktemp", 0, b"/tmp/clawrium-sync.XYZ\n", b""),
                ("install", 0, b"", b""),
                ("rm -f", 0, b"", b""),
            ]
        )
        host = (
            {"hostname": "h", "hardware": {"os": os_value}} if pass_host else None
        )
        lc._atomic_write(
            client,
            agent_name="alpha",
            remote_path=f"{expected_dir_root}alpha/.openclaw/env",
            body="X=1\n",
            host=host,
        )
        install_call = next(c for c in client.calls if "install" in c)
        assert "-o alpha" in install_call
        assert expected_group_flag in install_call
        # Body must have been pushed via SFTP to the mktemp path on
        # both branches.
        assert client.sftp_writes == {"/tmp/clawrium-sync.XYZ": b"X=1\n"}

    def test_install_failure_raises_canonical_error_on_macos(self):
        client = _Client(
            [
                ("mktemp", 0, b"/tmp/clawrium-sync.X\n", b""),
                ("install", 1, b"", b"chown: invalid group: 'staff'\n"),
                ("rm -f", 0, b"", b""),
            ]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(lc.CanonicalSyncError, match=r"install .* failed"):
            lc._atomic_write(
                client,
                agent_name="alpha",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )

    def test_install_failure_includes_stderr_detail_after_drain(self):
        """W2 ordering test — error surface must include stderr text
        AFTER `recv_exit_status`, proving the drain ordering didn't
        accidentally drop the diagnostic body."""
        client = _Client(
            [
                ("mktemp", 0, b"/tmp/clawrium-sync.X\n", b""),
                ("install", 1, b"", b"sudo: a password is required\n"),
                ("rm -f", 0, b"", b""),
            ]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"sudo: a password is required",
        ):
            lc._atomic_write(
                client,
                agent_name="alpha",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )

    # W9: failure branches that previously had zero coverage.

    def test_mktemp_nonzero_exit_includes_stderr(self):
        """mktemp rc != 0 → CanonicalSyncError with stderr text."""
        client = _Client([("mktemp", 1, b"", b"mktemp: too many templates\n")])
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"mktemp failed on host.*too many templates",
        ):
            lc._atomic_write(
                client,
                agent_name="alpha",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )

    def test_mktemp_empty_stdout_is_rejected(self):
        """A transient SSH glitch returning `b''` from mktemp would
        pass an rc==0 guard naively, then `install` would write the
        body to `""`. The empty-path guard rejects this case loudly."""
        client = _Client([("mktemp", 0, b"\n", b"")])
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"mktemp returned empty path",
        ):
            lc._atomic_write(
                client,
                agent_name="alpha",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )

    def test_invalid_agent_name_rejected_before_any_ssh_command(self):
        """B3 (ATX iter-3): `atomic_write_macos` must call
        `_validate_agent_name` at function entry, refusing shell
        metacharacters BEFORE any SSH command runs. A regression that
        dropped the call would let `a;rm -rf /` reach the install
        command's `-o` argument. Asserts both the ValueError raise and
        zero SSH calls executed (no mktemp leak, no install attempt)."""
        client = _Client()  # empty script — any exec_command would fail
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(ValueError, match=r"invalid agent_name"):
            lc._atomic_write(
                client,
                agent_name="a;rm -rf /",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )
        assert client.calls == [], (
            "validation must happen before any SSH command"
        )

    def test_mktemp_returns_unsafe_path_rejected(self):
        """B1 (ATX iter-3): defense-in-depth against a hostile or
        malfunctioning host returning a path OUTSIDE
        `/tmp/clawrium-sync.*` from mktemp. Without the prefix guard
        the subsequent `sudo -n install` would overwrite that path
        with `body` — e.g. clobbering the operator's
        ~/.openclaw/openclaw.json with the rendered .env."""
        client = _Client(
            [
                ("mktemp", 0, b"/Users/alpha/.openclaw/openclaw.json\n", b""),
            ]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"unsafe path.*expected prefix '/tmp/clawrium-sync.'",
        ):
            lc._atomic_write(
                client,
                agent_name="alpha",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )
        # The install command must NOT have run.
        assert not any("install" in c for c in client.calls), client.calls

    def test_sftp_open_failure_surfaces_and_cleans_up(self, monkeypatch):
        """If SFTP `file()` raises (channel torn down mid-handshake,
        quota exceeded, etc.) the exception must propagate AND the
        mktemp tmpfile must still be cleaned up via the finally
        block."""

        class _ClientWithFailingSftp(_Client):
            def open_sftp(self):
                return _FailingSftp(IOError("sftp channel closed"))

        client = _ClientWithFailingSftp(
            [
                ("mktemp", 0, b"/tmp/clawrium-sync.X\n", b""),
                ("rm -f /tmp/clawrium-sync.X", 0, b"", b""),
            ]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(IOError, match=r"sftp channel closed"):
            lc._atomic_write(
                client,
                agent_name="alpha",
                remote_path="/Users/alpha/.openclaw/env",
                body="x",
                host=host,
            )
        # Finally block must have fired the rm.
        assert any("rm -f /tmp/clawrium-sync.X" in c for c in client.calls)


# ---------------------------------------------------------------------------
# _restart_unit: launchctl kickstart with dual-label (hermes) + fallback
# ---------------------------------------------------------------------------


class TestRestartUnitMacosDispatch:
    def test_openclaw_macos_kickstarts_gateway_label_only(self):
        client = _Client(
            [("launchctl kickstart -k", 0, b"", b"")]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}, "agents": {}}
        lc._restart_unit(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            host=host,
        )
        expected_label = label_for("alpha", kind="gateway", agent_type="openclaw")
        assert any(
            f"system/{expected_label}" in c and "kickstart -k" in c
            for c in client.calls
        ), client.calls

    def test_hermes_macos_kickstarts_dashboard_then_gateway_in_order(self):
        """Hermes runs two launchd units on macOS; sync must restart
        both. Order matters: `dashboard` before `gateway` mirrors the
        existing `restart_agent_macos` invariant, and a flipped order
        reopens a window where the gateway runs ahead of the dashboard
        with mismatched config (S11)."""
        client = _Client(
            [
                ("launchctl kickstart -k", 0, b"", b""),
                ("launchctl kickstart -k", 0, b"", b""),
            ]
        )
        host = {
            "hostname": "h",
            "hardware": {"os": "macos"},
            "agents": {
                "alpha": {
                    "type": "hermes",
                    "config": {"dashboard": {"port": 45123}},
                }
            },
        }
        lc._restart_unit(
            client,
            agent_type="hermes",
            agent_name="alpha",
            host=host,
        )
        gateway_label = label_for("alpha", kind="gateway", agent_type="hermes")
        dashboard_label = label_for("alpha", kind="dashboard", agent_type="hermes")
        kick_calls = [c for c in client.calls if "kickstart -k" in c]
        assert len(kick_calls) == 2
        # S11: pin the order, not just "both appeared".
        assert dashboard_label in kick_calls[0], (
            f"dashboard must be first; got order: {kick_calls}"
        )
        assert gateway_label in kick_calls[1]

    def test_kickstart_not_loaded_triggers_bootstrap_then_kickstart(
        self, monkeypatch
    ):
        """W10: assert the fallback path actually fires `bootstrap` AND
        `kickstart` on the wire, not just that `install_service` was
        called. A regression that called install_service but skipped
        the bootstrap+kickstart pair would leave the unit installed-
        but-not-running and pass the earlier weaker assertion."""
        client = _Client(
            [
                ("launchctl kickstart -k", 113, b"", b"Could not find service\n"),
                ("launchctl bootstrap", 0, b"", b""),
                ("launchctl kickstart", 0, b"", b""),
            ]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}, "agents": {}}

        install_calls: list[tuple] = []

        def _fake_install_service(
            c, name, *, dashboard_port=None, agent_type="hermes", timeout=None
        ):
            install_calls.append((name, dashboard_port, agent_type))
            return "/Library/LaunchDaemons/ai.clawrium.openclaw.alpha.plist"

        monkeypatch.setattr(lm, "install_service", _fake_install_service)

        lc._restart_unit(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            host=host,
        )
        # install_service called once.
        assert install_calls == [("alpha", None, "openclaw")]
        # Bootstrap fired AFTER the install_service step.
        assert any("launchctl bootstrap" in c for c in client.calls), client.calls
        # And the recovery kickstart (without -k) fired AFTER bootstrap.
        recovery_kicks = [
            c for c in client.calls
            if "launchctl kickstart" in c and "kickstart -k" not in c
        ]
        assert len(recovery_kicks) == 1, recovery_kicks

    def test_hermes_dual_label_bootstrap_fallback_covers_both_kinds(
        self, monkeypatch
    ):
        """W10: hermes' two-label fallback must bootstrap+kickstart
        BOTH dashboard and gateway. A regression that only fell back on
        one label would silently leave the other absent."""
        client = _Client(
            [
                # First kickstart -k (dashboard) reports not-loaded
                # → fallback kicks in for both labels.
                ("launchctl kickstart -k", 113, b"", b"Could not find service\n"),
                # Two bootstrap + kickstart pairs (dashboard, gateway).
                ("launchctl bootstrap", 0, b"", b""),
                ("launchctl kickstart", 0, b"", b""),
                ("launchctl bootstrap", 0, b"", b""),
                ("launchctl kickstart", 0, b"", b""),
            ]
        )
        host = {
            "hostname": "h",
            "hardware": {"os": "macos"},
            "agents": {
                "alpha": {
                    "type": "hermes",
                    "config": {"dashboard": {"port": 45123}},
                }
            },
        }
        monkeypatch.setattr(
            lm,
            "install_service",
            lambda c, name, *, dashboard_port=None, agent_type="hermes", timeout=None: "/L/H.plist",
        )
        lc._restart_unit(
            client,
            agent_type="hermes",
            agent_name="alpha",
            host=host,
        )
        bootstrap_calls = [c for c in client.calls if "launchctl bootstrap" in c]
        recovery_kicks = [
            c for c in client.calls
            if "launchctl kickstart" in c and "kickstart -k" not in c
        ]
        assert len(bootstrap_calls) == 2, bootstrap_calls
        assert len(recovery_kicks) == 2, recovery_kicks

    def test_bootstrap_with_tolerance_failure_during_fallback_raises(
        self, monkeypatch
    ):
        """W10: the fallback's `_bootstrap_with_tolerance` can still
        fail hard (e.g. malformed plist, rc=5 + 'configuration
        invalid'). That failure must surface as CanonicalSyncError,
        not be swallowed."""
        client = _Client(
            [
                ("launchctl kickstart -k", 113, b"", b"Could not find service\n"),
                ("launchctl bootstrap", 78, b"", b"Bootstrap failed: invalid plist\n"),
            ]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}, "agents": {}}
        monkeypatch.setattr(
            lm,
            "install_service",
            lambda c, name, *, dashboard_port=None, agent_type="hermes", timeout=None: "/L/O.plist",
        )
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"launchctl bootstrap.*failed.*invalid plist",
        ):
            lc._restart_unit(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                host=host,
            )

    def test_kickstart_real_failure_raises_canonical_error(self):
        """An error that is NOT 'not loaded' must surface — operator
        needs to know the daemon refused to start."""
        client = _Client(
            [("launchctl kickstart -k", 1, b"", b"permission denied\n")]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}, "agents": {}}
        with pytest.raises(lc.CanonicalSyncError, match=r"kickstart.*permission denied"):
            lc._restart_unit(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                host=host,
            )

    def test_invalid_agent_name_rejected_via_validate(self):
        """Defense-in-depth (W1/W12): both atomic_write_macos AND
        restart_unit_macos must call `_validate_agent_name` up-front.
        Tested for the restart path here; atomic_write coverage is
        below."""
        client = _Client()
        host = {"hostname": "h", "hardware": {"os": "macos"}, "agents": {}}
        with pytest.raises(ValueError, match=r"invalid agent_name"):
            lc._restart_unit(
                client,
                agent_type="openclaw",
                agent_name="a;rm -rf /",
                host=host,
            )

    def test_unsupported_agent_type_for_macos_raises_canonical_error(
        self, monkeypatch
    ):
        """W4: `label_for` raises `ValueError` for unsupported
        (agent_type, kind) combos (e.g. zeroclaw on macOS — no
        launchd backend). The dispatcher must catch and re-raise as
        CanonicalSyncError so sync_agent_canonical's error path
        handles it uniformly."""
        client = _Client()
        host = {"hostname": "h", "hardware": {"os": "macos"}, "agents": {}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"unsupported launchd label.*zeroclaw",
        ):
            lc._restart_unit(
                client,
                agent_type="zeroclaw",
                agent_name="alpha",
                host=host,
            )


# ---------------------------------------------------------------------------
# _verify_health: nc -z port poll on macOS
# ---------------------------------------------------------------------------


def _stub_monotonic(monkeypatch, ticks: list[float]) -> list[float]:
    """W11: replace the brittle 3-element-iterator + dead hasattr
    pattern with a single counted stub. Pops one value per call;
    `StopIteration` here means the test under-fed ticks (bug in the
    test), so raising loudly is correct.

    S7 (ATX iter-3): this stub assumes `verify_health_macos` calls
    `time.monotonic` via the module-level `time` import (which it does
    via the local alias `import time as _time` resolved per-call).
    A refactor that rebinds with `from time import monotonic` at
    module load would bypass this patch, and timeout tests would
    silently no-op (the wall clock would advance instead). If
    `verify_health_macos` is ever changed to a from-import,
    `monkeypatch.setattr` here must be re-pointed at the function-local
    reference too."""
    import time as time_mod

    feed = list(ticks)

    def _next_tick() -> float:
        if not feed:
            raise AssertionError(
                "test under-fed monotonic ticks — extend the list"
            )
        return feed.pop(0)

    monkeypatch.setattr(time_mod, "monotonic", _next_tick)
    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)
    return feed


class TestVerifyHealthMacosDispatch:
    def test_nc_connect_returns_immediately_on_first_poll(self, monkeypatch):
        client = _Client([("nc -z -w 1 127.0.0.1 40510", 0, b"", b"")])
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            host=host,
            gateway_port=40510,
        )
        assert any("nc -z -w 1 127.0.0.1 40510" in c for c in client.calls)
        # Exactly one probe — happy path is one round trip.
        assert sum(1 for c in client.calls if "nc -z" in c) == 1

    def test_nc_delayed_success_exercises_polling_loop(self, monkeypatch):
        """S10: a regression that short-circuited on the first non-zero
        rc would pass `test_nc_connect_returns_immediately` (no nc
        failure there) but break here. This delayed-success case fails
        nc twice, then succeeds, and asserts the loop kept polling."""
        client = _Client(
            [
                ("nc -z -w 1 127.0.0.1 40510", 1, b"", b""),
                ("nc -z -w 1 127.0.0.1 40510", 1, b"", b""),
                ("nc -z -w 1 127.0.0.1 40510", 0, b"", b""),
            ]
        )
        # Feed: initial deadline calc + 3 loop-head checks (well under
        # deadline) + headroom. We never miss the deadline before nc
        # returns 0.
        _stub_monotonic(monkeypatch, [0.0] + [1.0, 2.0, 3.0])

        host = {"hostname": "h", "hardware": {"os": "macos"}}
        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            host=host,
            gateway_port=40510,
            timeout=30,
        )
        nc_calls = [c for c in client.calls if "nc -z" in c]
        assert len(nc_calls) == 3, nc_calls

    def test_timeout_raises_canonical_error(self, monkeypatch):
        """Port never opens → operator gets a precise error naming the
        port rather than a stuck sync. W11: uses the new counted stub
        instead of the fragile shared iterator pattern."""
        client = _Client(
            [("nc -z -w 1 127.0.0.1 40510", 1, b"", b"")]
        )
        # Feed: initial deadline calc returns 0.0 (deadline = 1.0),
        # then the loop check returns 999.0 (past deadline → exit).
        _stub_monotonic(monkeypatch, [0.0, 999.0])

        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"gateway port 40510 not accepting connections",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                host=host,
                gateway_port=40510,
                timeout=1,
            )

    @pytest.mark.parametrize(
        "stderr_text",
        [
            # bash / zsh shape
            b"bash: nc: command not found\n",
            # BusyBox / dash / sh shape — `nc: not found`
            b"sh: nc: not found\n",
            # macOS shape (rare, but matches the precise regex)
            b"-bash: nc: command not found\n",
        ],
    )
    def test_nc_missing_breaks_early_with_diagnostic(
        self, monkeypatch, stderr_text
    ):
        """W5 + W6 iter-3: if `nc` is not on PATH the stderr text
        matches one of several shell-prelude shapes. The helper must
        break early with a diagnostic pointing at the tool — not
        retry until the 30s deadline and then misdirect the operator
        at the daemon. Parametrized across both `command not found`
        (bash/zsh) and `not found` (BusyBox/dash) variants."""
        client = _Client(
            [
                (
                    "nc -z -w 1 127.0.0.1 40510",
                    127,
                    b"",
                    stderr_text,
                )
            ]
        )
        _stub_monotonic(monkeypatch, [0.0, 0.5])

        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"`nc` is not available",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                host=host,
                gateway_port=40510,
                timeout=30,
            )
        # MUST break on the first probe — not retry until the deadline.
        assert sum(1 for c in client.calls if "nc -z" in c) == 1

    def test_nc_connection_refused_does_not_match_missing_diagnostic(
        self, monkeypatch
    ):
        """W1 iter-3: the regex must NOT match BSD `nc: connect to
        127.0.0.1 port N (tcp) failed: Connection refused` — that is
        the expected "daemon not yet listening" stderr and the loop
        must keep retrying until the deadline, not bail early."""
        client = _Client(
            [
                (
                    "nc -z -w 1 127.0.0.1 40510",
                    1,
                    b"",
                    b"nc: connect to 127.0.0.1 port 40510 (tcp) failed: "
                    b"Connection refused\n",
                ),
                (
                    "nc -z -w 1 127.0.0.1 40510",
                    0,
                    b"",
                    b"",
                ),
            ]
        )
        _stub_monotonic(monkeypatch, [0.0, 1.0, 2.0])

        host = {"hostname": "h", "hardware": {"os": "macos"}}
        # Must NOT raise — must keep polling and then succeed.
        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            host=host,
            gateway_port=40510,
            timeout=30,
        )
        assert sum(1 for c in client.calls if "nc -z" in c) == 2

    def test_missing_gateway_port_raises_canonical_error(self):
        """W2 iter-3: a missing persisted port on macOS for openclaw /
        hermes means install.py never allocated one — the agent is not
        properly installed. The previous behavior (emit
        `verify_skipped` and return) let canonical sync write
        `state=READY` for a never-verified daemon. Now treated as a
        hard CanonicalSyncError pointing the operator at the cause."""
        client = _Client()

        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"no gateway port persisted.*install\.py never allocated",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                host=host,
                gateway_port=None,
            )
        # No port-probe attempted — we raise before any SSH.
        assert client.calls == []

    @pytest.mark.parametrize(
        "invalid_port",
        [
            "40510",  # string-typed (hand-edited hosts.json)
            0,        # zero — POSIX reserved, never a real listener
            -1,       # negative
            65536,    # exact upper-bound off-by-one (W5 iter-3)
            70000,    # above 65535
            3.14,     # float
            True,     # bool (subclass of int but semantically wrong)
            False,    # also a bool subclass of int (S6 iter-3)
        ],
    )
    def test_invalid_port_rejected(self, invalid_port):
        """W12: parametrized matrix of invalid port values. A
        hand-edited hosts.json could put any of these in the port
        field; refuse to interpolate them into a shell command.

        W5 iter-3: includes the exact upper-bound 65536 to pin the
        `< 65536` strict-less-than guard (off-by-one regression
        would let port 65536 through).
        S6 iter-3: both True AND False to lock the `type(...) is int`
        idiom — `isinstance(False, int)` is True, so a switch back to
        isinstance would let bools through."""
        client = _Client()
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"invalid gateway_port",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                host=host,
                gateway_port=invalid_port,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("valid_port", [1, 1024, 41091, 65535])
    def test_valid_port_boundary_values_accepted(self, monkeypatch, valid_port):
        """W5 iter-3: the highest legal port (65535) must succeed
        through the validator. Combined with the 65536 case above,
        this pins the exact `0 < port < 65536` invariant."""
        client = _Client(
            [(f"nc -z -w 1 127.0.0.1 {valid_port}", 0, b"", b"")]
        )
        host = {"hostname": "h", "hardware": {"os": "macos"}}
        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            host=host,
            gateway_port=valid_port,
        )
        assert any(f"nc -z -w 1 127.0.0.1 {valid_port}" in c for c in client.calls)
