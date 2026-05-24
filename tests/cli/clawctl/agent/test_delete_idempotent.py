"""Tests for `clawctl agent delete` idempotency + error mapping (ATX iter-2 W5)."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_delete_already_removed_is_noop(fleet_dir, monkeypatch) -> None:
    """W5: re-running on an already-removed agent must exit 0, not fail."""
    from clawrium.core.lifecycle import LifecycleError

    def already_gone(**_kwargs):
        raise LifecycleError("Agent 'openclaw' not installed on 'wolf-i'")

    monkeypatch.setattr("clawrium.cli.clawctl.agent.delete.remove_agent", already_gone)
    result = runner.invoke(app, ["agent", "delete", "wise-hypatia", "--yes"])
    assert result.exit_code == 0
    assert "already deleted" in result.output


def test_delete_other_lifecycle_error_propagates(fleet_dir, monkeypatch) -> None:
    """Non-'not installed' LifecycleError must still fail loudly."""
    from clawrium.core.lifecycle import LifecycleError

    def host_unreachable(**_kwargs):
        raise LifecycleError("Connection timed out")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.delete.remove_agent", host_unreachable
    )
    result = runner.invoke(app, ["agent", "delete", "wise-hypatia", "--yes"])
    assert result.exit_code != 0
    assert "remote cleanup failed" in result.output


def test_delete_host_not_found_propagates(fleet_dir, monkeypatch) -> None:
    """ATX iter-3 W5: 'Host ... not found' MUST NOT be silently swallowed.

    The iter-2 guard matched both `'Agent ... not installed'` AND
    `'Host ... not found'`, so a genuine host-resolution failure would
    have been treated as an idempotent no-op. iter-3 narrows the match
    to `'not installed'` only.
    """
    from clawrium.core.lifecycle import LifecycleError

    def host_unknown(**_kwargs):
        raise LifecycleError("Host 'wolf-i' not found")

    monkeypatch.setattr("clawrium.cli.clawctl.agent.delete.remove_agent", host_unknown)
    result = runner.invoke(app, ["agent", "delete", "wise-hypatia", "--yes"])
    assert result.exit_code != 0
    assert "remote cleanup failed" in result.output
    assert "already deleted" not in result.output


def test_delete_success_false_errors(fleet_dir, monkeypatch) -> None:
    """B3 regression check: remove_agent returning {success: False} must fail."""

    def returns_failure(**_kwargs):
        return {"success": False, "error": "playbook rc=1"}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.delete.remove_agent", returns_failure
    )
    result = runner.invoke(app, ["agent", "delete", "wise-hypatia", "--yes"])
    assert result.exit_code != 0
    assert "playbook rc=1" in result.output
