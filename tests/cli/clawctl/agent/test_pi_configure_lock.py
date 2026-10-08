"""Pi configure transaction uses the same reentrant lock as lifecycle sync."""

import json
import threading
from pathlib import Path

from clawrium.core.pi import pi_credential_lock


def _seed_pi_lock_identity(fleet_dir: Path) -> None:
    """Give the canonical lock resolver a real Pi hosts.json record."""
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["key_id"] = "wolf-i-stable-key"
    hosts[0]["agents"] = {
        "pi-configure-race": {
            "type": "pi",
            "agent_name": "pi-configure-race",
            "name": "pi-configure-race-alias",
            "providers": ["router"],
        }
    }
    hosts_path.write_text(json.dumps(hosts))


def test_pi_configure_lock_is_reentrant_and_releases_after_sync_failure(fleet_dir: Path):
    _seed_pi_lock_identity(fleet_dir)
    """Configure can call locked sync and a later detach can acquire the lock."""
    acquired = threading.Event()
    release = threading.Event()
    detached = threading.Event()

    def configure_with_failed_sync():
        try:
            with pi_credential_lock("pi-configure-race"):
                acquired.set()
                assert release.wait(1)
                # Canonical sync obtains the same lock inside configure.
                with pi_credential_lock("pi-configure-race"):
                    raise RuntimeError("sync failed")
        except RuntimeError:
            pass

    def detach():
        assert acquired.wait(1)
        with pi_credential_lock("pi-configure-race"):
            detached.set()

    first = threading.Thread(target=configure_with_failed_sync)
    second = threading.Thread(target=detach)
    first.start()
    second.start()
    assert not detached.wait(0.05)
    release.set()
    first.join(1)
    second.join(1)
    assert detached.is_set()
