"""End-to-end locking regressions for Pi configure and provider detach (#1038)."""

import json
import threading
from contextlib import contextmanager
from pathlib import Path

import typer
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import provider as provider_mod
from clawrium.core.config import get_config_dir
from clawrium.core.providers.storage import set_provider_api_key


AGENT = "pi-race"
PROVIDER = "router"
WAIT_SECONDS = 2


def _seed_disk_state(*, attached: bool) -> Path:
    """Create the real hosts, provider, and secret records the CLI consumes."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    providers = [PROVIDER] if attached else []
    (config_dir / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "race-host",
                    "os_family": "linux",
                    "agents": {
                        AGENT: {
                            "type": "pi",
                            "agent_name": AGENT,
                            "providers": providers,
                            "status": "installed",
                            "installed_at": "2026-01-01T00:00:00+00:00",
                        }
                    },
                }
            ]
        )
    )
    (config_dir / "providers.json").write_text(
        json.dumps(
            [
                {
                    "name": PROVIDER,
                    "type": "openrouter",
                    "default_model": "openai/gpt-4o",
                }
            ]
        )
    )
    set_provider_api_key(PROVIDER, "test-openrouter-key")
    return config_dir / "hosts.json"


def _attachments(hosts_path: Path) -> list[str]:
    return json.loads(hosts_path.read_text())[0]["agents"][AGENT]["providers"]


def _invoke(argv: list[str]) -> int:
    """Invoke the real Typer tree without CliRunner's process-global streams.

    Click's test runner swaps ``sys.stdout`` globally, so two simultaneous
    runners corrupt each other's capture buffers. Direct Typer invocation
    preserves the command parser and callbacks while allowing the operations
    themselves to contend in separate threads.
    """
    try:
        result = app(args=argv, prog_name="clawctl", standalone_mode=False)
    except typer.Exit as exc:
        return exc.exit_code
    return int(result or 0)


def _configure(result: dict) -> None:
    result["exit_code"] = _invoke(
        ["agent", "configure", AGENT, "--stage", "providers", "--provider", PROVIDER]
    )


def _detach(result: dict) -> None:
    result["exit_code"] = _invoke(
        ["agent", "provider", "detach", PROVIDER, "--agent", AGENT]
    )


def _observe_shared_lock(monkeypatch, *, contender_name: str):
    """Expose the real flock boundary without replacing its mutual exclusion."""
    from clawrium.core import pi as pi_mod

    attempting = threading.Event()
    acquired = threading.Event()
    real_lock = pi_mod.pi_credential_lock

    @contextmanager
    def observed_lock(agent_name):
        contender = threading.current_thread().name == contender_name
        if contender:
            attempting.set()
        with real_lock(agent_name):
            if contender:
                acquired.set()
            yield

    monkeypatch.setattr(pi_mod, "pi_credential_lock", observed_lock)
    return attempting, acquired


def _mock_remote(
    monkeypatch,
    remote,
    *,
    write_started=None,
    allow_write=None,
    revoke_started=None,
    allow_revoke=None,
    fail_write=False,
    fail_provision=False,
    operations=None,
):
    """Mock only SSH ownership and the remote credential write/revocation."""

    class Client:
        def close(self):
            pass

    def environment_operation(_client, *, body, path, **_kwargs):
        # OpenRouter tests model the secret-bearing provider activation only;
        # removing the independent Bedrock profile must not look like revoking
        # that credential.
        if not path.endswith("clawrium-provider.env"):
            return
        if body is not None:
            if operations is not None:
                operations.append("provision")
            if write_started is not None:
                write_started.set()
            if allow_write is not None:
                assert allow_write.wait(WAIT_SECONDS)
            if fail_write or fail_provision:
                from clawrium.core.lifecycle_canonical import CanonicalSyncError

                raise CanonicalSyncError("remote credential write failed")
            remote["credential"] = True
            return
        if operations is not None:
            operations.append("revoke")
        if revoke_started is not None:
            revoke_started.set()
        if allow_revoke is not None:
            assert allow_revoke.wait(WAIT_SECONDS)
        remote["credential"] = False

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._open_ssh", lambda _host: Client()
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        environment_operation,
    )


def test_configure_first_then_detach_leaves_disk_and_remote_detached(
    tmp_path, monkeypatch
):
    """Detach waits at the shared lock until configure has written remotely."""
    hosts_path = _seed_disk_state(attached=False)
    remote = {"credential": False}
    write_started = threading.Event()
    allow_write = threading.Event()
    _mock_remote(
        monkeypatch,
        remote,
        write_started=write_started,
        allow_write=allow_write,
    )
    detach_attempting, detach_acquired = _observe_shared_lock(
        monkeypatch, contender_name="detach"
    )

    configure_result: dict = {}
    detach_result: dict = {}
    configuring = threading.Thread(target=_configure, args=(configure_result,))
    detaching = threading.Thread(target=_detach, args=(detach_result,), name="detach")
    configuring.start()
    assert write_started.wait(WAIT_SECONDS)
    detaching.start()
    assert detach_attempting.wait(WAIT_SECONDS)
    assert not detach_acquired.wait(0.1)
    allow_write.set()
    configuring.join(WAIT_SECONDS)
    detaching.join(WAIT_SECONDS)

    assert not configuring.is_alive()
    assert not detaching.is_alive()
    assert configure_result["exit_code"] == 0
    assert detach_result["exit_code"] == 0
    assert _attachments(hosts_path) == []
    assert remote["credential"] is False


def test_detach_first_then_configure_leaves_disk_and_remote_attached(
    tmp_path, monkeypatch
):
    """Configure re-reads state under the lock after the prior detach commits."""
    hosts_path = _seed_disk_state(attached=True)
    remote = {"credential": True}
    revoke_started = threading.Event()
    allow_revoke = threading.Event()
    _mock_remote(
        monkeypatch,
        remote,
        revoke_started=revoke_started,
        allow_revoke=allow_revoke,
    )
    configure_attempting, configure_acquired = _observe_shared_lock(
        monkeypatch, contender_name="configure"
    )

    detach_result: dict = {}
    configure_result: dict = {}
    detaching = threading.Thread(target=_detach, args=(detach_result,))
    configuring = threading.Thread(
        target=_configure, args=(configure_result,), name="configure"
    )
    detaching.start()
    assert revoke_started.wait(WAIT_SECONDS)
    configuring.start()
    assert configure_attempting.wait(WAIT_SECONDS)
    assert not configure_acquired.wait(0.1)
    allow_revoke.set()
    detaching.join(WAIT_SECONDS)
    configuring.join(WAIT_SECONDS)

    assert not detaching.is_alive()
    assert not configuring.is_alive()
    assert detach_result["exit_code"] == 0
    assert configure_result["exit_code"] == 0
    assert _attachments(hosts_path) == [PROVIDER]
    assert remote["credential"] is True


def test_failed_configure_releases_lock_for_waiting_detach(tmp_path, monkeypatch):
    """A remote configure failure compensates state and never wedges detach."""
    hosts_path = _seed_disk_state(attached=False)
    remote = {"credential": False}
    write_started = threading.Event()
    allow_write = threading.Event()
    _mock_remote(
        monkeypatch,
        remote,
        write_started=write_started,
        allow_write=allow_write,
        fail_write=True,
    )
    detach_attempting, detach_acquired = _observe_shared_lock(
        monkeypatch, contender_name="detach"
    )

    configure_result: dict = {}
    detach_result: dict = {}
    configuring = threading.Thread(target=_configure, args=(configure_result,))
    detaching = threading.Thread(target=_detach, args=(detach_result,), name="detach")
    configuring.start()
    assert write_started.wait(WAIT_SECONDS)
    detaching.start()
    assert detach_attempting.wait(WAIT_SECONDS)
    assert not detach_acquired.wait(0.1)
    allow_write.set()
    configuring.join(WAIT_SECONDS)
    detaching.join(WAIT_SECONDS)

    assert not configuring.is_alive()
    assert not detaching.is_alive()
    assert configure_result["exit_code"] != 0
    # Detach acquired after configure rolled its first-time attachment back;
    # it therefore reports the provider absent instead of revoking it again.
    assert detach_result["exit_code"] != 0
    assert detach_acquired.is_set()
    assert _attachments(hosts_path) == []
    assert remote["credential"] is False


def test_pi_detach_persistence_failure_keeps_attachment_for_idempotent_retry(
    tmp_path, monkeypatch
):
    """Do not recreate a credential after a post-revoke metadata failure."""
    hosts_path = _seed_disk_state(attached=True)
    remote = {"credential": True}
    operations = []
    _mock_remote(monkeypatch, remote, operations=operations)
    original_set = provider_mod._set_attachments
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return False
        return original_set(*args)

    monkeypatch.setattr(provider_mod, "_set_attachments", fail_once)
    first = CliRunner().invoke(
        app, ["agent", "provider", "detach", PROVIDER, "--agent", AGENT]
    )

    assert first.exit_code != 0
    assert operations == ["revoke"]
    assert _attachments(hosts_path) == [PROVIDER]
    assert remote["credential"] is False
    assert "detach did not finish" in first.output
    assert "retry: clawctl agent provider detach router --agent pi-race" in first.output
    assert "test-openrouter-key" not in first.output

    second = CliRunner().invoke(
        app, ["agent", "provider", "detach", PROVIDER, "--agent", AGENT]
    )
    assert second.exit_code == 0, second.output
    assert operations == ["revoke", "revoke"]
    assert _attachments(hosts_path) == []
    assert remote["credential"] is False
