"""Unit tests for core/agent_exec.py — Ansible passthrough dispatcher.

ansible_runner is mocked so tests run offline. Event lists model what
the real `exec.yaml` playbook emits: three debug events tagged
EXEC_STDOUT=/EXEC_STDERR=/EXEC_RC=.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import agent_exec


def _ok_event(msg: str) -> dict:
    return {"event": "runner_on_ok", "event_data": {"res": {"msg": msg}}}


def _make_result(events: list[dict], status: str = "successful") -> SimpleNamespace:
    return SimpleNamespace(events=events, status=status)


def _pi_encrypted_event(
    recipient_certificate: str, payload: dict, tmp_path: Path
) -> dict:
    """Model the host's CMS event without putting its plaintext in events."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for Pi secure-exec transport")
    public_path = tmp_path / "pi-exec-recipient.pem"
    public_path.write_text(recipient_certificate)
    encrypted = subprocess.run(
        [
            openssl,
            "cms",
            "-encrypt",
            "-binary",
            "-outform",
            "DER",
            "-aes-256-cbc",
            "-recip",
            str(public_path),
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        check=True,
    ).stdout
    return _ok_event("PI_EXEC_RESULT=" + base64.b64encode(encrypted).decode())


@pytest.fixture
def patched_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(
        agent_exec,
        "get_config_dir",
        lambda: tmp_path / "config",
    )
    monkeypatch.setattr(
        agent_exec.core_keys,
        "get_host_private_key",
        lambda key_id: tmp_path / "fake-key",
    )
    (tmp_path / "fake-key").write_text("KEY")
    # Make all per-type playbook paths exist
    for ctype in agent_exec.SUPPORTED_CLAW_TYPES:
        p = agent_exec._playbook_path(ctype)
        if not p.exists():  # pragma: no cover — real playbooks exist
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("dummy")
    # Stub get_host
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {"hostname": h, "user": "alice", "port": 22, "alias": "wolf-i"},
    )
    return tmp_path


def test_run_agent_exec_success(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"hello world").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["--version"]
    )
    assert (stdout, stderr, rc) == ("hello world", "", 0)
    # extra_vars passes cmd_argv as a typed list
    inv = captured["inventory"]
    assert inv["all"]["vars"]["cmd_argv"] == ["--version"]
    assert inv["all"]["vars"]["agent_name"] == "wolf-i"


def test_run_agent_exec_nonzero_rc(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"oops\n").decode()),
                _ok_event("EXEC_RC=42"),
            ]
        ),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["bogus"]
    )
    assert rc == 42
    assert "oops" in stderr


@pytest.mark.parametrize(
    ("os_family", "expected_playbook"),
    [("linux", "exec.yaml"), ("darwin", "exec_macos.yaml")],
)
def test_pi_exec_encrypts_sentinel_output_preserves_nonzero_and_cleans_runner_state(
    monkeypatch, patched_env, os_family, expected_playbook
):
    """Success/failure output is recoverable only by this invocation's key."""
    captured = {}
    sentinel = "pi-secret-sentinel-must-not-reach-ansible-events"

    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {
            "hostname": h,
            "user": "alice",
            "port": 22,
            "alias": "wolf-i",
            "os_family": os_family,
        },
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        # ansible-runner would create these persistent locations; cleanup must
        # remove them with the ephemeral private key after result decryption.
        private_data_dir = Path(kwargs["private_data_dir"])
        for name in ("artifacts", "env", "inventory"):
            (private_data_dir / name).mkdir()
        event = _pi_encrypted_event(
            kwargs["inventory"]["all"]["vars"]["pi_exec_recipient_certificate"],
            {"stdout": sentinel + "\\n", "stderr": "failed: " + sentinel, "rc": 17},
            patched_env,
        )
        assert sentinel not in event["event_data"]["res"]["msg"]
        return _make_result([event])

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "pi-one", "pi", ["--version"]
    )
    assert (stdout, stderr, rc) == (sentinel + "\\n", "failed: " + sentinel, 17)
    assert str(captured["playbook"]).endswith("pi/playbooks/" + expected_playbook)
    assert captured["inventory"]["all"]["vars"]["cmd_argv"] == ["--version"]
    assert captured["inventory"]["all"]["vars"]["pi_exec_mode"] == "diagnostic"
    assert captured["inventory"]["all"]["vars"]["pi_exec_timeout"] == 120
    # The Pi playbook owns process-group termination; runner only receives
    # a grace window to collect the encrypted terminal result.
    assert captured["timeout"] == 150
    assert (
        sentinel
        not in captured["inventory"]["all"]["vars"]["pi_exec_recipient_certificate"]
    )
    assert not Path(captured["private_data_dir"]).exists()


def test_run_agent_exec_unreachable(monkeypatch, patched_env):
    unreach = {
        "event": "runner_on_unreachable",
        "event_data": {"res": {"msg": "ssh failed"}},
    }
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([unreach], status="failed"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "unreachable" in stderr.lower()


def test_run_agent_exec_timeout(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([], status="timeout"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "timed out" in stderr


def test_unknown_claw_type_raises(patched_env):
    with pytest.raises(agent_exec.AgentExecError):
        agent_exec.run_agent_exec("10.0.0.1", "x", "phantomclaw", ["foo"])


@pytest.mark.parametrize("cmd_argv", [[], None])
def test_empty_cmd_argv_raises(patched_env, cmd_argv):
    with pytest.raises(
        agent_exec.AgentExecError, match="cmd_argv must be a non-empty list"
    ):
        agent_exec.run_agent_exec("10.0.0.1", "x", "openclaw", cmd_argv)


def test_missing_ssh_key(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.core_keys, "get_host_private_key", lambda key_id: None
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "SSH key" in stderr


def test_missing_host(monkeypatch, patched_env):
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(hosts_module, "get_host", lambda h: None)
    stdout, stderr, rc = agent_exec.run_agent_exec("nope", "x", "openclaw", ["v"])
    assert rc == 255
    assert "not found" in stderr


def test_invalid_agent_name_raises(patched_env):
    with pytest.raises(agent_exec.AgentExecError):
        agent_exec.run_agent_exec("10.0.0.1", "Bad Name!", "openclaw", ["x"])


@pytest.mark.parametrize("claw_type", ["claude", "hermes", "zeroclaw"])
def test_run_agent_exec_per_type_success(monkeypatch, patched_env, claw_type):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"v1.0").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "agent", claw_type, ["--version"]
    )
    assert (stdout, rc) == ("v1.0", 0)
    assert claw_type in captured["playbook"]


def test_runner_on_failed_with_msg(monkeypatch, patched_env):
    failed = {
        "event": "runner_on_failed",
        "event_data": {"res": {"msg": "binary not found"}},
    }
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([failed], status="failed"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "binary not found" in stderr


def test_runner_on_failed_with_stderr(monkeypatch, patched_env):
    failed = {
        "event": "runner_on_failed",
        "event_data": {"res": {"stderr": "permission denied"}},
    }
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([failed], status="failed"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "permission denied" in stderr


def test_log_dir_uses_uuid_suffix(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        return _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    agent_exec.run_agent_exec("10.0.0.1", "wolf-i", "openclaw", ["x"])
    # Path ends in `-<8 hex chars>`
    suffix = captured["pd"].rsplit("-", 1)[-1]
    assert len(suffix) == 8 and all(c in "0123456789abcdef" for c in suffix)


def test_missing_rc_marker(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"out").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                # no EXEC_RC
            ]
        ),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "did not report an exit code" in stderr


@pytest.mark.parametrize(
    ("claw_type", "os_family", "expected_suffix"),
    [
        ("claude", "linux", "claude/playbooks/exec.yaml"),
        ("claude", "darwin", "claude/playbooks/exec_macos.yaml"),
        ("openclaw", "linux", "openclaw/playbooks/exec.yaml"),
        ("openclaw", "darwin", "openclaw/playbooks/exec_macos.yaml"),
        ("hermes", "linux", "hermes/playbooks/exec.yaml"),
        ("hermes", "darwin", "hermes/playbooks/exec_macos.yaml"),
        ("zeroclaw", "linux", "zeroclaw/playbooks/exec.yaml"),
        ("zeroclaw", "darwin", "zeroclaw/playbooks/exec_macos.yaml"),
    ],
)
def test_run_agent_exec_uses_expected_playbook_for_host_os(
    monkeypatch, patched_env, claw_type, os_family, expected_suffix
):
    captured = {}

    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {
            "hostname": h,
            "user": "alice",
            "port": 22,
            "alias": "wolf-m",
            "os_family": os_family,
        },
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"hello world").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-m", claw_type, ["--version"]
    )

    assert (stdout, stderr, rc) == ("hello world", "", 0)
    assert captured["playbook"].endswith(expected_suffix)


def test_run_agent_exec_returns_error_for_unrecognized_os_family(
    monkeypatch, patched_env
):
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {
            "hostname": h,
            "user": "alice",
            "port": 22,
            "alias": "wolf-bsd",
            "os_family": "freebsd",
        },
    )

    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-bsd", "openclaw", ["--version"]
    )

    assert stdout == ""
    assert rc == 255
    assert "os_family='freebsd' is not supported by clawrium" in stderr


def test_run_agent_exec_returns_file_not_found_when_supported_os_playbook_missing(
    monkeypatch, patched_env
):
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {
            "hostname": h,
            "user": "alice",
            "port": 22,
            "alias": "wolf-m",
            "os_family": "darwin",
        },
    )

    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-m", "ethos", ["--version"]
    )

    assert stdout == ""
    assert rc == 255
    assert "does not support os_family='darwin'" in stderr


def test_claude_exec_parses_host_redacted_result_event(monkeypatch, patched_env):
    """Claude playbooks emit only one already-redacted result event."""
    payload = base64.b64encode(b'{"stdout":"[REDACTED]","stderr":"","rc":7}').decode()
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([_ok_event(f"CLAUDE_EXEC_RESULT={payload}")]),
    )

    assert agent_exec.run_agent_exec("10.0.0.1", "wolf-i", "claude", ["--print"]) == (
        "[REDACTED]",
        "",
        7,
    )


def test_claude_exec_preserves_structured_injection_shaped_argv(
    monkeypatch, patched_env
):
    """Claude arguments remain typed inventory values, never a shell fragment."""
    captured = {}
    injection_shaped_argv = [
        "--setting",
        "'; touch /tmp/pwn; {{ lookup('env', 'SECRET') }}",
    ]

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"safe").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "claude", injection_shaped_argv, timeout=17
    )

    assert (stdout, stderr, rc) == ("safe", "", 0)
    assert captured["inventory"]["all"]["vars"] == {
        "agent_name": "wolf-i",
        "cmd_argv": injection_shaped_argv,
        "claude_exec_timeout": 17,
    }
    # The native command is killed on the host after 17s; the runner gets a
    # short grace period only to collect the redacted result events.
    assert captured["timeout"] == 47


def test_claude_exec_clamps_remote_timeout_and_never_passes_credentials(
    monkeypatch, patched_env
):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event(
                    "EXEC_STDOUT=" + base64.b64encode(b"Claude Code 2.1.100").decode()
                ),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "claude", ["--version"], timeout=9999
    )

    assert (stdout, stderr, rc) == ("Claude Code 2.1.100", "", 0)
    variables = captured["inventory"]["all"]["vars"]
    assert variables["claude_exec_timeout"] == 120
    assert not any("credential" in key or "token" in key for key in variables)
    assert captured["timeout"] == 150


def test_claude_exec_version_does_not_require_controller_credential(
    monkeypatch, patched_env
):
    """Unauthenticated version parity stays available before configure/sync."""
    from clawrium.core import claude_credentials

    def no_credential(_agent_name):
        raise claude_credentials.ClaudeCredentialError("credential is not configured")

    monkeypatch.setattr(
        claude_credentials, "get_active_claude_credential", no_credential
    )
    version = "2.1.100" + chr(10)
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(version.encode()).decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        ),
    )

    assert agent_exec.run_agent_exec("10.0.0.1", "wolf-i", "claude", ["--version"]) == (
        version,
        "",
        0,
    )


def test_claude_exec_redacts_selected_api_key_from_remote_failure(
    monkeypatch, patched_env
):
    from clawrium.core import claude_credentials

    secret = "sk-ant-api03-secret-value"
    monkeypatch.setattr(
        claude_credentials,
        "get_active_claude_credential",
        lambda _agent_name: ("ANTHROPIC_API_KEY", secret),
    )
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(secret.encode()).decode()),
                _ok_event(
                    "EXEC_STDERR="
                    + base64.b64encode(
                        f"authentication failed: {secret}".encode()
                    ).decode()
                ),
                _ok_event("EXEC_RC=1"),
            ]
        ),
    )

    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "claude", ["--print"]
    )

    assert rc == 1
    assert secret not in stdout
    assert secret not in stderr
    assert "[REDACTED]" in stdout
    assert "[REDACTED]" in stderr


@pytest.mark.parametrize(
    "cmd_argv",
    [[], None, [""], [None], ["--version", "contains" + chr(0) + "nul"]],
)
def test_malformed_cmd_argv_raises_before_runner(patched_env, cmd_argv):
    with pytest.raises(
        agent_exec.AgentExecError, match="cmd_argv must be a non-empty list"
    ):
        agent_exec.run_agent_exec("10.0.0.1", "wolf-i", "claude", cmd_argv)


def test_reserved_agent_name_is_rejected_before_runner(patched_env):
    with pytest.raises(agent_exec.AgentExecError, match="reserved system user"):
        agent_exec.run_agent_exec("10.0.0.1", "root", "claude", ["--version"])


def test_pi_exec_cleans_ephemeral_key_on_key_setup_interruption(monkeypatch, patched_env):
    captured = {}
    original = agent_exec._create_pi_exec_keypair

    def interrupted(log_dir):
        captured["calls"] = captured.get("calls", 0) + 1
        original(log_dir)
        captured["log_dir"] = log_dir
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_exec, "_create_pi_exec_keypair", interrupted)
    with pytest.raises(KeyboardInterrupt):
        agent_exec.run_agent_exec("10.0.0.1", "pi-one", "pi", ["--version"])
    assert captured["calls"] == 1
    assert not captured["log_dir"].exists()


def test_pi_exec_cleans_ephemeral_key_on_runner_interruption(monkeypatch, patched_env):
    captured = {}

    def interrupted(**kwargs):
        captured.update(kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_exec.ansible_runner, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        agent_exec.run_agent_exec("10.0.0.1", "pi-one", "pi", ["--version"])
    assert not Path(captured["private_data_dir"]).exists()


def test_run_agent_exec_returns_runner_exception(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )

    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["--version"]
    )

    assert stdout == ""
    assert rc == 255
    assert stderr == "ansible-runner error: connection refused"
