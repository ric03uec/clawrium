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

from clawrium.cli.clawctl._common import stdin_is_tty
from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.hosts import HostsFileCorruptedError, update_host
from clawrium.core.lifecycle import LifecycleError, sync_agent
from clawrium.core.playbook_resolver import resolve_lifecycle_backend
from clawrium.core.onboarding import (
    AgentNotFoundError,
    InvalidTransitionError,
    OnboardingNotFoundError,
    OnboardingState,
    get_onboarding_state,
    run_stage,
)
from clawrium.core.providers.storage import (
    ProvidersFileCorruptedError,
    get_provider,
)


def _attach_provider_for_configure(
    agent_name: str, hostname: str, agent_key: str, provider_name: str
) -> None:
    """Write `agents.<key>.providers = [provider_name]` for issue #541.

    Differs from `clawctl agent provider attach` in one critical way:
    the verb is *replace*, not *append*. The customer outcome on #541
    requires that `clawctl agent configure --stage providers --provider X`
    can be called any number of times — including to switch the
    attached provider — without manually detaching first. The
    Pattern A `attach` surface refuses to replace by design (#426
    single-provider invariant), so the configure path performs the
    replacement inline.
    """
    # ATX iter-2 B3 / iter-3 W1+W4: broaden the catch so a missing,
    # unreadable, or structurally malformed `providers.json` surfaces a
    # clean message instead of a raw traceback. `str(OSError)` formats
    # as `[Errno 2] ... '/home/<user>/.config/clawrium/providers.json'`
    # — the full path including the username leaks. For OS-level
    # exceptions, surface the type only and steer the operator to the
    # canonical config path in the hint.
    record: dict | None = None
    try:
        record = get_provider(provider_name)
    except ProvidersFileCorruptedError as exc:
        emit_error(
            str(exc),
            hint="check ~/.config/clawrium/providers.json (clawctl provider registry get)",
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        emit_error(
            f"could not read providers file: {type(exc).__name__}",
            hint="check ~/.config/clawrium/providers.json (clawctl provider registry get)",
        )
    except (KeyError, ValueError, TypeError) as exc:
        emit_error(
            f"providers file structurally invalid: {type(exc).__name__}",
            hint="check ~/.config/clawrium/providers.json",
        )
    if not record:
        emit_error(
            f"provider {provider_name!r} not registered",
            hint="clawctl provider registry get",
        )

    # ATX iter-2 B3: persist the canonical name from the registry record,
    # not the raw CLI argument. `get_provider` is case- and shape-
    # tolerant; downstream lifecycle code reads `agents.<n>.providers`
    # and looks up the provider by *that* exact string.
    canonical_name = record.get("name", provider_name)

    def updater(h: dict) -> dict:
        agents = h.get("agents", {})
        if agent_key not in agents or not isinstance(agents[agent_key], dict):
            raise LifecycleError(
                f"agent record for {agent_name!r} missing from host {hostname!r}"
            )
        agents[agent_key]["providers"] = [canonical_name]
        return h

    # ATX iter-3 W1: `update_host` can raise `HostsFileCorruptedError`
    # (malformed hosts.json) or `OSError` (atomic-write fs failure) in
    # addition to `LifecycleError`. Catch the lot so a fs/IO failure
    # surfaces a clean message rather than a raw traceback leaking
    # `~/.config/clawrium/hosts.json` path internals.
    try:
        update_host(hostname, updater)
    except LifecycleError as exc:
        emit_error(
            str(exc),
            hint="clawctl agent get to verify state, then retry",
        )
    except HostsFileCorruptedError as exc:
        emit_error(
            str(exc),
            hint="inspect ~/.config/clawrium/hosts.json before retrying",
        )
    except OSError as exc:
        # ATX iter-3 W4: do not leak the absolute hosts.json path via
        # `str(OSError)`. Surface the error type only.
        emit_error(
            f"could not write hosts.json: {type(exc).__name__}",
            hint="inspect ~/.config/clawrium/hosts.json before retrying",
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

    # Bug #516: `safe_resolve_agent` returns the *type string* as its
    # second tuple element (per its own docstring). The dict key used
    # to identify the agent on its host (and as `agent_name` in core
    # lifecycle calls) requires a second-pass lookup. Without this,
    # any host with >1 agent of the same type breaks lifecycle ops.
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", _agent_type)

    if stage is None:
        # Non-interactive contract: stdin closed + no stage = clean failure.
        if not stdin_is_tty():
            emit_error(
                "missing required flag --stage",
                hint="pass --stage providers|identity|validate",
            )
        # ATX iter-2 W2: stale hint pointed at the retired `clawctl` binary;
        # the kubectl-style rewrite replaced it.
        emit_error(
            "interactive multi-stage configure not yet exposed via clawctl",
            hint="run a specific stage with --stage providers|identity|validate",
        )

    # ATX iter-2 B1: `--provider` is unconditionally required when the
    # providers stage is selected. `require_flag` defers on a TTY so
    # without this guard a `--stage providers` invocation on an
    # interactive terminal would fall through to the placeholder
    # `run_stage` path, silently corrupting the onboarding record
    # (exactly the bug #541 exists to fix).
    if stage is Stage.providers:
        if not provider:
            emit_error(
                "missing required flag --provider",
                hint="pass --provider <name> (see 'clawctl provider registry get')",
            )

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

    # Issue #541: the providers stage was previously routed through
    # `run_stage`, which is a placeholder that only flips the per-stage
    # status flag — it never pushes config to the host and never advances
    # the onboarding state machine. That left the agent stuck at
    # `state=pending` and blocked every subsequent stage (`identity`,
    # `validate`) and `agent start`.
    #
    # Route `--stage providers --provider X` through the real reconcile
    # path: write the attachment into `agents.<name>.providers` (Pattern A
    # from #426/#509), then call `sync_agent`. `sync_agent` builds the
    # provider overlay, walks the state machine (PENDING → PROVIDERS →
    # ... → READY, honoring per-manifest `auto_skip`), and pushes the
    # configuration via Ansible. This makes the verb idempotent on a
    # `ready` agent (re-attaching the same or a different provider stays
    # in `ready`) and unblocks the remaining stages.
    if stage is Stage.providers and provider is not None:
        # Ensure the onboarding record exists so `sync_agent`'s
        # state-machine walk has something to transition. Mirrors the
        # PENDING-recovery branch below for the non-providers path.
        try:
            get_onboarding_state(hostname, agent_key)
        except OnboardingNotFoundError:
            from clawrium.core.onboarding import initialize_onboarding

            try:
                initialize_onboarding(hostname, agent_key)
            except AgentNotFoundError as exc:
                emit_error(
                    f"agent record disappeared during configure: {exc}",
                    hint="rerun clawctl agent get to verify",
                )

        # ATX iter-3 W3: wrap the attach call so any unexpected
        # exception (TypeError/ValueError/etc.) from registry handling
        # surfaces as a clean CLI error rather than a raw traceback
        # leaking config paths.
        try:
            _attach_provider_for_configure(name, hostname, agent_key, provider)
        except (typer.Exit, SystemExit):
            raise
        except Exception as exc:
            emit_error(
                f"configure stage failed: {exc}",
                hint=f"clawctl agent describe {name}",
            )

        def on_event(stage_evt: str, message: str) -> None:
            # ATX iter-2 W1: forward all sync progress events (ansible
            # phases take 30–60s; previously the operator saw a frozen
            # cursor). Mirrors how `clawctl agent sync` surfaces events.
            stream_action(resource=f"agent/{name}", message=f"[{stage_evt}] {message}")

        # ATX iter-2 S6/W7 parity with the non-providers path: pre-bind
        # `result` so a non-LifecycleError that escapes the try block
        # does not raise `UnboundLocalError` at the `result.get(...)`
        # check below.
        result: dict = {}
        try:
            # OS-family dispatch (CLI layer). #469 step 1 invariant:
            # core/lifecycle.py must NOT branch on Darwin. lifecycle_macos
            # wraps sync_agent so the post-configure launchctl restart
            # fires after the macOS configure playbook completes (B2).
            # For Linux we keep the existing `sync_agent` symbol so
            # downstream tests that monkeypatch
            # `clawrium.cli.clawctl.agent.configure.sync_agent` keep
            # working unchanged.
            os_family = host.get("os_family", "linux")
            if os_family == "linux":
                sync_fn = sync_agent
            else:
                sync_fn = resolve_lifecycle_backend(os_family).sync_agent
            result = sync_fn(
                hostname=hostname,
                claw_name=agent_type,
                agent_name=agent_key,
                on_event=on_event,
            )
        except LifecycleError as exc:
            emit_error(
                f"configure stage failed: {exc}",
                hint=f"clawctl agent describe {name}",
            )
        except (typer.Exit, SystemExit):
            # ATX iter-3 W2: `emit_error` raises `typer.Exit`. If
            # `sync_agent` (or any helper it calls) ever invokes
            # `emit_error` internally, the bare `except Exception`
            # below would re-wrap the exit into a vacuous "configure
            # stage failed" message that masks the real cause. Let the
            # exit propagate unmodified.
            raise
        except Exception as exc:  # ATX iter-2 B2: parity with non-providers path
            emit_error(
                f"configure stage failed: {exc}",
                hint=f"clawctl agent describe {name}",
            )

        if not result.get("success"):
            emit_error(
                f"configure stage failed: {result.get('error') or 'unknown error'}",
                hint=f"clawctl agent describe {name}",
            )

        stream_action(
            resource=f"agent/{name}", message=f"stage {stage.value} complete"
        )
        return

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
        emit_error(
            f"configure stage failed: {exc}",
            hint=f"clawctl agent describe {name}",
        )
    except InvalidTransitionError as exc:
        # ATX iter-2 W6: surface state-machine rejection distinctly from
        # opaque network/lifecycle errors so the operator knows the
        # remediation is "fix the agent's onboarding state", not "retry".
        emit_error(
            f"configure stage rejected: {exc}",
            hint=f"clawctl agent describe {name}",
        )
    except (typer.Exit, SystemExit):
        # ATX iter-3 W2: do not re-wrap propagating CLI exits. See the
        # matching branch in the providers path above.
        raise
    except Exception as exc:  # core.onboarding may raise misc errors
        emit_error(
            f"configure stage failed: {exc}",
            hint=f"clawctl agent describe {name}",
        )

    if not success:
        emit_error(
            f"stage {stage.value!r} did not complete",
            hint=f"clawctl agent describe {name}",
        )
    stream_action(resource=f"agent/{name}", message=f"stage {stage.value} complete")
