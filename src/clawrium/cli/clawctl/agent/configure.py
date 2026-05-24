"""`clawctl agent configure <name>` — non-interactive (+TTY fallback) configure.

Plan §"Specific Outcomes":
    `clawctl agent configure <n> --stage validate` runs validate stage
    non-interactively.

The full per-stage rewrite (providers/identity/channels/validate) with
flag-driven inputs and Discord/Slack extraction lives in bundle 4
(#509). This bundle wraps the existing legacy `cli/agent.py:configure`
flow so the surface exists, the `--stage` flag works, and the
non-interactive contract is enforced for the `validate` stage (the one
the bundle's acceptance criteria call out by name).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import typer

from clawrium.cli.clawctl._common import require_flag, stdin_is_tty
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.lifecycle import LifecycleError
from clawrium.core.onboarding import (
    AgentNotFoundError,
    InvalidTransitionError,
    OnboardingNotFoundError,
    OnboardingState,
    get_onboarding_state,
    run_stage,
)


class Stage(str, Enum):
    providers = "providers"
    identity = "identity"
    channels = "channels"
    validate = "validate"


def configure(
    name: str = typer.Argument(..., help="Agent name."),
    stage: Optional[Stage] = typer.Option(
        None,
        "--stage",
        help="Specific stage to run (providers/identity/channels/validate).",
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Provider name (when --stage=providers)."
    ),
    personality: Optional[str] = typer.Option(
        None, "--personality", help="Personality preset (when --stage=identity)."
    ),
    channel: Optional[list[str]] = typer.Option(
        None, "--channel", help="Channel name to attach. Repeatable."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmations."),
) -> None:
    """Configure an agent (per-stage, non-interactive when flags supplied)."""
    host, agent_key, claw_record = safe_resolve_agent(name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", agent_key)

    if stage is None:
        # Non-interactive contract: stdin closed + no stage = clean failure.
        if not stdin_is_tty():
            emit_error(
                "missing required flag --stage",
                hint="pass --stage providers|identity|channels|validate",
            )
        emit_error(
            "interactive multi-stage configure not yet exposed via clawctl",
            hint=(
                "run a specific stage with --stage, or use legacy "
                "'clm agent configure' until bundle 4"
            ),
        )

    # Provider stage requires provider flag (or TTY for prompt fallback).
    if stage is Stage.providers:
        require_flag(provider, flag="--provider")
    if stage is Stage.channels and not channel and not stdin_is_tty():
        require_flag(channel, flag="--channel")

    stream_action(
        resource=f"agent/{name}", message=f"configure stage={stage.value} on {hostname}"
    )

    # ATX iter-1 B4: `get_onboarding_state` raises `OnboardingNotFoundError`
    # for any pre-onboarding-schema agent (or when install.py's Step 11
    # non-fatally silently failed). Treat as PENDING and run the
    # initialize path rather than letting the traceback escape.
    try:
        state = get_onboarding_state(hostname, agent_key)
    except OnboardingNotFoundError:
        state = OnboardingState.PENDING
    if state == OnboardingState.PENDING:
        from clawrium.core.onboarding import initialize_onboarding

        # ATX iter-2 W4: `initialize_onboarding` raises
        # `AgentNotFoundError` on race/concurrent edit (agent record
        # deleted between resolve and initialize). Bound the
        # exception inline rather than letting the traceback escape.
        try:
            initialize_onboarding(hostname, agent_key)
        except AgentNotFoundError as exc:
            emit_error(
                f"agent record disappeared during configure: {exc}",
                hint="rerun clawctl agent get to verify",
            )

    # ATX iter-3 S7: pre-bind `success` for parity with delete.py/sync.py
    # so a non-LifecycleError that escapes the try block cannot trigger
    # an `UnboundLocalError`. Dormant today (emit_error is NoReturn);
    # defensive bind future-proofs the contract.
    success: bool = False
    try:
        success = run_stage(agent_type, hostname, agent_key, stage.value)
    except LifecycleError as exc:
        emit_error(f"configure stage failed: {exc}")
    except InvalidTransitionError as exc:
        # ATX iter-2 W6: surface state-machine rejection distinctly from
        # opaque network/lifecycle errors so the operator knows the
        # remediation is "fix the agent's onboarding state", not "retry".
        emit_error(
            f"configure stage rejected: {exc}",
            hint=f"clawctl agent describe {name}",
        )
    except Exception as exc:  # core.onboarding may raise misc errors
        emit_error(f"configure stage failed: {exc}")

    if not success:
        emit_error(
            f"stage {stage.value!r} did not complete",
            hint=f"clawctl agent describe {name}",
        )
    stream_action(resource=f"agent/{name}", message=f"stage {stage.value} complete")
