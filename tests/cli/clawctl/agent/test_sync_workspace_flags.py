"""CLI flag contracts for `clawctl agent sync` workspace overlay (#760).

Covers:
- `--workspace` hard error path (U32).
- `--workspace-only --diff` mutex (I7).
- `--workspace-only` short-circuit (no canonical render call) (I4).
- workspace-phase failure surfaces as a non-zero exit (S-cli-ux).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_deprecated_workspace_flag_is_hard_error(fleet_dir) -> None:
    """U32 — `--workspace` exits 2 with a hint to the replacement flags."""
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", "--workspace"])
    assert result.exit_code == 2
    assert "--workspace-only" in result.output
    assert "--no-restart" in result.output


def test_workspace_only_and_diff_are_mutually_exclusive(fleet_dir) -> None:
    """I7 — exits 2 with a clear message."""
    result = runner.invoke(
        app,
        ["agent", "sync", "wise-hypatia", "--workspace-only", "--diff"],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_workspace_only_and_no_restart_are_mutually_exclusive(
    fleet_dir,
) -> None:
    """ATX iter-1 B1: `--workspace-only` already implies skip-restart;
    `--no-restart` alongside it is ambiguous and must be rejected, not
    silently collapsed to workspace-only behavior."""
    result = runner.invoke(
        app,
        ["agent", "sync", "wise-hypatia", "--workspace-only", "--no-restart"],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output
    assert "--workspace-only" in result.output
    assert "--no-restart" in result.output


def test_workspace_only_short_circuits_canonical_render(
    fleet_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I4 — `--workspace-only` skips canonical render / restart / verify
    and invokes only the workspace push branch of
    `sync_agent_canonical`. The CLI is exercised end-to-end via Typer's
    CliRunner; `sync_agent_canonical` is stubbed to capture kwargs."""
    captured: dict = {}

    def fake_sync(agent_name: str, **kwargs):
        captured["agent_name"] = agent_name
        captured.update(kwargs)
        from clawrium.core.lifecycle_canonical import CanonicalSyncResult

        return CanonicalSyncResult(
            success=True,
            agent=agent_name,
            host="10.0.0.1",
            files_written=(),
            files_unchanged=(),
            diffs=(),
            workspace_files_pushed=("MARKER.md",),
            workspace_files_excluded=(),
        )

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.sync.sync_agent_canonical",
        fake_sync,
        raising=False,
    )
    # Above patch path may not exist (sync_agent_canonical is imported
    # inside the function). Patch the source binding too.
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        fake_sync,
    )

    result = runner.invoke(
        app,
        ["agent", "sync", "wise-hypatia", "--workspace-only"],
    )
    assert result.exit_code == 0, result.output
    # workspace_only=True flows through.
    assert captured.get("workspace_only") is True
    # restart/verify are suppressed.
    assert captured.get("restart") is False
    assert captured.get("verify") is False


def test_workspace_phase_failure_exits_nonzero(
    fleet_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S-cli-ux — workspace-phase failure surfaces as a non-zero exit.

    The CanonicalSyncError prefix `"workspace overlay push failed"` is
    what `lifecycle_canonical.sync_agent_canonical` raises when the
    inserted phase fails before restart; the CLI must surface this as a
    non-zero exit (the existing `emit_error` path already raises
    `typer.Exit(code=1)` internally).
    """
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    def fake_sync(*_args, **_kwargs):
        raise CanonicalSyncError(
            "workspace overlay push failed for wise-hypatia: stub failure"
        )

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        fake_sync,
    )

    result = runner.invoke(app, ["agent", "sync", "wise-hypatia"])
    assert result.exit_code != 0
    assert "workspace overlay push failed" in result.output


def test_gateway_auth_stale_banner_renders_to_stderr(
    fleet_dir, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """iter-1 test-coverage W1 + cli-ux W3 (Phase 2 / #768): the new
    `gateway_auth_stale` banner is rendered to stderr (not stdout) with
    a yellow warning, includes the recovery commands, and runs both
    operator-controlled fields (`agent_key`, `detail`) through
    `sanitize_passthrough` so bidi / zero-width codepoints cannot
    spoof terminal output.
    """
    from clawrium.core.lifecycle_canonical import (
        CanonicalSyncError,
        CanonicalSyncResult,  # noqa: F401  imported for side-effect import path
    )

    # `sync_agent_canonical` is stubbed to:
    #   1. emit a gateway_auth_stale event with a hostile agent_key
    #      and detail (bidi LRE U+202A embedded)
    #   2. raise CanonicalSyncError to mirror the real flow
    HOSTILE_KEY = "alice‪hidden"
    HOSTILE_DETAIL = "pair returned 500: gateway‫hung"

    def fake_sync(_name: str, *, on_event=None, **_kwargs):
        import json as _json

        if on_event is not None:
            on_event(
                "gateway_auth_stale",
                _json.dumps(
                    {
                        "agent_key": HOSTILE_KEY,
                        "reason": "sync re-pair failed",
                        "detail": HOSTILE_DETAIL,
                    }
                ),
            )
        raise CanonicalSyncError(
            "sync wrote and restarted 'wise-hypatia' but the gateway "
            "re-pair failed: stub failure"
        )

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        fake_sync,
    )

    # Use a runner that does not merge stderr into stdout so we can pin
    # the stderr-only contract.
    runner_split = CliRunner()
    result = runner_split.invoke(app, ["agent", "sync", "wise-hypatia"])

    assert result.exit_code != 0
    # Banner must surface on stderr.
    assert "Gateway bearer" in result.stderr
    assert "stale" in result.stderr
    # Tightened remediation text (lifecycle-core W2): includes restart,
    # falls through to doctor.
    assert "clawctl agent restart" in result.stderr
    assert "doctor" in result.stderr
    # Bidi-safety: U+202A / U+202B MUST NOT appear verbatim in either
    # stream after sanitize_passthrough.
    assert "‪" not in result.stderr
    assert "‫" not in result.stderr


def test_gateway_auth_stale_banner_tolerates_malformed_payload(
    fleet_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The banner handler must not raise on a malformed JSON payload;
    it falls back to the generic 'zeroclaw agent' label."""
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    def fake_sync(_name: str, *, on_event=None, **_kwargs):
        if on_event is not None:
            on_event("gateway_auth_stale", "{not valid json")
        raise CanonicalSyncError("stub failure")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        fake_sync,
    )

    runner_split = CliRunner()
    result = runner_split.invoke(app, ["agent", "sync", "wise-hypatia"])
    # Must exit on the raised CanonicalSyncError, not on a banner-handler
    # exception. Without the JSONDecodeError catch, the handler would
    # raise inside `on_event` and the test would surface an unrelated
    # exception trace in `result.exception`.
    assert result.exit_code != 0
    assert "zeroclaw agent" in result.stderr


@pytest.mark.parametrize("flag", ["--workspace-only", "--no-restart"])
def test_flag_accepted_for_zeroclaw_in_phase_2(
    fleet_dir, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """ATX iter-1 cli-ux B1 (Phase 2 / #768): Phase 1 of #760 gated
    `--workspace-only` / `--no-restart` away from zeroclaw because
    bearer-rotation wiring was deferred. Phase 2 wires
    `_zeroclaw_repair_after_start` into both branches of
    `sync_agent_canonical` so the gate is lifted. This test pins the
    inversion: a zeroclaw agent invoked with either flag must reach the
    canonical sync layer (no exit-2, no "not supported" error)."""
    import clawrium.cli.clawctl.agent.sync as sync_mod

    real_resolve = sync_mod.safe_resolve_agent

    def fake_resolve(name: str):
        host, _agent_type, claw_record = real_resolve(name)
        claw_record = dict(claw_record)
        claw_record["type"] = "zeroclaw"
        return host, "zeroclaw", claw_record

    monkeypatch.setattr(sync_mod, "safe_resolve_agent", fake_resolve)

    # Stub the canonical pipeline so we can assert it was reached; we
    # don't care about its return value here.
    from clawrium.core.lifecycle_canonical import CanonicalSyncResult

    canonical_calls: list[dict] = []

    def fake_sync(name: str, **kwargs) -> CanonicalSyncResult:
        canonical_calls.append({"name": name, **kwargs})
        return CanonicalSyncResult(
            success=True,
            agent=name,
            host="h",
            files_written=(),
            files_unchanged=(),
            diffs=(),
            error=None,
            workspace_files_pushed=(),
            workspace_files_excluded=(),
        )

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        fake_sync,
    )

    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", flag])
    assert result.exit_code == 0, (
        f"{flag} on zeroclaw must reach the canonical sync layer; got "
        f"exit_code={result.exit_code}, output:\n{result.output}"
    )
    assert "not supported for zeroclaw" not in result.output
    assert len(canonical_calls) == 1
    if flag == "--workspace-only":
        assert canonical_calls[0]["workspace_only"] is True
    else:
        assert canonical_calls[0]["restart"] is False
        assert canonical_calls[0]["verify"] is False
