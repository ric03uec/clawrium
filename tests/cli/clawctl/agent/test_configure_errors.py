"""Tests for `clawctl agent configure` error-path handling (ATX iter-3 W4/W6)."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

# `emit_error` writes to stderr. Current CliRunner (Click 8.2+) merges
# stderr into `result.output` by default, which is what makes
# "<text> in result.output" assertions on error paths work below.
runner = CliRunner()


def test_configure_agent_not_found_during_init_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """W4 regression: `initialize_onboarding` racing with delete must
    surface a clean error, not a raw traceback.
    """
    from clawrium.core.onboarding import AgentNotFoundError, OnboardingState

    # Make get_onboarding_state return PENDING so initialize_onboarding runs.
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_onboarding_state",
        lambda *_a, **_k: OnboardingState.PENDING,
    )

    def init_race(*_args, **_kwargs):
        raise AgentNotFoundError("agent 'wise-hypatia' vanished")

    monkeypatch.setattr("clawrium.core.onboarding.initialize_onboarding", init_race)
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "validate",
        ],
    )
    assert result.exit_code != 0
    assert "agent record disappeared" in result.output


def test_configure_invalid_transition_surfaces_distinct_hint(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """W6 regression: state-machine rejection must NOT collapse into the
    opaque `configure stage failed:` text — operator needs to know it's
    a state issue, not a network/SSH failure.
    """
    from clawrium.core.onboarding import InvalidTransitionError, OnboardingState

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_onboarding_state",
        lambda *_a, **_k: OnboardingState.READY,
    )

    def reject(*_args, **_kwargs):
        raise InvalidTransitionError("cannot transition READY → PROVIDERS")

    monkeypatch.setattr("clawrium.cli.clawctl.agent.configure.run_stage", reject)

    # Issue #541: `--stage providers --provider X` no longer routes
    # through `run_stage`; it goes through `sync_agent`. Use a stage
    # that still delegates to `run_stage` to exercise the W6 path.
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "validate",
        ],
    )
    assert result.exit_code != 0
    assert "stage rejected" in result.output
    # W5: the remediation hint is the operationally meaningful part of
    # the contract — assert it explicitly so it can't be silently
    # deleted from configure.py.
    assert "clawctl agent describe" in result.output


def test_providers_stage_agent_not_found_during_init_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """B6 regression: the structurally identical race-recovery block in
    the providers branch must surface the same clean error as the
    non-providers path.
    """
    from clawrium.core.onboarding import AgentNotFoundError, OnboardingNotFoundError

    def raise_missing(*_a, **_k):
        raise OnboardingNotFoundError("no onboarding record")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_onboarding_state",
        raise_missing,
    )

    def init_race(*_args, **_kwargs):
        raise AgentNotFoundError("agent 'wise-hypatia' vanished")

    monkeypatch.setattr("clawrium.core.onboarding.initialize_onboarding", init_race)
    # No `get_provider` stub needed — the test exits via emit_error in
    # the initialize_onboarding race path *before*
    # `_attach_provider_for_configure` (which is where `get_provider`
    # would be called) is reached.

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "anthropic",
        ],
    )
    assert result.exit_code != 0
    assert "agent record disappeared" in result.output


def test_run_stage_lifecycle_error_surfaces_configure_failed_message(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """ATX iter-3 W6: `run_stage` raising `LifecycleError` in the
    non-providers path must surface a clean 'configure stage failed'
    message — the existing test only covers `InvalidTransitionError`.
    """
    from clawrium.core.lifecycle import LifecycleError
    from clawrium.core.onboarding import OnboardingState

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_onboarding_state",
        lambda *_a, **_k: OnboardingState.READY,
    )

    def raise_lifecycle(*_a, **_k):
        raise LifecycleError("ansible exited 1")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.run_stage", raise_lifecycle
    )

    result = runner.invoke(
        app,
        ["agent", "configure", "wise-hypatia", "--stage", "validate"],
    )

    assert result.exit_code != 0
    assert "configure stage failed" in result.output
    assert "ansible exited 1" in result.output


def test_run_stage_returns_false_surfaces_did_not_complete(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """ATX iter-3 W6: `run_stage` returning `False` must surface a
    'did not complete' message via the `success` guard.
    """
    from clawrium.core.onboarding import OnboardingState

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_onboarding_state",
        lambda *_a, **_k: OnboardingState.READY,
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.run_stage",
        lambda *_a, **_k: False,
    )

    result = runner.invoke(
        app,
        ["agent", "configure", "wise-hypatia", "--stage", "validate"],
    )

    assert result.exit_code != 0
    assert "did not complete" in result.output


def test_channels_stage_deprecation_fires_before_agent_lookup(fleet_dir) -> None:
    """ATX iter-3 W5: the `--stage channels` deprecation guard is
    hoisted above `safe_resolve_agent` so a typo'd agent name surfaces
    the actionable deprecation hint, not a misleading 'agent not found'
    error. Pin the ordering with a regression test.
    """
    result = runner.invoke(
        app,
        ["agent", "configure", "NO-SUCH-AGENT", "--stage", "channels"],
    )
    assert result.exit_code == 1
    assert "deprecated" in result.output
    assert "not found" not in result.output
