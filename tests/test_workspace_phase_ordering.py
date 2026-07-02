"""Phase ordering + short-circuit pins for the canonical workspace phase
(issue #760 ATX iter-1 B2 + B3).

- B2 (plan I8): when the workspace push returns failure,
  `_restart_unit` MUST NOT be called. The canonical pipeline raises
  `CanonicalSyncError` and exits before restart so the daemon is never
  flapped on a half-applied overlay.
- B3: the phase order is [push_workspace → restart → verify]. A
  refactor that reordered these would silently pass every other test;
  this test pins the sequence with a shared call-order list.

Both tests patch the dependencies of `sync_agent_canonical` at the
import sites so the canonical function's own logic exercises end-to-end
without SSH / Ansible / network. The shared helper
`_invoke_canonical_with_stubs` wires the minimum mock surface needed
for the canonical pipeline to reach the workspace + restart branch.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clawrium.core import lifecycle_canonical
from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    sync_agent_canonical,
)
from clawrium.core.workspace_sync import WorkspacePhaseResult


@pytest.fixture
def canonical_stubs(monkeypatch: pytest.MonkeyPatch):
    """Patch the dependencies of `sync_agent_canonical` so the function's
    own phase-ordering logic is exercised without touching SSH / Ansible.

    Returns a `calls` list that downstream patches push into in the
    order the canonical pipeline invokes them.
    """
    calls: list[str] = []

    inputs = MagicMock()
    inputs.agent_type = "openclaw"
    inputs.integrations = []

    def fake_build_render_inputs(agent_name: str):
        return inputs

    def fake_renderer(_inputs):
        return MagicMock(files={})

    def fake_get_agent_by_name(agent_name: str):
        host = {
            "hostname": "h.example",
            "key_id": "h.example",
            "user": "xclm",
            "os_family": "linux",
        }
        return (host, agent_name, {"type": "openclaw"})

    def fake_diff_files(**_kwargs):
        return []  # no canonical drift → no writes

    fake_client = MagicMock()
    fake_client.close = lambda: None

    def fake_open_ssh(_host, *, timeout=15):
        return fake_client

    def fake_restart_unit(_client, *, agent_type, agent_name, **_kwargs):
        calls.append("restart")

    def fake_verify_health(_client, *, agent_type, agent_name, **_kwargs):
        calls.append("verify")

    monkeypatch.setattr(
        lifecycle_canonical, "build_render_inputs", fake_build_render_inputs
    )
    monkeypatch.setitem(
        lifecycle_canonical._RENDERERS, "openclaw", fake_renderer
    )
    monkeypatch.setattr(
        lifecycle_canonical, "get_agent_by_name", fake_get_agent_by_name
    )
    monkeypatch.setattr(
        lifecycle_canonical, "diff_files", fake_diff_files
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_open_ssh", fake_open_ssh
    )
    # #811: validate-phase host probe defaults to "install present" so
    # the phase-ordering invariants under test stay isolated from the
    # new short-circuit. Tests that want the missing-install path can
    # re-monkeypatch this in the test body.
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
    monkeypatch.setattr(
        lifecycle_canonical, "_restart_unit", fake_restart_unit
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_verify_health", fake_verify_health
    )

    # Suppress the onboarding state transition — it pokes hosts.json and
    # is unrelated to the phase-ordering invariants we are asserting.
    monkeypatch.setattr(
        "clawrium.core.onboarding.transition_state",
        lambda *_a, **_k: None,
    )

    return calls


def test_workspace_failure_short_circuits_before_restart(
    canonical_stubs,
) -> None:
    """B2 / plan I8: workspace push failure raises CanonicalSyncError
    and `_restart_unit` is NEVER called."""

    def fake_push(**_kwargs):
        canonical_stubs.append("push_workspace")
        return WorkspacePhaseResult(
            success=False,
            files_pushed=(),
            files_excluded=(),
            error="simulated workspace failure",
        )

    with patch(
        "clawrium.core.workspace_sync.push_workspace_phase",
        side_effect=fake_push,
    ):
        with pytest.raises(CanonicalSyncError, match="workspace overlay push failed"):
            sync_agent_canonical(
                "alice", force=False, restart=True, verify=True
            )

    # The workspace push ran exactly once; restart + verify never did.
    assert canonical_stubs == ["push_workspace"], (
        f"phase short-circuit broken: expected only push_workspace, "
        f"got {canonical_stubs}"
    )


def test_workspace_only_failure_raises_canonical_sync_error(
    canonical_stubs,
) -> None:
    """ATX iter-2 B1-NEW: the workspace_only early-return path used to
    return `CanonicalSyncResult(success=False)` rather than raising.
    The CLI never inspects `.success`, so the operator would see
    `synced (drift=0)` with exit 0. Pin that the path raises
    `CanonicalSyncError` so the CLI's existing `except` clause routes
    it to `emit_error` (exit code 1).
    """

    def fake_push(**_kwargs):
        canonical_stubs.append("push_workspace")
        return WorkspacePhaseResult(
            success=False,
            files_pushed=(),
            files_excluded=(),
            error="forced workspace_only failure",
        )

    with patch(
        "clawrium.core.workspace_sync.push_workspace_phase",
        side_effect=fake_push,
    ):
        with pytest.raises(
            CanonicalSyncError,
            # S5 iter-3: pin the agent name in the message so a regression
            # that drops `{agent_name!r}` from the raise is caught.
            match=r"workspace overlay push failed for 'alice'",
        ):
            sync_agent_canonical(
                "alice",
                workspace_only=True,
                restart=False,
                verify=False,
            )

    # No restart/verify in the workspace_only path either.
    assert canonical_stubs == ["push_workspace"], (
        f"workspace_only short-circuit broken: expected only "
        f"push_workspace, got {canonical_stubs}"
    )


def test_phase_order_is_push_workspace_then_restart_then_verify(
    canonical_stubs,
) -> None:
    """B3: pins the canonical sequence so a refactor that reordered
    these would fail loudly."""

    def fake_push(**_kwargs):
        canonical_stubs.append("push_workspace")
        return WorkspacePhaseResult(
            success=True,
            files_pushed=(),
            files_excluded=(),
        )

    # Force a canonical write so the restart branch is reached. Provide
    # one synthetic file with a non-empty diff so the write loop fires
    # and `files_written` is non-empty.
    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = ".openclaw/openclaw.json"
    written_diff.remote_path = "/home/alice/.openclaw/openclaw.json"
    written_diff.rendered_body = "{}"
    written_diff.remote_body = ""

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            side_effect=fake_push,
        ),
        patch.object(lifecycle_canonical, "diff_files", return_value=[written_diff]),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
    ):
        result = sync_agent_canonical(
            "alice", force=False, restart=True, verify=True
        )

    assert result.success is True
    assert canonical_stubs == ["push_workspace", "restart", "verify"], (
        f"phase order regression: expected "
        f"['push_workspace', 'restart', 'verify'], got {canonical_stubs}"
    )
