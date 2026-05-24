"""`clawctl agent configure <name>` — non-interactive (+TTY fallback) configure.

Bundle 4 (#509) closes Risk R3 from the parent plan: the `channels`
stage no longer prompts for Discord/Slack input here. Channel
configuration moves into the dedicated `clawctl channel registry
create` + `clawctl agent channel attach` surfaces. Invoking
`clawctl agent configure <n> --stage channels` now exits with a
deprecation notice that points at the replacement commands.

The remaining stages (`providers`, `identity`, `validate`) continue
to delegate to the legacy `clawrium.core.onboarding.run_stage`. The
non-interactive contract still applies: when stdin is not a TTY and a
mandatory stage flag is missing, the verb fails fast (plan §7).
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
        help=(
            "Specific stage to run. Valid: providers, identity, validate. "
            "'channels' is deprecated — use 'clawctl channel registry' instead."
        ),
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Provider name (when --stage=providers)."
    ),
    personality: Optional[str] = typer.Option(
        None, "--personality", help="Personality preset (when --stage=identity)."
    ),
    channel: Optional[list[str]] = typer.Option(
        None,
        "--channel",
        help=(
            "DEPRECATED: channels are now managed via 'clawctl channel "
            "registry create' + 'clawctl agent channel attach'."
        ),
    ),
) -> None:
    """Configure an agent (per-stage, non-interactive when flags supplied)."""
    # ATX iter-2 B2 / W-NEW-5: argument-shape rejections fire before
    # `safe_resolve_agent` so a typo'd agent name combined with a
    # deprecated flag surfaces the actionable deprecation hint, not a
    # misleading "agent not found" error.
    if channel:
        emit_error(
            "--channel is no longer supported on 'clawctl agent configure'",
            hint=(
                "use 'clawctl channel registry create <name> ...' and "
                f"'clawctl agent channel attach <name> --agent {name}'"
            ),
        )
    if stage is Stage.channels:
        # R3 closure: --stage channels is deprecated in favour of the
        # dedicated channel surfaces. Exit with a clear pointer; no
        # Discord/Slack prompts here.
        emit_error(
            "'clawctl agent configure --stage channels' is deprecated",
            hint=(
                "use 'clawctl channel registry create <name> --type ... ...' "
                "and 'clawctl agent channel attach <name> --agent " + name + "'"
            ),
        )

    host, agent_key, claw_record = safe_resolve_agent(name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", agent_key)

    if stage is None:
        # Non-interactive contract: stdin closed + no stage = clean failure.
        if not stdin_is_tty():
            emit_error(
                "missing required flag --stage",
                hint="pass --stage providers|identity|validate",
            )
        # ATX iter-2 W2: stale hint pointed at the retired `clm` binary;
        # the kubectl-style rewrite replaced it.
        emit_error(
            "interactive multi-stage configure not yet exposed via clawctl",
            hint="run a specific stage with --stage providers|identity|validate",
        )

    # Provider stage requires provider flag (or TTY for prompt fallback).
    if stage is Stage.providers:
        require_flag(provider, flag="--provider")

    # ATX iter-2 B1: `--personality` flowed into the verb signature but
    # nothing read it back out. Until `run_stage` accepts a personality
    # override, refuse the flag with an explicit pointer rather than
    # accept-and-drop.
    if personality is not None:
        emit_error(
            "--personality is not wired into 'clawctl agent configure' yet",
            hint=(
                "follow up in a separate issue; for now set personality via "
                "'clawctl agent edit " + name + "'"
            ),
        )

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
