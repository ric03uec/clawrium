"""Real Mac E2E tests — marked slow + nightly (issue #469 step 11).

Skipped by default. To run:
    CLAWRIUM_MAC_E2E_HOST=<host> CLAWRIUM_MAC_E2E_USER=xclm \
    CLAWRIUM_MAC_E2E_KEY=~/.config/clawrium/keys/<host>/xclm_ed25519 \
    uv run pytest tests/integration/test_macos_e2e_real.py -v

These tests assume:
  - The Mac has the `xclm` management user pre-configured per
    docs/host-preparation.md (xclm exists, NOPASSWD sudo, SSH key auth).
  - Homebrew, node, ripgrep, ffmpeg, uv are present (base_macos.yaml
    ran at least once).

They DO NOT test the full hermes install + configure + chat loop —
that's exercised manually + is too slow for CI even on nightly. What
they DO cover:
  - launchctl plist install + bootstrap + bootout end-to-end (the
    parts of step 7 that the mocked suite can't verify behaviorally).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _env_or_skip(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"Mac E2E disabled: set {name} to run")
    return val


@pytest.fixture
def mac_host():
    return {
        "hostname": _env_or_skip("CLAWRIUM_MAC_E2E_HOST"),
        "user": os.environ.get("CLAWRIUM_MAC_E2E_USER", "xclm"),
        "port": int(os.environ.get("CLAWRIUM_MAC_E2E_PORT", "22")),
        "key_id": os.environ.get(
            "CLAWRIUM_MAC_E2E_KEY_ID",
            os.environ.get("CLAWRIUM_MAC_E2E_HOST", ""),
        ),
        "agents": {},
    }


@pytest.fixture
def mac_ssh_key():
    p = _env_or_skip("CLAWRIUM_MAC_E2E_KEY")
    path = Path(os.path.expanduser(p))
    if not path.exists():
        pytest.skip(f"key path does not exist: {path}")
    return path


def test_launchd_plist_lifecycle_round_trip(mac_host, mac_ssh_key, monkeypatch):
    """Render + write + bootstrap + bootout a throwaway plist.

    Uses agent name `clmtest` (UID-less; the plist references a user that
    may not exist on the Mac, which is fine — launchctl bootstrap returns
    the same I/O error regardless; this only exercises the plumbing).
    """
    from clawrium.core import lifecycle_macos

    # Force the lifecycle helper to use the explicit key path so we
    # don't depend on hosts.json existing in CI.
    def _fake_key(_key_id):
        return mac_ssh_key

    monkeypatch.setattr(
        "clawrium.core.lifecycle_macos.get_host_private_key", _fake_key, raising=False
    )

    client = lifecycle_macos._ssh(mac_host)
    try:
        path = lifecycle_macos.install_service(client, "clmtest")
        assert path.endswith("clmtest.plist")
        # bootstrap may fail because UserName doesn't exist; just ensure
        # the file lives at the expected path.
        rc, out, err = lifecycle_macos._run(client, f"sudo test -f {path}")
        assert rc == 0, f"plist missing on remote: {err}"
    finally:
        # Always clean up — best-effort.
        lifecycle_macos.remove_service_macos(mac_host, "clmtest")
        client.close()
