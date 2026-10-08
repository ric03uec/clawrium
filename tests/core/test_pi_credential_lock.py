"""End-to-end race regression coverage for Pi credential lifecycle (#1038)."""

import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.config import get_config_dir
from clawrium.core.lifecycle_canonical import CanonicalSyncError, sync_agent_canonical
from clawrium.core.providers.storage import set_provider_api_key

runner = CliRunner()


def _seed_disk_state() -> Path:
    """Create the real local control-plane state used by sync and detach."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "wolf-i",
                    "key_id": "wolf-i-stable-key",
                    "os_family": "linux",
                    "agents": {
                        "pi-race": {
                            "type": "pi",
                            "agent_name": "pi-race",
                            "name": "pi-race-alias",
                            "providers": ["router"],
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
                    "name": "router",
                    "type": "openrouter",
                    "default_model": "openai/gpt-4o",
                }
            ]
        )
    )
    set_provider_api_key("router", "test-openrouter-key")
    return config_dir / "hosts.json"


def _providers(hosts_path: Path) -> list:
    return json.loads(hosts_path.read_text())[0]["agents"]["pi-race"]["providers"]


def _mock_sync_remote(monkeypatch, remote, *, started=None, release=None):
    """Mock only SSH and the remote private credential operation."""

    class Channel:
        def recv_exit_status(self):
            return 0

    class Stream:
        channel = Channel()

        def read(self):
            return b""

    class Client:
        def exec_command(self, command, timeout):
            remote.setdefault("cache_cleanup_requests", []).append((command, timeout))
            return Stream(), Stream(), Stream()

        def close(self):
            pass

    def environment_operation(_client, *, body, **_kwargs):
        if body is not None:
            if started is not None:
                started.set()
            if release is not None:
                assert release.wait(2)
            remote["credential"] = True

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


def _run_sync(result):
    try:
        result["value"] = sync_agent_canonical("pi-race")
    except Exception as exc:  # asserted by the calling deterministic ordering test
        result["error"] = exc


def _run_detach(result):
    result["value"] = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-race"]
    )


def test_pi_lock_refuses_unresolved_or_nonimmutable_identity(tmp_path):
    """Never fall back to a lock keyed by an untrusted agent string."""
    hosts_path = _seed_disk_state()
    hosts = json.loads(hosts_path.read_text())
    hosts[0].pop("key_id")
    hosts_path.write_text(json.dumps(hosts))

    from clawrium.core.pi import PiProvisioningError, pi_credential_lock

    with pytest.raises(PiProvisioningError, match="could not be resolved"):
        with pi_credential_lock("pi-race"):
            pass


def test_pi_aliases_share_one_stable_disk_backed_lock_and_release_on_failure(
    tmp_path,
):
    """Record-name aliases cannot run credential lifecycle work concurrently."""
    _seed_disk_state()
    from clawrium.core.pi import pi_credential_lock

    acquired = threading.Event()
    release = threading.Event()
    alias_waiting = threading.Event()
    alias_entered = threading.Event()

    def primary() -> None:
        try:
            with pi_credential_lock("pi-race"):
                acquired.set()
                assert release.wait(2)
                raise RuntimeError("expected failure")
        except RuntimeError:
            pass

    def alias() -> None:
        assert acquired.wait(2)
        alias_waiting.set()
        with pi_credential_lock("pi-race-alias"):
            alias_entered.set()

    primary_thread = threading.Thread(target=primary)
    alias_thread = threading.Thread(target=alias)
    primary_thread.start()
    assert acquired.wait(2)
    alias_thread.start()
    assert alias_waiting.wait(2)
    assert not alias_entered.wait(0.05)
    release.set()
    primary_thread.join(2)
    alias_thread.join(2)

    assert not primary_thread.is_alive()
    assert not alias_thread.is_alive()
    assert alias_entered.is_set()


def test_pi_sync_first_then_detach_keeps_remote_credential_absent(
    tmp_path, monkeypatch
):
    """A queued final detach wins after an already-started full sync."""
    hosts_path = _seed_disk_state()
    remote = {"credential": False}
    sync_started = threading.Event()
    allow_sync_write = threading.Event()
    _mock_sync_remote(
        monkeypatch,
        remote,
        started=sync_started,
        release=allow_sync_write,
    )

    def revoke(**_kwargs):
        remote["credential"] = False

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke)
    # Keep the real flock and announce immediately before the detach attempts
    # it, so releasing sync cannot race ahead of the detach lock request.
    from clawrium.core import pi as pi_mod

    detach_waiting_for_lock = threading.Event()
    real_lock = pi_mod.pi_credential_lock

    @contextmanager
    def observed_lock(agent_name):
        if threading.current_thread().name == "detach-after-sync":
            detach_waiting_for_lock.set()
        with real_lock(agent_name):
            yield

    monkeypatch.setattr(pi_mod, "pi_credential_lock", observed_lock)
    sync_result = {}
    detach_result = {}
    syncing = threading.Thread(target=_run_sync, args=(sync_result,))
    detaching = threading.Thread(
        target=_run_detach, args=(detach_result,), name="detach-after-sync"
    )
    syncing.start()
    assert sync_started.wait(2)
    detaching.start()
    assert detach_waiting_for_lock.wait(2)
    assert detaching.is_alive()
    allow_sync_write.set()
    syncing.join(2)
    detaching.join(2)

    assert not syncing.is_alive()
    assert not detaching.is_alive()
    assert "error" not in sync_result
    assert detach_result["value"].exit_code == 0, detach_result["value"].output
    assert _providers(hosts_path) == []
    assert remote["credential"] is False
    assert len(remote["cache_cleanup_requests"]) == 1


def test_pi_detach_first_prevents_queued_sync_from_restoring_credential(
    tmp_path, monkeypatch
):
    """Sync re-reads durable attachments after detach releases the lock."""
    hosts_path = _seed_disk_state()
    remote = {"credential": True}
    revocation_started = threading.Event()
    allow_revocation = threading.Event()
    _mock_sync_remote(monkeypatch, remote)

    def revoke(**_kwargs):
        revocation_started.set()
        assert allow_revocation.wait(2)
        remote["credential"] = False

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke)
    # Observe the real lock boundary without replacing it: the sync thread
    # announces immediately before attempting flock, then must remain blocked
    # until the in-flight CLI detach finishes remote revocation and persistence.
    from clawrium.core import pi as pi_mod

    sync_waiting_for_lock = threading.Event()
    real_lock = pi_mod.pi_credential_lock

    @contextmanager
    def observed_lock(agent_name):
        if threading.current_thread().name == "sync-after-detach":
            sync_waiting_for_lock.set()
        with real_lock(agent_name):
            yield

    monkeypatch.setattr(pi_mod, "pi_credential_lock", observed_lock)
    detach_result = {}
    sync_result = {}
    detaching = threading.Thread(target=_run_detach, args=(detach_result,))
    syncing = threading.Thread(
        target=_run_sync, args=(sync_result,), name="sync-after-detach"
    )
    detaching.start()
    assert revocation_started.wait(2)
    syncing.start()
    assert sync_waiting_for_lock.wait(2)
    assert syncing.is_alive()
    allow_revocation.set()
    detaching.join(2)
    syncing.join(2)

    assert not detaching.is_alive()
    assert not syncing.is_alive()
    assert detach_result["value"].exit_code == 0, detach_result["value"].output
    assert isinstance(sync_result.get("error"), CanonicalSyncError)
    assert "exactly one attached" in str(sync_result["error"])
    assert _providers(hosts_path) == []
    assert remote["credential"] is False


def test_pi_detach_remote_failure_releases_lock_for_later_sync(tmp_path, monkeypatch):
    """A failed revocation leaves the attachment durable and never wedges sync."""
    hosts_path = _seed_disk_state()
    remote = {"credential": False}
    _mock_sync_remote(monkeypatch, remote)

    def revoke(**_kwargs):
        raise CanonicalSyncError("remote revoke failed")

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke)
    detached = runner.invoke(
        app, ["agent", "provider", "detach", "router", "--agent", "pi-race"]
    )

    assert detached.exit_code != 0
    assert _providers(hosts_path) == ["router"]
    synced = sync_agent_canonical("pi-race")
    assert synced.success is True
    assert remote["credential"] is True
    assert len(remote["cache_cleanup_requests"]) == 1
