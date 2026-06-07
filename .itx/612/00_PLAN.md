# Issue #612 — CLI `--role` flag on provider attach + detach-primary guard

Subtask 1 of 4 under parent #589 (hermes multi-provider end-to-end).

## Scope (frozen)

CLI surface only. **Hermes-only behaviors.** zeroclaw/openclaw
singleton invariant stays untouched and its `single-provider invariant`
phrase from `core/provider_attachments.validate()` remains pinned.

## Changes

- Add `--role` Typer option on `clawctl agent provider attach`.
  - Required on hermes (`primary` for the first attachment, one of the
    nine `AUXILIARY_SLOTS` for subsequent ones).
  - Rejected on non-hermes with a clear remediation message.
- Replace the unconditional singleton rejection at the old
  `provider.py:106-118` with a `not supports_multi_provider(agent_type)`
  gate, so the existing zeroclaw/openclaw `already has provider`
  message keeps firing.
- Read/write attachments through `provider_attachments.normalize()` /
  `validate()`. No duplicated invariants in the CLI layer.
- Hermes detach-primary guard: refuse `detach <primary-name>` when
  any auxiliary attachments remain. Hint enumerates the exact
  `clawctl agent provider detach` commands the operator must run
  first. Promotion is explicitly out of scope.
- `clawctl agent provider get`: for multi-provider agents, render
  `NAME / ROLE / MODEL / AGENT` columns; for singleton agents, keep
  the existing flat `NAME / AGENT` layout for back-compat.

## Out of scope

- Per-attachment API-key hydration (subtask 2).
- Template rendering of `auxiliary.<role>` (subtask 3).
- GUI parity (subtask 4).
- `set-role` / promote-to-primary command.

## Test surface

`tests/cli/clawctl/provider/test_agent_attach_hermes_multi.py`
covers:

- Attach without `--role` rejected on hermes
- Attach with `--role primary` succeeds
- Aux attach after primary
- Invalid `--role` value rejected
- Duplicate-primary attach rejected (via `validate()`)
- Same-name re-attach with mismatched role rejected
- Idempotent re-attach with matching role
- `get` table renders ROLE + MODEL columns
- Detach-primary blocked while aux present
- Detach-primary OK when alone
- Aux-then-primary detach sequence
- Non-hermes rejects `--role`
- Non-hermes singleton invariant (verbatim `single-provider invariant`
  phrase) preserved at the `validate()` level

## Refs

- `src/clawrium/cli/clawctl/agent/provider.py`
- `src/clawrium/core/provider_attachments.py`
- Parent: #589
