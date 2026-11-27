"""Bearer-rotation invariant for the canonical sync pipeline.

Hot-path regression backstop for #437 (lifted from the pre-#1071
workspace-phase test file).

The contract being pinned, per AGENTS.md "Gateway Token Lifecycle
(zeroclaw)":

  `clawctl agent configure`, `clawctl agent sync`, and
  `clawctl agent restart` all mint a fresh bearer and overwrite
  `hosts.json.gateway.auth` atomically. There is no idempotent-skip
  path.

Post-#1071 phase 3b the workspace-overlay sync path is gone, so the
`--workspace-only` sync entry point no longer exists. The remaining
two entry shapes are pinned here:

  - default `clawctl agent sync <name>`
  - `clawctl agent sync <name> --no-restart`

These tests stub the dependencies of `sync_agent_canonical` at the
import sites so the canonical function's own bearer-rotation logic is
exercised without SSH / Ansible / network. Every assertion is
`assert_called_once_with(...)` so a regression that fires with the
wrong agent / wrong reason / wrong hostname trips a test.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clawrium.core import lifecycle_canonical
from clawrium.core.lifecycle_canonical import sync_agent_canonical


@pytest.fixture
def make_canonical_stubs(monkeypatch: pytest.MonkeyPatch):
    """Factory: returns a stubs builder parametrized on `agent_type`
    so the same scaffolding drives the openclaw-negative and
    zeroclaw-positive cases.

    `os_family` defaults to `"linux"` but can be overridden to
    `"darwin"` to exercise the macOS code path. The bearer-rotation
    invariant is OS-agnostic (it lives in `lifecycle_canonical`, not
    in the playbook), so the same default + --no-restart tests must
    hold under both OS families.
    """

    def _build(agent_type: str, os_family: str = "linux"):
        calls: list[tuple] = []

        inputs = MagicMock()
        inputs.agent_type = agent_type
        inputs.integrations = []

        def fake_build_render_inputs(_agent_name: str):
            return inputs

        def fake_renderer(_inputs, **_kwargs):
            # #835 (pre-#1071): lifecycle_canonical threads `os_family=`
            # for hermes and openclaw renderers. Accept and ignore so
            # the stub stays call-signature agnostic.
            return MagicMock(files={})

        def fake_get_agent_by_name(agent_name: str):
            host = {
                "hostname": "h.example",
                "key_id": "h.example",
                "user": "xclm",
                "os_family": os_family,
            }
            return (host, agent_name, {"type": agent_type})

        def fake_diff_files(**_kwargs):
            return []

        fake_client = MagicMock()
        fake_client.close = lambda: None

        def fake_open_ssh(_host, *, timeout=15):
            return fake_client

        def fake_restart_unit(_client, *, agent_type, agent_name, **_kwargs):
            calls.append(("restart", agent_type, agent_name))

        def fake_verify_health(_client, *, agent_type, agent_name, **_kwargs):
            calls.append(("verify", agent_type, agent_name))

        monkeypatch.setattr(
            lifecycle_canonical,
            "build_render_inputs",
            fake_build_render_inputs,
        )
        monkeypatch.setitem(lifecycle_canonical._RENDERERS, agent_type, fake_renderer)
        monkeypatch.setattr(
            lifecycle_canonical, "get_agent_by_name", fake_get_agent_by_name
        )
        monkeypatch.setattr(lifecycle_canonical, "diff_files", fake_diff_files)
        monkeypatch.setattr(lifecycle_canonical, "_open_ssh", fake_open_ssh)
        # #811: validate-phase host probe defaults to "install present"
        # so the bearer-rotation invariants under test stay isolated
        # from the short-circuit.
        monkeypatch.setattr(
            lifecycle_canonical,
            "probe_host_install",
            lambda *_a, **_kw: lifecycle_canonical.HostInstallProbe(
                unit_present=True,
                home_present=True,
                unit_path="/etc/systemd/system/x.service",
                home_path="/home/x/.x",
            ),
        )
        monkeypatch.setattr(lifecycle_canonical, "_restart_unit", fake_restart_unit)
        monkeypatch.setattr(lifecycle_canonical, "_verify_health", fake_verify_health)

        # Suppress onboarding state transition — unrelated to bearer
        # rotation.
        monkeypatch.setattr(
            "clawrium.core.onboarding.transition_state",
            lambda *_a, **_k: None,
        )

        return calls

    return _build


# ---------------------------------------------------------------------------
# I-pair-A — default sync rotates bearer (zeroclaw)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_zeroclaw_default_sync_calls_repair_with_exact_args(
    make_canonical_stubs, os_family: str
) -> None:
    """Full-flow rotation. After restart+verify, the canonical pipeline
    MUST call `_zeroclaw_repair_after_start` exactly once with the host,
    agent_name, callback, and reason=sync.

    The darwin parametrization pins that the repair gate at
    `lifecycle_canonical` is NOT additionally gated on os_family — a
    regression that narrowed it to "linux only" would silently
    reintroduce the #437 stale-bearer bug on every macOS sync.
    """
    make_canonical_stubs("zeroclaw", os_family=os_family)

    repair_mock = MagicMock(return_value=(True, None))

    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = ".zeroclaw/config.toml"
    home_prefix = "/Users" if os_family == "darwin" else "/home"
    written_diff.remote_path = f"{home_prefix}/alice/.zeroclaw/config.toml"
    written_diff.rendered_body = "[]"

    with (
        patch.object(lifecycle_canonical, "diff_files", return_value=[written_diff]),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        result = sync_agent_canonical("alice", force=False, restart=True, verify=True)

    assert result.success is True
    repair_mock.assert_called_once_with(
        "h.example",
        agent_name="alice",
        on_event=None,
        reason="sync",
    )


# ---------------------------------------------------------------------------
# I-pair-C — --no-restart sync still rotates bearer (zeroclaw)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_zeroclaw_no_restart_sync_still_calls_repair(
    make_canonical_stubs, os_family: str
) -> None:
    """`--no-restart` skips `_restart_unit` but the bearer re-pair
    still runs unconditionally. AGENTS.md: an externally-driven daemon
    restart (host reboot, ops systemctl) would otherwise leave
    hosts.json stale.
    """
    calls = make_canonical_stubs("zeroclaw", os_family=os_family)

    repair_mock = MagicMock(return_value=(True, None))

    with (
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical("alice", force=False, restart=False, verify=False)

    # No restart unit ran (operator asked to skip it).
    restart_calls = [c for c in calls if c[0] == "restart"]
    assert restart_calls == []

    repair_mock.assert_called_once_with(
        "h.example",
        agent_name="alice",
        on_event=None,
        reason="sync",
    )


# ---------------------------------------------------------------------------
# I-pair-D — negative: openclaw / hermes NEVER call zeroclaw repair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_type,remote_path,rendered_body",
    [
        pytest.param(
            "openclaw",
            "/home/alice/.openclaw/openclaw.json",
            "{}",
            id="openclaw",
        ),
        pytest.param(
            "hermes",
            "/home/alice/.hermes/config.yaml",
            "version: 1\n",
            id="hermes",
        ),
    ],
)
@pytest.mark.parametrize(
    "sync_kwargs",
    [
        pytest.param({"restart": True, "verify": True}, id="default"),
        pytest.param({"restart": False, "verify": False}, id="no-restart"),
    ],
)
@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_non_zeroclaw_never_calls_zeroclaw_repair(
    make_canonical_stubs,
    sync_kwargs: dict,
    agent_type: str,
    remote_path: str,
    rendered_body: str,
    os_family: str,
) -> None:
    """Bearer rotation is zeroclaw-specific. Openclaw's gateway uses a
    flat bearer in `hosts.json.gateway.auth` but it is NOT rotated by
    clawctl; the repair playbook does not exist for openclaw. Hermes
    has no pairing flow at all — its api_server bearer is generated
    once at install time and never rotated. Pinning both cells across
    both OS families prevents a regression where the `agent_type ==
    "zeroclaw"` guard is dropped or inverted, or accidentally gated on
    os_family.
    """
    make_canonical_stubs(agent_type, os_family=os_family)

    repair_mock = MagicMock(return_value=(True, None))

    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = remote_path.split("/home/alice/")[1]
    written_diff.remote_path = remote_path
    written_diff.rendered_body = rendered_body

    with (
        patch.object(lifecycle_canonical, "diff_files", return_value=[written_diff]),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
        patch.object(lifecycle_canonical, "_hermes_reconcile_herdr", return_value=None),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical("alice", **sync_kwargs)

    repair_mock.assert_not_called()
