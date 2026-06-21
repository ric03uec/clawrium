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


@pytest.mark.parametrize("flag", ["--workspace-only", "--no-restart"])
def test_flag_rejected_for_zeroclaw_in_phase_1(
    fleet_dir, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """ATX iter-2 B2-NEW: `--workspace-only` and `--no-restart` are
    gated away from zeroclaw in Phase 1 because bearer rotation wiring
    is deferred to Phase 2. Without this gate, running these flags
    against a zeroclaw agent silently leaves `hosts.json.gateway.auth`
    stale and `clawctl agent chat` returns 401 on the next daemon
    restart with no diagnostic.
    """
    # Patch the resolved agent type to zeroclaw without rebuilding the
    # fleet fixture. The CLI's safe_resolve_agent looks up by name; the
    # `wise-hypatia` agent in the fleet is openclaw, so we monkeypatch
    # the lookup to return a zeroclaw type.
    import clawrium.cli.clawctl.agent.sync as sync_mod

    real_resolve = sync_mod.safe_resolve_agent

    def fake_resolve(name: str):
        host, _agent_type, claw_record = real_resolve(name)
        claw_record = dict(claw_record)
        claw_record["type"] = "zeroclaw"
        return host, "zeroclaw", claw_record

    monkeypatch.setattr(sync_mod, "safe_resolve_agent", fake_resolve)

    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", flag])
    assert result.exit_code == 2, (
        f"{flag} on zeroclaw must exit 2 with a clear error; got "
        f"exit_code={result.exit_code}, output:\n{result.output}"
    )
    # Pin the canonical error-fragment string, not just a substring of
    # the agent type (W4 iter-3 tightening).
    assert "not supported for zeroclaw" in result.output
    assert "Phase 2" in result.output
