"""Tests for `clawctl agent configure` error-path handling (ATX iter-3 W4/W6)."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

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
    assert "stage rejected" in result.output
