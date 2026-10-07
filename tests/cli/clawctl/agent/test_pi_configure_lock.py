"""Pi configure transaction uses the same reentrant lock as lifecycle sync."""

import threading

from clawrium.core.pi import pi_credential_lock


def test_pi_configure_lock_is_reentrant_and_releases_after_sync_failure():
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
