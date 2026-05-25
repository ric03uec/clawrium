"""Issue #426 — single-provider invariant on `clawctl agent provider attach`.

The bridge in `core/lifecycle.sync_agent` materializes
`agent.providers[0]` into `config.provider` at reconcile time. Allowing
more than one attachment would silently ambiguate which one wins, so
`attach` hard-fails the 2nd attachment with a remediation pointer at
`detach`. Same-name re-attach stays idempotent.
"""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _create_provider(name: str) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            name,
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )


def test_second_distinct_attach_is_rejected(fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    _create_provider("openrt")
    first = runner.invoke(
        app, ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"]
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app, ["agent", "provider", "attach", "openrt", "--agent", "wise-hypatia"]
    )
    assert second.exit_code != 0
    assert "already has provider" in second.output
    # Hint must point at the right remediation surface.
    assert "detach" in second.output
    assert "anth" in second.output


def test_same_name_reattach_is_idempotent(fleet_dir, stdin_not_tty) -> None:
    """Idempotent re-attach of the same name is preserved (existing UX).
    The single-provider guard must not fire when the user re-runs the
    same attach command (e.g. a retry after a flaky network)."""
    _create_provider("anth")
    first = runner.invoke(
        app, ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"]
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app, ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"]
    )
    assert second.exit_code == 0
    assert "already attached" in second.output


def test_attach_after_detach_succeeds(fleet_dir, stdin_not_tty) -> None:
    """Detach + re-attach (potentially a different provider) is the
    documented replacement workflow. Verify the guard doesn't leak
    state across the detach boundary AND that the on-disk attachment
    list reflects the replacement.
    """
    import json

    _create_provider("anth")
    _create_provider("openrt")

    attach1 = runner.invoke(
        app, ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"]
    )
    assert attach1.exit_code == 0

    detach = runner.invoke(
        app, ["agent", "provider", "detach", "anth", "--agent", "wise-hypatia"]
    )
    assert detach.exit_code == 0

    attach2 = runner.invoke(
        app, ["agent", "provider", "attach", "openrt", "--agent", "wise-hypatia"]
    )
    assert attach2.exit_code == 0, attach2.output

    # ATX iter-1 B3: assert the *final* attachment list, not just exit
    # codes. A silent persistence-layer failure (or a regressed
    # idempotent-check after detach) would leave the list as ['anth'],
    # ['anth', 'openrt'], or [] — all of which would pass an exit-code
    # check alone.
    listed = runner.invoke(
        app,
        ["agent", "provider", "get", "--agent", "wise-hypatia", "-o", "json"],
    )
    assert listed.exit_code == 0
    data = json.loads(listed.output)
    names = sorted(p["name"] for p in data)
    assert names == ["openrt"], f"expected ['openrt'], got {names}"
