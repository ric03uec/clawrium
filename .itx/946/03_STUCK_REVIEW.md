# Issue #946 — GPT-5.5 Stuck-Review Gate

**Date**: 2026-07-26
**Branch**: `issue-946-provider-credentials-gateway`
**Base**: `issue-945-delete-bare-openclaw`
**Reviewer**: PI harness / GPT-5.5

## Gate Summary

ATX-style rating after this pass: **4/5**.

All blockers that can be fixed safely in this PR have been fixed. The
remaining blocker is a product/API decision outside this repository:
parent-plan §7.5 must define the real upstream NemoClaw gateway provider
registration contract before Clawrium can wire production configure/sync
behavior.

## Feasible Blockers Fixed

1. `CHANGELOG.md` no longer claims that `clawctl agent configure`
   already registers provider credentials with NemoClaw. The entry now
   scopes this PR to canonical render stripping plus the guarded builder.
2. `openclaw.plist.j2` no longer says provider API keys live in
   `.openclaw/env`.
3. `NemoclawCommand.__repr__` redacts both split flag/value secrets and
   `--api-key=value` style secrets.
4. `gateway_register_provider(...)` is fail-closed by default. It only
   returns the best-guess argv when a future caller passes
   `upstream_cli_shape_confirmed=True`, preventing the guessed ITX-STUCK
   CLI shape from becoming production behavior silently.
5. Tests now assert raw provider secret/value absence from canonical
   openclaw env output, not only env-var-name absence.

## Remaining Decision for Devashish (§7.5)

Devashish must choose the production contract for handing provider
credentials to NemoClaw's gateway.

### Option A — Confirm the guessed argv contract

Use:

```text
nemoclaw <sandbox> gateway provider add <name> --api-key <key> --base-url <url>
```

Pros:
- Smallest follow-up diff; current builder already models this shape.
- Easy to wire from Python/Ansible once confirmed.

Cons:
- Places provider bearers in argv, where they may be visible in process
  listings, debug logs, shell history, or Ansible artifacts unless every
  executor is carefully no-logged/redacted.

### Option B — Require a secret-safe handoff (recommended)

Define NemoClaw registration as one of:

```text
nemoclaw <sandbox> gateway provider add <name> --base-url <url> --api-key-stdin
nemoclaw <sandbox> gateway provider add <name> --base-url <url> --api-key-env NEMOCLAW_PROVIDER_API_KEY
nemoclaw <sandbox> gateway provider add <name> --base-url <url> --api-key-file <0600-tempfile>
```

Pros:
- Avoids putting raw provider bearers in argv/process listings.
- Aligns with the security motivation for removing credentials from the
  sandbox env.

Cons:
- Requires upstream support or a confirmed wrapper contract before wiring.

### Option C — Do not have Clawrium register providers yet

Keep Clawrium from managing gateway credentials and document an explicit
operator NemoClaw step for custom providers.

Pros:
- Honest and safe if NemoClaw does not expose a stable registration API.

Cons:
- Breaks the parent-plan goal that users never need to touch NemoClaw CLI
  directly for provider setup.

## Recommended Default

Choose **Option B**: a stdin/env/file-based secret handoff. It preserves
the security benefit this phase is trying to deliver and avoids replacing
"credential in sandbox env" with "credential in process argv".

Until Devashish chooses, this PR should remain `[ITX-STUCK]` and must not
be merged into a branch that ships to operators.

## Verification

- `make lint` — pass
- `make test` — pass (`4733 passed, 8 skipped`; GUI `329 passed`)
