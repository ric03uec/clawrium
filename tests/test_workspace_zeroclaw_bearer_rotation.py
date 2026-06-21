"""Bearer-rotation invariant for the canonical workspace phase
(issue #760 Phase 2 / #768, hot-path regression backstop for #437).

The contract being pinned, per AGENTS.md "Gateway Token Lifecycle
(zeroclaw)":

  `clawctl agent configure`, `clawctl agent sync`, and
  `clawctl agent restart` all mint a fresh bearer and overwrite
  `hosts.json.gateway.auth` atomically.  There is no idempotent-skip
  path.

The Phase 2 wiring (issue #768) extends the same invariant across all
three sync entry shapes:

  - default `clawctl agent sync <name>`
  - `clawctl agent sync <name> --no-restart`
  - `clawctl agent sync <name> --workspace-only`

These tests stub the dependencies of `sync_agent_canonical` at the
import sites so the canonical function's own bearer-rotation logic is
exercised without SSH / Ansible / network. The hook-review S
requirement makes every assertion `assert_called_once_with(...)` style
— loose `assert_called()` masks regressions where the repair fires
with the wrong agent / wrong reason / wrong hostname.
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
def make_canonical_stubs(monkeypatch: pytest.MonkeyPatch):
    """Factory: returns a stubs builder parametrized on `agent_type`
    so the same scaffolding drives the openclaw-negative and
    zeroclaw-positive cases."""

    def _build(agent_type: str):
        calls: list[str] = []

        inputs = MagicMock()
        inputs.agent_type = agent_type
        inputs.integrations = []

        def fake_build_render_inputs(_agent_name: str):
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
            return (host, agent_name, {"type": agent_type})

        def fake_diff_files(**_kwargs):
            return []

        fake_client = MagicMock()
        fake_client.close = lambda: None

        def fake_open_ssh(_host, *, timeout=15):
            return fake_client

        def fake_restart_unit(_client, *, agent_type, agent_name):
            calls.append(("restart", agent_type, agent_name))

        def fake_verify_health(_client, *, agent_type, agent_name):
            calls.append(("verify", agent_type, agent_name))

        monkeypatch.setattr(
            lifecycle_canonical,
            "build_render_inputs",
            fake_build_render_inputs,
        )
        monkeypatch.setitem(
            lifecycle_canonical._RENDERERS, agent_type, fake_renderer
        )
        monkeypatch.setattr(
            lifecycle_canonical, "get_agent_by_name", fake_get_agent_by_name
        )
        monkeypatch.setattr(
            lifecycle_canonical, "diff_files", fake_diff_files
        )
        monkeypatch.setattr(lifecycle_canonical, "_open_ssh", fake_open_ssh)
        monkeypatch.setattr(
            lifecycle_canonical, "_restart_unit", fake_restart_unit
        )
        monkeypatch.setattr(
            lifecycle_canonical, "_verify_health", fake_verify_health
        )

        # Suppress onboarding state transition — unrelated to bearer
        # rotation. Tests that explicitly want to assert the state
        # transition override this within the test body.
        monkeypatch.setattr(
            "clawrium.core.onboarding.transition_state",
            lambda *_a, **_k: None,
        )

        return calls

    return _build


def _fake_push_success(rel_files: tuple[str, ...] = ()) -> WorkspacePhaseResult:
    return WorkspacePhaseResult(
        success=True, files_pushed=rel_files, files_excluded=()
    )


# ---------------------------------------------------------------------------
# I-pair-A — default sync rotates bearer (zeroclaw)
# ---------------------------------------------------------------------------


def test_zeroclaw_default_sync_calls_repair_with_exact_args(
    make_canonical_stubs,
) -> None:
    """I-pair-A: full-flow rotation. After restart+verify, the
    canonical pipeline MUST call `_zeroclaw_repair_after_start` exactly
    once with the host, agent_name, callback, and reason=sync.

    Hook-review S — exact-argument `assert_called_once_with(...)`. The
    looser `assert_called()` would silently accept a regression that
    invoked the repair with the wrong agent or the wrong reason."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(return_value=(True, None))

    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = ".zeroclaw/config.toml"
    written_diff.remote_path = "/home/alice/.zeroclaw/config.toml"
    written_diff.rendered_body = "[]"

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch.object(
            lifecycle_canonical, "diff_files", return_value=[written_diff]
        ),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        result = sync_agent_canonical(
            "alice", force=False, restart=True, verify=True
        )

    assert result.success is True
    repair_mock.assert_called_once_with(
        "h.example",
        agent_name="alice",
        on_event=None,
        reason="sync",
    )


# ---------------------------------------------------------------------------
# I-pair-B — workspace-only sync rotates bearer (zeroclaw)
# ---------------------------------------------------------------------------


def test_zeroclaw_workspace_only_sync_calls_repair_with_exact_args(
    make_canonical_stubs,
) -> None:
    """I-pair-B + U28: `--workspace-only` MUST also rotate the bearer.
    Skipping rotation here was the regression class iter-2 protected
    (B2-NEW) and the original #437 bug shape: any sync entry point that
    skips re-pair leaves `hosts.json.gateway.auth` permanently stale on
    the next external daemon restart."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(return_value=(True, None))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(rel_files=("MARKER.md",)),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        result = sync_agent_canonical(
            "alice",
            workspace_only=True,
            restart=False,
            verify=False,
        )

    assert result.success is True
    assert result.workspace_files_pushed == ("MARKER.md",)
    # iter-1 lifecycle-core S5: reason is distinct per entry point so
    # `gateway_token_rotated` events are greppable by source.
    repair_mock.assert_called_once_with(
        "h.example",
        agent_name="alice",
        on_event=None,
        reason="workspace-only-sync",
    )


# ---------------------------------------------------------------------------
# I-pair-C — no-restart sync still rotates bearer (zeroclaw)
# ---------------------------------------------------------------------------


def test_zeroclaw_no_restart_sync_still_calls_repair(
    make_canonical_stubs,
) -> None:
    """I-pair-C: `--no-restart` skips `_restart_unit` but the bearer
    re-pair still runs unconditionally. AGENTS.md: an externally-driven
    daemon restart (host reboot, ops systemctl) would otherwise leave
    hosts.json stale."""
    calls = make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(return_value=(True, None))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical(
            "alice", force=False, restart=False, verify=False
        )

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
# I-pair-D — negative: openclaw NEVER calls repair
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
        pytest.param(
            {"restart": True, "verify": True}, id="default"
        ),
        pytest.param(
            {"restart": False, "verify": False}, id="no-restart"
        ),
        pytest.param(
            {"workspace_only": True, "restart": False, "verify": False},
            id="workspace-only",
        ),
    ],
)
def test_non_zeroclaw_never_calls_zeroclaw_repair(
    make_canonical_stubs,
    sync_kwargs: dict,
    agent_type: str,
    remote_path: str,
    rendered_body: str,
) -> None:
    """I-pair-D (openclaw + hermes cells, #769): bearer rotation is
    zeroclaw-specific. Openclaw's gateway uses a flat bearer in
    `hosts.json.gateway.auth` but it is NOT rotated by clawctl; the
    repair playbook does not exist for openclaw. Hermes has no
    pairing flow at all — its api_server bearer is generated once at
    install time and never rotated. Pinning both cells prevents a
    regression where the `agent_type == "zeroclaw"` guard is dropped
    or inverted (#769 completes the negative parametrization started
    in Phase 2)."""
    make_canonical_stubs(agent_type)

    repair_mock = MagicMock(return_value=(True, None))

    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = remote_path.split("/home/alice/")[1]
    written_diff.remote_path = remote_path
    written_diff.rendered_body = rendered_body

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch.object(
            lifecycle_canonical, "diff_files", return_value=[written_diff]
        ),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical("alice", **sync_kwargs)

    repair_mock.assert_not_called()


# ---------------------------------------------------------------------------
# I-pair-state / I17 — workspace-only does NOT transition state
# ---------------------------------------------------------------------------


def test_zeroclaw_workspace_only_does_not_transition_state(
    make_canonical_stubs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W5 iter-3 / I17: `--workspace-only` preserves the current
    lifecycle state. An operator may overlay onto a STOPPED zeroclaw
    agent without silently flipping it to READY.

    iter-1 test-coverage W2/W3: tighten to (a) exact-argument repair
    assertion (loose assert_called_once() would mask wrong-reason
    regressions), (b) explicit assertion that restart/verify did not
    fire on the workspace-only path."""
    calls = make_canonical_stubs("zeroclaw")

    transition_mock = MagicMock()
    monkeypatch.setattr(
        "clawrium.core.onboarding.transition_state", transition_mock
    )

    repair_mock = MagicMock(return_value=(True, None))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical(
            "alice",
            workspace_only=True,
            restart=False,
            verify=False,
        )

    # Bearer DID rotate (workspace-only is bound by the #437 invariant);
    # pin reason="workspace-only-sync" so the entry-point distinction
    # in operator logs cannot regress to the default `reason="sync"`.
    repair_mock.assert_called_once_with(
        "h.example",
        agent_name="alice",
        on_event=None,
        reason="workspace-only-sync",
    )
    # But the state-READY transition is NOT attempted.
    transition_mock.assert_not_called()
    # And neither restart nor verify ran (workspace-only short-circuits
    # before the canonical write loop).
    assert not any(c[0] in {"restart", "verify"} for c in calls), (
        f"workspace-only path should not call restart/verify, got: {calls}"
    )


# ---------------------------------------------------------------------------
# I-pair-state — failed repair on workspace-only short-circuits
# ---------------------------------------------------------------------------


def test_zeroclaw_workspace_only_push_failure_skips_repair(
    make_canonical_stubs,
) -> None:
    """iter-2 test-coverage W4: when the workspace push itself fails on
    the `--workspace-only` path, the bearer-rotation block MUST be
    skipped. Reordering the push-failure raise to land after bearer
    rotation would silently rotate the bearer on a half-applied
    overlay — the exact regression class the AGENTS.md short-circuit
    contract forbids.
    """
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock()
    events: list[tuple[str, str]] = []

    def on_event(stage: str, message: str) -> None:
        events.append((stage, message))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=WorkspacePhaseResult(
                success=False,
                files_pushed=(),
                files_excluded=(),
                error="forced workspace_only push failure",
            ),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        with pytest.raises(
            CanonicalSyncError, match=r"workspace overlay push failed"
        ):
            sync_agent_canonical(
                "alice",
                workspace_only=True,
                restart=False,
                verify=False,
                on_event=on_event,
            )

    # The push raised — repair MUST NOT have run.
    repair_mock.assert_not_called()
    # And no bearer-related events should have been emitted on the
    # short-circuited path.
    assert all(
        stage not in {"gateway_token_rotated", "gateway_auth_stale"}
        for stage, _ in events
    )


def test_zeroclaw_no_restart_repair_failure_says_restart_skipped(
    make_canonical_stubs,
) -> None:
    """iter-2 lifecycle-core W3: the user-facing CanonicalSyncError
    preamble on the main-branch re-pair-failure path must branch on
    `restart`. In --no-restart mode the preamble must NOT claim a
    restart that did not happen — operators would otherwise look for
    systemctl evidence that never existed.
    """
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(return_value=(False, "/pair returned 503"))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        with pytest.raises(CanonicalSyncError) as excinfo:
            sync_agent_canonical(
                "alice",
                force=False,
                restart=False,
                verify=False,
            )

    err = str(excinfo.value)
    assert "restart skipped" in err
    # The preamble MUST NOT claim a restart that never ran.
    assert "wrote and restarted" not in err


def test_zeroclaw_repair_failure_default_path_says_restarted(
    make_canonical_stubs,
) -> None:
    """iter-2 lifecycle-core W3 (positive pin): in default mode the
    preamble correctly claims the restart that did happen.
    """
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(return_value=(False, "/pair returned 503"))

    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = ".zeroclaw/config.toml"
    written_diff.remote_path = "/home/alice/.zeroclaw/config.toml"
    written_diff.rendered_body = "[]"

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch.object(
            lifecycle_canonical, "diff_files", return_value=[written_diff]
        ),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        with pytest.raises(CanonicalSyncError) as excinfo:
            sync_agent_canonical(
                "alice",
                force=False,
                restart=True,
                verify=True,
            )

    err = str(excinfo.value)
    assert "wrote and restarted 'alice'" in err
    assert "restart skipped" not in err


def test_zeroclaw_workspace_only_repair_failure_raises(
    make_canonical_stubs,
) -> None:
    """I-pair-state (workspace-only branch): when re-pair fails after
    workspace push, the canonical sync MUST raise CanonicalSyncError so
    the CLI's `except` clause routes it to exit code 1."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(
        return_value=(False, "/pair returned 500: gateway hung")
    )

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        with pytest.raises(CanonicalSyncError) as excinfo:
            sync_agent_canonical(
                "alice",
                workspace_only=True,
                restart=False,
                verify=False,
            )
    # iter-1 test-coverage W4: pin both the agent-name fragment AND the
    # upstream `repair_err` so a regression that drops `{repair_err}`
    # from the raise message (silently stripping the operator's only
    # diagnostic) is caught.
    err_msg = str(excinfo.value)
    assert "workspace-only sync wrote overlay for 'alice'" in err_msg
    # iter-2 test-coverage S4: pin the FULL repair_err string so a
    # regression that truncates the detail to its last token still
    # fails. The literal must match the stub's return value above.
    assert "/pair returned 500: gateway hung" in err_msg


# ---------------------------------------------------------------------------
# Dry-run gate (W6 iter-3) — no bearer mint, no event emission
# ---------------------------------------------------------------------------


def test_zeroclaw_workspace_only_dry_run_skips_bearer_rotation(
    make_canonical_stubs,
) -> None:
    """W6 iter-3 defense-in-depth: even if a programmatic caller passes
    `dry_run=True` alongside `workspace_only=True`, the bearer MUST NOT
    be minted and no `gateway_token_rotated` event MAY be emitted.

    iter-1 test-coverage W7: also pin that `push_workspace_phase` is
    invoked with `dry_run=True` — a regression that forwarded
    `dry_run=False` would cause the dry-run to actually write files."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock()
    push_mock = MagicMock(return_value=_fake_push_success())
    events: list[tuple[str, str]] = []

    def on_event(stage: str, message: str) -> None:
        events.append((stage, message))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            push_mock,
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical(
            "alice",
            workspace_only=True,
            restart=False,
            verify=False,
            dry_run=True,
            on_event=on_event,
        )

    repair_mock.assert_not_called()
    # push_workspace_phase MUST receive dry_run=True so it short-circuits
    # before any host write.
    push_mock.assert_called_once()
    assert push_mock.call_args.kwargs.get("dry_run") is True
    # No gateway_token_rotated / gateway_auth_stale events permitted.
    assert all(
        stage not in {"gateway_token_rotated", "gateway_auth_stale"}
        for stage, _ in events
    )


def test_zeroclaw_default_sync_dry_run_skips_bearer_rotation(
    make_canonical_stubs,
) -> None:
    """W6 iter-3 (main-path branch): `dry_run=True` on the default sync
    also bypasses re-pair."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock()

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        sync_agent_canonical(
            "alice",
            force=False,
            restart=True,
            verify=True,
            dry_run=True,
        )

    repair_mock.assert_not_called()


# ---------------------------------------------------------------------------
# I18 — stale-bearer banner (W11)
# ---------------------------------------------------------------------------


def test_zeroclaw_repair_failure_emits_stale_bearer_event_default_path(
    make_canonical_stubs,
) -> None:
    """I18 / W11 iter-3: when re-pair fails after a successful restart +
    verify, the canonical sync MUST emit a `gateway_auth_stale` NDJSON
    event before raising. Without this banner an operator sees a generic
    CanonicalSyncError and has no signal that the on-disk bearer is now
    out of sync with the daemon's enforced bearer."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(
        return_value=(False, "/pair returned 500: gateway hung")
    )

    events: list[tuple[str, str]] = []

    def on_event(stage: str, message: str) -> None:
        events.append((stage, message))

    written_diff = MagicMock()
    written_diff.unified_diff = "--- a\n+++ b\n"
    written_diff.path = ".zeroclaw/config.toml"
    written_diff.remote_path = "/home/alice/.zeroclaw/config.toml"
    written_diff.rendered_body = "[]"

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch.object(
            lifecycle_canonical, "diff_files", return_value=[written_diff]
        ),
        patch.object(lifecycle_canonical, "_atomic_write", return_value=None),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        with pytest.raises(CanonicalSyncError):
            sync_agent_canonical(
                "alice",
                force=False,
                restart=True,
                verify=True,
                on_event=on_event,
            )

    stale_events = [(s, m) for (s, m) in events if s == "gateway_auth_stale"]
    assert len(stale_events) == 1, (
        f"expected exactly one gateway_auth_stale event, got: {events}"
    )

    import json as _json

    payload = _json.loads(stale_events[0][1])
    assert payload["agent_key"] == "alice"
    assert payload["reason"] == "sync re-pair failed"
    # The repair detail surfaces in the structured event so the CLI
    # banner has a concrete starting point for the operator.
    assert "gateway hung" in payload["detail"]


def test_zeroclaw_workspace_only_repair_failure_emits_stale_bearer_event(
    make_canonical_stubs,
) -> None:
    """I18 (workspace-only branch): stale-bearer banner also fires on
    the `--workspace-only` re-pair failure path. Without this the
    operator running `clawctl agent sync --workspace-only` would see a
    bare exit-1 with no diagnostic on bearer state."""
    make_canonical_stubs("zeroclaw")

    repair_mock = MagicMock(
        return_value=(False, "/pair/code returned 401")
    )
    events: list[tuple[str, str]] = []

    def on_event(stage: str, message: str) -> None:
        events.append((stage, message))

    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        with pytest.raises(CanonicalSyncError):
            sync_agent_canonical(
                "alice",
                workspace_only=True,
                restart=False,
                verify=False,
                on_event=on_event,
            )

    stale_events = [(s, m) for (s, m) in events if s == "gateway_auth_stale"]
    assert len(stale_events) == 1
    import json as _json

    payload = _json.loads(stale_events[0][1])
    assert payload["agent_key"] == "alice"
    assert payload["reason"] == "workspace-only re-pair failed"
