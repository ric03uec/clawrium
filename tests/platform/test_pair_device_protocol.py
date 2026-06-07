"""Behavioral regression tests for openclaw pair_device.mjs protocol negotiation.

Issue #608: pair_device.mjs pinned both minProtocol and maxProtocol to 3, which
the v2026.5.28 daemon (expectedProtocol=4) rejected. These tests stand up a
local Node WebSocket server mimicking the daemon's connect.challenge -> connect
-> hello-ok handshake and assert the pair script:
  - Succeeds against expectedProtocol={3, 4}.
  - Advertises the correct [3, 4] negotiation range on the wire.
  - Fails loudly with a protocol-mismatch message naming the supported range
    when the daemon advertises a protocol outside [3, 4].
  - Validates `negotiatedProtocol` echoed by the daemon and rejects an
    out-of-range value even when the daemon would otherwise return a token.
  - Fails when the connect response omits or empties `auth.deviceToken`.

The mock daemon and the pair script both rely on the `ws` npm package. A
session-scoped fixture installs `ws` into a tmp dir under pytest's basetemp
(skipped if `node` or `npm` are missing).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIR_SCRIPT = (
    REPO_ROOT
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "openclaw"
    / "scripts"
    / "pair_device.mjs"
)
MOCK_DAEMON = Path(__file__).parent / "fixtures" / "mock_openclaw_daemon.mjs"


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@pytest.fixture(scope="session")
def node_env(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Set up a working directory with `ws` installed and copies of both
    scripts. Node's ESM loader resolves bare imports from the script's
    location upward, so the scripts must live next to a node_modules with
    `ws` in it — NODE_PATH does not work for ESM bare specifiers.

    Uses a pytest tmp dir so parallel xdist workers don't trample each other
    or pollute the source tree.
    """
    if not _have("node"):
        pytest.skip("node required for behavioral pair test")
    if not _have("npm"):
        pytest.skip("npm required to install ws for behavioral pair test")

    ws_cache = tmp_path_factory.mktemp("pair_device_ws_cache")
    (ws_cache / "package.json").write_text(
        json.dumps({"name": "pair-device-test-cache", "private": True}) + "\n"
    )
    result = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund", "--silent", "ws@^8"],
        cwd=ws_cache,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(
            f"failed to install ws for pair test: {result.stderr.strip() or result.stdout.strip()}"
        )

    pair_copy = ws_cache / "pair_device.mjs"
    mock_copy = ws_cache / "mock_openclaw_daemon.mjs"
    pair_copy.write_text(PAIR_SCRIPT.read_text())
    mock_copy.write_text(MOCK_DAEMON.read_text())
    return {"pair": pair_copy, "mock": mock_copy, "env": os.environ.copy()}


class _MockDaemon:
    def __init__(self, proc: subprocess.Popen, port: int):
        self.proc = proc
        self.port = port
        self.connect_params: dict | None = None

    def collect_stdout(self) -> list[dict]:
        """Drain remaining stdout lines and return as parsed JSON events.
        Safe to call after the test exercises the script."""
        if not self.proc.stdout:
            return []
        events: list[dict] = []
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except ValueError:
            pass
        return events


def _spawn_mock_daemon(
    ctx: dict, expected_protocol: int, *extra_args: str
) -> _MockDaemon:
    proc = subprocess.Popen(
        [
            "node",
            str(ctx["mock"]),
            "--expected-protocol",
            str(expected_protocol),
            "--port",
            "0",
            *extra_args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=ctx["env"],
        text=True,
        bufsize=1,
    )
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if proc.poll() is not None:
            err = (proc.stderr.read() if proc.stderr else "") or ""
            raise RuntimeError(f"mock daemon exited early: {err}")
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            time.sleep(0.02)
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "ready":
            return _MockDaemon(proc, int(payload["port"]))
    proc.kill()
    raise TimeoutError("mock daemon never became ready")


def _run_pair_script(port: int, ctx: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "node",
            str(ctx["pair"]),
            f"ws://127.0.0.1:{port}",
            "test-bootstrap-token",
        ],
        capture_output=True,
        text=True,
        env=ctx["env"],
        timeout=15,
    )


def _pair_against(
    expected_protocol: int, ctx: dict, *extra_mock_args: str
) -> tuple[subprocess.CompletedProcess, list[dict]]:
    daemon = _spawn_mock_daemon(ctx, expected_protocol, *extra_mock_args)
    try:
        result = _run_pair_script(daemon.port, ctx)
    finally:
        daemon.proc.terminate()
        try:
            daemon.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            daemon.proc.kill()
    events = daemon.collect_stdout()
    return result, events


def _find_event(events: list[dict], event_name: str) -> dict | None:
    for ev in events:
        if ev.get("event") == event_name:
            return ev
    return None


@pytest.mark.parametrize(
    "expected_protocol",
    [
        pytest.param(4, id="v2026_5_28_daemon"),
        pytest.param(3, id="v2026_4_2_daemon"),
    ],
)
def test_pair_succeeds_against_supported_protocol(
    expected_protocol: int, node_env: dict
) -> None:
    """Pair script must succeed against daemons in the supported range AND
    must advertise the full [3, 4] negotiation window on the wire (so a
    silent regression back to maxProtocol=3 is caught even when the test
    runs against expectedProtocol=3)."""
    result, events = _pair_against(expected_protocol, node_env)
    assert result.returncode == 0, (
        f"pair script failed against expectedProtocol={expected_protocol}:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    output_lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    assert output_lines, f"no stdout from pair script: {result.stdout!r}"
    payload = json.loads(output_lines[-1])
    assert payload["deviceId"]
    assert isinstance(payload["deviceToken"], str)
    assert payload["deviceToken"].startswith("mock-device-token-")
    assert "PRIVATE KEY" in payload["privateKeyPem"]

    connect_params = _find_event(events, "connect-params")
    assert connect_params is not None, f"mock did not log connect-params: {events!r}"
    assert connect_params["minProtocol"] == 3, (
        f"pair script regressed minProtocol: {connect_params!r}"
    )
    assert connect_params["maxProtocol"] == 4, (
        f"pair script regressed maxProtocol: {connect_params!r}"
    )


@pytest.mark.parametrize(
    "expected_protocol",
    [
        pytest.param(5, id="future_v5_daemon"),
        pytest.param(2, id="legacy_v2_daemon"),
    ],
)
def test_pair_fails_loudly_on_unsupported_protocol(
    expected_protocol: int, node_env: dict
) -> None:
    """Pair script must exit non-zero with a clear protocol-mismatch message
    when the daemon's expected protocol falls outside [3, 4]."""
    result, _events = _pair_against(expected_protocol, node_env)
    assert result.returncode != 0, (
        f"pair script unexpectedly succeeded against expectedProtocol={expected_protocol}"
    )
    combined = result.stdout + "\n" + result.stderr
    assert "v3-v4" in combined, (
        f"missing supported-range marker in error output: {combined!r}"
    )
    assert f"v{expected_protocol}" in combined, (
        f"missing daemon-expected protocol marker in error output: {combined!r}"
    )


def test_pair_rejects_out_of_range_negotiated_protocol(node_env: dict) -> None:
    """A daemon that accepts the connect request but echoes a
    `negotiatedProtocol` outside [3, 4] must be rejected — without this
    guard, a future v5 daemon accepting the range for backward compat
    reasons would return a token that the script wrongly trusts."""
    # The mock's success path echoes negotiatedProtocol = expectedProtocol.
    # Spawn the mock with expectedProtocol=4 first (so the connect gate
    # passes), then force it to echo a v5 negotiation by patching at the
    # source. Simpler: use a dedicated mock flag.
    # Instead we use a separate test that reaches into the mock by spawning
    # it with --expected-protocol=5 AND --port=0 — but that hits the gate.
    # The cleanest direct test for this validation lives in the production
    # script's behavior alone: assert that formatProtocolMismatch is called
    # when `negotiatedProtocol` is out of range. We exercise via a custom
    # mock invocation that bypasses the protocol gate by widening the
    # acceptance window — that mode is built into the mock for this test.
    daemon = _spawn_mock_daemon(node_env, 4, "--negotiated-protocol-override", "5")
    try:
        result = _run_pair_script(daemon.port, node_env)
    finally:
        daemon.proc.terminate()
        try:
            daemon.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            daemon.proc.kill()
    assert result.returncode != 0, (
        "pair script silently accepted a v5 negotiated protocol"
    )
    combined = result.stdout + "\n" + result.stderr
    assert "v3-v4" in combined and "v5" in combined, (
        f"protocol-mismatch error did not name the offending version: {combined!r}"
    )


@pytest.mark.parametrize(
    "mock_flag,case_id",
    [
        ("--omit-device-token", "absent_field"),
        ("--empty-device-token", "empty_string"),
    ],
)
def test_pair_fails_when_device_token_missing_or_empty(
    mock_flag: str, case_id: str, node_env: dict
) -> None:
    """If the connect response carries no usable deviceToken, the script
    must exit non-zero rather than write a partial JSON output the
    install playbook would happily parse."""
    result, _events = _pair_against(4, node_env, mock_flag)
    assert result.returncode != 0, (
        f"pair script unexpectedly succeeded with mock {mock_flag} ({case_id})"
    )
    combined = result.stdout + "\n" + result.stderr
    assert "No deviceToken" in combined or "deviceToken" in combined, (
        f"missing device-token error marker: {combined!r}"
    )
