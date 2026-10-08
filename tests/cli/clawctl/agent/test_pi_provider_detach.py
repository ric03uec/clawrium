"""Pi final-provider detach commits metadata only after remote revocation."""

import json
import shlex
import threading
from contextlib import contextmanager
from pathlib import Path

import paramiko
import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import provider as provider_mod
from clawrium.core.lifecycle_canonical import CanonicalSyncError

runner = CliRunner()


def _expected_login_ssh(*, tty: bool, key: str, target: str) -> list[str]:
    return [
        "ssh", "-F", "/dev/null",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}",
        "-o", "IdentitiesOnly=yes",
        "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no",
        "-o", "ForwardAgent=no",
        "-o", "ForwardX11=no",
        "-tt" if tty else "-T",
        "-i", key, "-p", "22", "--", target,
    ]


def _setup(tmp_path, monkeypatch, calls):
    """Use provider.py's real attachment reader/writer against a disk store."""
    path = tmp_path / "hosts.json"
    host = {
        "hostname": "wolf-i",
        "agents": {"pi-key": {"type": "pi", "providers": ["router"]}},
    }
    path.write_text(json.dumps([host]))

    def load():
        return json.loads(path.read_text())[0]

    def resolve(_):
        current = load()
        return current, "pi-key", current["agents"]["pi-key"]

    def persist(hostname, updater):
        current = load()
        assert hostname == "wolf-i"
        calls.append("persist")
        path.write_text(json.dumps([updater(current)]))
        return True

    monkeypatch.setattr(provider_mod, "safe_resolve_agent", resolve)
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    monkeypatch.setattr(provider_mod, "update_host", persist)
    return load


def test_final_pi_detach_revocation_failure_keeps_persisted_attachment(
    tmp_path, monkeypatch
):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)

    def revoke(**kwargs):
        calls.append(("revoke", kwargs))
        raise CanonicalSyncError("remote revoke failed")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )
    assert result.exit_code != 0
    assert "failed to revoke Pi provider credential" in result.output
    assert calls == [
        (
            "revoke",
            {
                "agent_name": "pi-test",
                "host": {
                    "hostname": "wolf-i",
                    "agents": {"pi-key": {"type": "pi", "providers": ["router"]}},
                },
            },
        )
    ]
    assert load()["agents"]["pi-key"]["providers"] == ["router"]


def test_final_pi_detach_transport_failure_keeps_persisted_attachment(
    tmp_path, monkeypatch
):
    """Raw SSH failures must become the safe retryable detach outcome."""
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)

    def revoke(**kwargs):
        calls.append(("revoke", kwargs))
        raise paramiko.SSHException("connection reset")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )

    assert result.exit_code != 0
    assert (
        "failed to revoke Pi provider credential; detach did not finish"
        in result.output
    )
    assert (
        "retry: clawctl agent provider detach router --agent pi-test" in result.output
    )
    assert "connection reset" not in result.output
    assert calls[0][0] == "revoke"
    assert "persist" not in calls
    assert load()["agents"]["pi-key"]["providers"] == ["router"]


def test_final_pi_detach_eof_failure_keeps_persisted_attachment(tmp_path, monkeypatch):
    """Abrupt SSH EOF must retain the attachment and provide a retry command."""
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)

    def revoke(**kwargs):
        calls.append(("revoke", kwargs))
        raise EOFError("connection closed")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )

    assert result.exit_code != 0
    assert "failed to revoke Pi provider credential; detach did not finish" in result.output
    assert "retry: clawctl agent provider detach router --agent pi-test" in result.output
    assert "connection closed" not in result.output
    assert "persist" not in calls
    assert load()["agents"]["pi-key"]["providers"] == ["router"]


def test_final_pi_codex_detach_revokes_only_native_auth_before_persisting(
    tmp_path, monkeypatch
):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {
            "name": "router",
            "type": "openai-codex",
            "default_model": "gpt-5.1-codex-mini",
        },
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **kwargs: pytest.fail("OpenRouter credential must not be touched"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex",
        lambda **kwargs: calls.append(("revoke-codex", kwargs)),
    )

    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == "revoke-codex"
    assert calls[1] == "persist"
    assert load()["agents"]["pi-key"]["providers"] == []


def test_pi_codex_login_opens_tty_only_for_attached_dedicated_agent(monkeypatch):
    host = {
        "hostname": "wolf-i",
        "port": 22,
        "user": "xclm",
        "os_family": "linux",
        "agents": {
            "pi-key": {
                "type": "pi",
                "agent_name": "pi-dedicated",
                "providers": ["codex"],
            }
        },
    }
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi", host["agents"]["pi-key"]),
    )
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {
            "name": "codex",
            "type": "openai-codex",
            "default_model": "gpt-5.1-codex-mini",
        },
    )
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    calls = []
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda args, check: (
            calls.append((args, check)) or type("R", (), {"returncode": 0})()
        ),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", "codex", "--agent", "pi-test"]
    )

    assert result.exit_code == 0, result.output
    assert "/login" in result.output
    assert len(calls) == 2
    # Pin both complete SSH transports in order. The final command argument is
    # validated semantically below rather than copied from the production
    # command builders.
    assert [(argv[:-1], check) for argv, check in calls] == [
        (_expected_login_ssh(tty=True, key="/private/key", target="xclm@wolf-i"), False),
        (_expected_login_ssh(tty=False, key="/private/key", target="xclm@wolf-i"), False),
    ]
    argv, check = calls[0]
    remote = shlex.split(argv[-1])
    assert remote[:5] == ["exec", "sudo", "-n", "/bin/sh", "-c"]
    script, separator, probe, agent_name, home, marker, provider, model, recovery, cleanup = remote[5:]
    assert separator == "--"
    assert recovery == "0"
    assert (agent_name, home, marker, provider, model) == (
        "pi-dedicated",
        "/home/pi-dedicated",
        "/var/lib/clawrium/pi/pi-dedicated.json",
        "openai-codex",
        "gpt-5.1-codex-mini",
    )
    # Independently pin the privileged marker probe rather than reproducing
    # provider.py's builder: root-owned regular 0600 file, no-follow open,
    # inode revalidation, and schema/account binding are all mandatory.
    for required in (
        "lstat($marker)", "O_NOFOLLOW", "sysopen(my $fh,$marker,O_RDONLY|O_NOFOLLOW)",
        "$opened[0]==$before[0]", "$opened[1]==$before[1]", "$before[4]==0",
        "($before[2]&07777)==0600", "$data->{schema}==2",
        "$data->{agent_name} eq $name", "$data->{home} eq $home",
        "$data->{uid}==$account[2]", "$account[7] eq $home",
        "clawrium-pi-$transaction",
    ):
        assert required in probe
    assert 'if test "$7" = 1; then /usr/bin/sudo -n -H -u "$2" -- /usr/bin/perl -e "$8"' in script
    assert "lstat($auth)" in cleanup
    assert "unlink($auth)" in cleanup
    assert 'exec /usr/bin/sudo -n -H -u "$2" -- /usr/bin/env -i' in script
    assert 'pi --provider "$5" --model "$6"' in script
    for inherited in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "AWS_", "NODE_OPTIONS", "PI_CODING_AGENT_DIR"):
        assert inherited not in script
    verify_argv, verify_check = calls[1]
    assert verify_check is False
    verify_remote = shlex.split(verify_argv[-1])
    assert verify_remote[:7] == [
        "exec", "sudo", "-n", "/bin/sh", "-c", verify_remote[5], "--"
    ]
    verify_probe, verified_name, verified_home, verified_marker, verified_auth = verify_remote[7:]
    assert (verified_name, verified_home, verified_marker, verified_auth) == (
        "pi-dedicated", "/home/pi-dedicated", "/var/lib/clawrium/pi/pi-dedicated.json",
        "/home/pi-dedicated/.pi/agent/auth.json",
    )
    for required in (
        "lstat($auth)", "O_NOFOLLOW", "sysopen(my $auth_fh,$auth,O_RDONLY|O_NOFOLLOW)",
        "($auth_before[2]&0170000)==0100000", "$auth_before[4]==$account[2]",
        "($auth_before[2]&07777)==0600", "$auth_opened[0]==$auth_before[0]",
        "$auth_opened[1]==$auth_before[1]", "$oauth->{type} eq 'oauth'",
        "length($oauth->{access})",
    ):
        assert required in verify_probe
    assert "print" not in verify_probe


def test_pi_codex_login_uses_macos_marker_and_home(monkeypatch):
    host = {"hostname": "mac", "user": "xclm", "os_family": "darwin", "agents": {"pi": {"type": "pi", "agent_name": "pi-dedicated", "providers": ["codex"]}}}
    monkeypatch.setattr(provider_mod, "safe_resolve_agent", lambda _: (host, "pi", host["agents"]["pi"]))
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi")
    monkeypatch.setattr(provider_mod, "_safe_get_provider", lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"})
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/key")
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", lambda args, check: (calls.append((args, check)) or type("R", (), {"returncode": 0})()))

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert [(argv[:-1], check) for argv, check in calls] == [
        (_expected_login_ssh(tty=True, key="/key", target="xclm@mac"), False),
        (_expected_login_ssh(tty=False, key="/key", target="xclm@mac"), False),
    ]
    remote = shlex.split(calls[0][0][-1])
    assert remote[:5] == ["exec", "sudo", "-n", "/bin/sh", "-c"]
    assert remote[6] == "--"
    assert remote[9:11] == ["/Users/pi-dedicated", "/Library/Application Support/clawrium/pi/pi-dedicated.json"]
    assert remote[11:13] == ["openai-codex", "gpt-5.1-codex-mini"]
    assert remote[13] == "0"
    verify_remote = shlex.split(calls[1][0][-1])
    assert verify_remote[:5] == ["exec", "sudo", "-n", "/bin/sh", "-c"]
    assert verify_remote[6] == "--"
    assert verify_remote[8:] == [
        "pi-dedicated", "/Users/pi-dedicated",
        "/Library/Application Support/clawrium/pi/pi-dedicated.json",
        "/Users/pi-dedicated/.pi/agent/auth.json",
    ]


def _setup_codex_recovery(tmp_path, monkeypatch, *, update=None):
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps([{
        "hostname": "wolf-i", "user": "xclm", "agents": {
            "pi-key": {"type": "pi", "agent_name": "pi-dedicated", "providers": ["codex"], "pi_codex_auth_recovery": True}
        }
    }]))

    def resolve(_):
        host = json.loads(path.read_text())[0]
        return host, "pi-key", host["agents"]["pi-key"]

    def persist(hostname, updater):
        assert hostname == "wolf-i"
        hosts = json.loads(path.read_text())
        hosts[0] = updater(hosts[0])
        path.write_text(json.dumps(hosts))
        return True

    monkeypatch.setattr(provider_mod, "safe_resolve_agent", resolve)
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(provider_mod, "_safe_get_provider", lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"})
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    monkeypatch.setattr(provider_mod, "update_host", update or persist)
    return path


def test_pi_codex_login_exit_zero_without_new_oauth_keeps_recovery_marker(tmp_path, monkeypatch):
    path = _setup_codex_recovery(tmp_path, monkeypatch)
    calls = []
    results = iter((0, 1))  # Pi exits after recovery scrub; auth verification finds no new OAuth.

    def run(args, check):
        calls.append((args, check))
        return type("R", (), {"returncode": next(results)})()

    monkeypatch.setattr(provider_mod.subprocess, "run", run)

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])

    assert result.exit_code != 0
    assert "did not complete credential recovery" in result.output
    assert json.loads(path.read_text())[0]["agents"]["pi-key"]["pi_codex_auth_recovery"] is True
    interactive = shlex.split(calls[0][0][-1])
    assert interactive[-2] == "1"
    cleanup = interactive[-1]
    assert "lstat($auth)" in cleanup
    assert "unlink($auth)" in cleanup
    assert "access_token" not in result.output


def test_pi_codex_login_validated_oauth_clears_recovery_marker(tmp_path, monkeypatch):
    path = _setup_codex_recovery(tmp_path, monkeypatch)
    results = iter((0, 0))
    monkeypatch.setattr(provider_mod.subprocess, "run", lambda *_args, **_kwargs: type("R", (), {"returncode": next(results)})())

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])

    assert result.exit_code == 0, result.output
    assert "pi_codex_auth_recovery" not in json.loads(path.read_text())[0]["agents"]["pi-key"]


def test_pi_codex_login_excludes_concurrent_pi_lifecycle_operation(tmp_path, monkeypatch):
    _setup_codex_recovery(tmp_path, monkeypatch)
    lock = threading.Lock()
    interactive_started = threading.Event()
    release_interactive = threading.Event()
    competing_operation_acquired = threading.Event()
    results = []
    thread_errors = []

    @contextmanager
    def shared_pi_lock(_agent):
        with lock:
            yield

    def run(args, check):
        if "-tt" in args:
            interactive_started.set()
            assert release_interactive.wait(timeout=2)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(provider_mod, "pi_credential_lock", shared_pi_lock)
    monkeypatch.setattr(provider_mod.subprocess, "run", run)

    def run_login():
        try:
            results.append(
                runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])
            )
        except BaseException as exc:  # Thread failures must fail the test.
            thread_errors.append(exc)

    def concurrent_configure_or_detach():
        try:
            with shared_pi_lock("pi-test"):
                competing_operation_acquired.set()
        except BaseException as exc:  # Thread failures must fail the test.
            thread_errors.append(exc)

    login_thread = threading.Thread(target=run_login)
    competing_thread = threading.Thread(target=concurrent_configure_or_detach)
    try:
        login_thread.start()
        assert interactive_started.wait(timeout=2)
        competing_thread.start()
        assert not competing_operation_acquired.wait(timeout=0.1)
    finally:
        release_interactive.set()
        login_thread.join(timeout=2)
        competing_thread.join(timeout=2)

    assert not login_thread.is_alive()
    assert not competing_thread.is_alive()
    assert not thread_errors
    assert results[0].exit_code == 0, results[0].output
    assert competing_operation_acquired.is_set()


def test_pi_codex_login_racing_attachment_change_keeps_recovery_marker(tmp_path, monkeypatch):
    path = _setup_codex_recovery(tmp_path, monkeypatch)
    calls = 0

    def run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            hosts = json.loads(path.read_text())
            hosts[0]["agents"]["pi-key"]["providers"] = ["replacement"]
            path.write_text(json.dumps(hosts))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(provider_mod.subprocess, "run", run)

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])

    assert result.exit_code != 0
    record = json.loads(path.read_text())[0]["agents"]["pi-key"]
    assert record["providers"] == ["replacement"]
    assert record["pi_codex_auth_recovery"] is True


def test_pi_codex_login_storage_failure_keeps_marker_and_uses_safe_message(tmp_path, monkeypatch):
    def fail_update(_hostname, _updater):
        raise OSError("private path detail")

    path = _setup_codex_recovery(tmp_path, monkeypatch, update=fail_update)
    results = iter((0, 0))
    monkeypatch.setattr(provider_mod.subprocess, "run", lambda *_args, **_kwargs: type("R", (), {"returncode": next(results)})())

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])

    assert result.exit_code != 0
    assert "repair local storage" in result.output
    assert "private path detail" not in result.output
    assert json.loads(path.read_text())[0]["agents"]["pi-key"]["pi_codex_auth_recovery"] is True


def test_pi_codex_login_rejects_invalid_managed_account_before_ssh(monkeypatch):
    host = {"hostname": "host", "user": "xclm", "agents": {"pi": {"type": "pi", "agent_name": "bad/name", "providers": ["codex"]}}}
    monkeypatch.setattr(provider_mod, "safe_resolve_agent", lambda _: (host, "pi", host["agents"]["pi"]))
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi")
    monkeypatch.setattr(provider_mod, "_safe_get_provider", lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"})
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/key")
    monkeypatch.setattr(provider_mod.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("must not invoke SSH"))

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi"])

    assert result.exit_code != 0
    assert "invalid managed account name" in result.output


def test_pi_codex_login_sanitizes_nonexistent_provider_before_lookup(monkeypatch):
    hostile_provider = "missing\u202eprovider"
    monkeypatch.setattr(provider_mod, "get_provider", lambda _: None)
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not invoke SSH"),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", hostile_provider, "--agent", "pi-test"]
    )

    assert result.exit_code != 0
    assert "provider 'missing provider' not found" in result.output
    assert "\u202e" not in result.output


def test_pi_codex_login_sanitizes_nonexistent_agent_before_lookup(monkeypatch):
    hostile_agent = "missing\u202eagent"
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not invoke SSH"),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", "codex", "--agent", hostile_agent]
    )

    assert result.exit_code != 0
    assert "agent 'missing agent' not found" in result.output
    assert "\u202e" not in result.output


def test_generic_provider_detach_sanitizes_unattached_provider_and_agent(monkeypatch):
    hostile_provider = "missing\u202eprovider"
    hostile_agent = "pi\u202etest"
    host = {"hostname": "wolf-i", "agents": {"pi-key": {"type": "pi", "providers": []}}}
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi-key", host["agents"]["pi-key"]),
    )
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")

    result = runner.invoke(
        app, ["agent", "provider", "detach", hostile_provider, "--agent", hostile_agent]
    )

    assert result.exit_code != 0
    assert "provider 'missing\\u202eprovider' not attached to agent 'pi\\u202etest'" in result.output
    assert "clawctl agent provider get --agent pi test" in result.output
    assert "\u202e" not in result.output


def test_pi_codex_login_rejects_unattached_provider_without_opening_ssh(monkeypatch):
    hostile_provider = "codex\u202eevil"
    hostile_agent = "pi\u202etest"
    host = {
        "hostname": "wolf-i",
        "agents": {"pi-key": {"type": "pi", "providers": []}},
    }
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi-key", host["agents"]["pi-key"]),
    )
    resolved_names = []
    monkeypatch.setattr(
        provider_mod,
        "resolve_agent_key",
        lambda _host, value: (resolved_names.append(value) or "pi-key"),
    )
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not open SSH"),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", hostile_provider, "--agent", hostile_agent]
    )

    assert result.exit_code != 0
    assert "not attached" in result.output
    assert "\u202e" not in result.output
    assert "codex evil" in result.output
    assert "pi test" in result.output
    assert resolved_names == ["pi test"]


def test_pi_codex_login_reports_local_ssh_launch_failure(monkeypatch):
    host = {
        "hostname": "wolf\u202ei",
        "user": "xclm",
        "agents": {"pi-key": {"type": "pi", "agent_name": "pi-dedicated", "providers": ["codex"]}},
    }
    monkeypatch.setattr(provider_mod, "safe_resolve_agent", lambda _: (host, "pi-key", host["agents"]["pi-key"]))
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(provider_mod, "_safe_get_provider", lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"})
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    monkeypatch.setattr(provider_mod.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("ssh missing")))

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])

    assert result.exit_code != 0
    assert "could not start SSH for Pi native login on host 'wolfi'" in result.output
    assert "ssh missing" not in result.output
    assert "\u202e" not in result.output


def test_pi_codex_login_passes_option_like_hostname_after_ssh_delimiter(monkeypatch):
    hostile_hostname = "-oProxyCommand=unsafe"
    host = {
        "hostname": hostile_hostname,
        "user": "xclm",
        "agents": {"pi-key": {"type": "pi", "agent_name": "pi-dedicated", "providers": ["codex"]}},
    }
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi-key", host["agents"]["pi-key"]),
    )
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    calls = []
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda args, check: (calls.append((args, check)) or type("R", (), {"returncode": 0})()),
    )

    result = runner.invoke(app, ["agent", "provider", "login", "codex", "--agent", "pi-test"])

    assert result.exit_code == 0, result.output
    assert [(argv[:-1], check) for argv, check in calls] == [
        (_expected_login_ssh(tty=True, key="/private/key", target="xclm@-oProxyCommand=unsafe"), False),
        (_expected_login_ssh(tty=False, key="/private/key", target="xclm@-oProxyCommand=unsafe"), False),
    ]


def test_pi_codex_login_rejects_option_like_ssh_user_before_subprocess(monkeypatch):
    host = {
        "hostname": "wolf-i",
        "user": "-oProxyCommand=unsafe",
        "agents": {"pi-key": {"type": "pi", "providers": ["codex"]}},
    }
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi-key", host["agents"]["pi-key"]),
    )
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not invoke SSH"),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", "codex", "--agent", "pi-test"]
    )

    assert result.exit_code != 0
    assert "invalid managed SSH user" in result.output


def test_pi_codex_login_propagates_interactive_ssh_failure(monkeypatch):
    host = {
        "hostname": "wolf-i",
        "port": 22,
        "user": "xclm",
        "os_family": "linux",
        "agents": {
            "pi-key": {
                "type": "pi",
                "agent_name": "pi-dedicated",
                "providers": ["codex"],
            }
        },
    }
    monkeypatch.setattr(
        provider_mod,
        "safe_resolve_agent",
        lambda _: (host, "pi-key", host["agents"]["pi-key"]),
    )
    monkeypatch.setattr(provider_mod, "resolve_agent_key", lambda *_: "pi-key")
    monkeypatch.setattr(
        provider_mod,
        "_safe_get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(provider_mod, "get_host_private_key", lambda _: "/private/key")
    monkeypatch.setattr(
        provider_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: type("R", (), {"returncode": 23})(),
    )

    result = runner.invoke(
        app, ["agent", "provider", "login", "codex", "--agent", "pi-test"]
    )

    assert result.exit_code == 23
    assert "Opening Pi native login" in result.output


def test_final_pi_detach_revokes_before_persisting_attachment(tmp_path, monkeypatch):
    calls = []
    load = _setup(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
        lambda **kwargs: calls.append(("revoke-openrouter", kwargs)),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex",
        lambda **kwargs: pytest.fail("Codex credential must not be touched"),
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-test"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "revoke-openrouter"
    assert calls[0][1]["agent_name"] == "pi-test"
    assert calls[0][1]["host"]["hostname"] == "wolf-i"
    assert calls[1] == "persist"
    assert load()["agents"]["pi-key"]["providers"] == []
    assert "detached provider 'router'" in result.output
