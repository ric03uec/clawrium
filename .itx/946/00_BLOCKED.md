# Issue #946 — Phase 4 Execution BLOCKED

**Date**: 2026-07-25
**Branch**: `issue-946-provider-credentials-gateway` (stacked on `issue-945-delete-bare-openclaw`)
**Executor**: `/itx:execute 946 --pr-base=issue-945-delete-bare-openclaw`

## Block

Phase 4 fails its own **entry criterion** documented in the issue body and
`.itx/11/00_PLAN.md` §7.5:

> Owner has answered plan §7.5 (blueprint override path — reconcile
> "no Clawrium blueprint" with "NemoClaw CLI never exposed to end users"
> for custom providers).

§7.5 is unresolved. The orchestrator update on issue #11 (2026-07-25T01:58:35Z)
lists §7.5 as still open alongside §7.2–7.4.

## Why it can't be worked around

The owner's implementation plan (2026-05-18) says provider keys get
handed to *"NemoClaw's provider-registration command"* on the gateway,
after which "the sandboxed OpenClaw process never receives the raw
key; the gateway's L7 proxy substitutes it at egress."

Executing that requires knowing:

1. The upstream NemoClaw CLI verb for provider registration
   (name, argv shape, idempotency semantics, secret-input mechanism —
   argv / stdin / env / file).
2. Whether registration is per-sandbox or gateway-wide.
3. What happens on `nemoclaw destroy <sandbox>` — does the
   registration survive, and if so, is that a leak?
4. Whether the gateway substitutes the key transparently for every
   provider `type` today (anthropic, openai, opencode, opencode-go,
   litellm, zai) or only a subset — the render layer today branches
   per-type and litellm additionally writes `apiKey` **inline** into
   `.openclaw/openclaw.json` (see `render.py:2211-2231`).

Current-main state, verified by survey:

- `src/clawrium/core/nemoclaw.py` — wrapper exposes
  `{onboard, start, stop, status, logs, destroy}`. No `gateway`
  namespace. No `register` verb.
- `src/clawrium/platform/registry/openclaw/manifest.yaml` —
  `runtime.nemoclaw.version: v0.0.94`, no gateway config block.
- Phase 1's doctor probe verified the upstream repo exists but did
  not enumerate the gateway API surface.

Fabricating the verb in `nemoclaw.py`, `render.py`, and
`configure.yaml` risks shipping a fictional integration surface that
does not match whatever upstream NemoClaw actually offers — this
would be caught in wolf-i UAT and require a full rework once the
real API is known.

## Non-regression scope reminder

Phase 4 must not regress hermes / zeroclaw provider handling — they
share `core/render.py`. Any real implementation of this phase MUST
gate the "delete provider env injection" change to the openclaw
render path only. This constraint is documented in the issue body's
"Critical non-regression" bullet.

## Recommended resolution path

1. Owner answers §7.5 on issue #11: either
   - (a) point to upstream NemoClaw's gateway registration docs / CLI
     verb (URL + verb name + argv shape), OR
   - (b) accept that customers with custom providers use NemoClaw's
     runtime CLI directly (retracts "CLI never exposed" guarantee for
     that narrow case), OR
   - (c) declare that Clawrium ships a thin blueprint after all,
     with a `providers:` section templated per-agent.
2. Re-spawn `/itx:execute 946 --pr-base=issue-945-delete-bare-openclaw`
   on this branch. This document is preserved as the historical
   record of the block.

## No commits / no PR

Per user directive (2026-07-25), this session halts without pushing
or opening a PR. The branch remains at
`df28079` (phase-3 tip); this document is the only artifact.
