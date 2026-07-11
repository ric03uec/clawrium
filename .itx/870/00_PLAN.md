# Issue #870 — Stable Agent Action Bar

## Goal

Stabilize the agent action bar so lifecycle buttons (`Start`, `Restart`,
`Stop`) never appear/disappear based on `liveStatus`. Buttons that are
invalid for the current state render disabled instead of unmounting, so
`Restart` never shifts into where the cursor is headed.

## Scope

**In scope** — the three lifecycle buttons in
`gui/src/components/agent-detail/agent-header.tsx`:

- `Start` (previously gated by `isStopped`)
- `Restart` + `Stop` (previously gated by `isRunning`)

**Out of scope** — buttons gated by *agent-type identity* rather than
state (they don't shift within a given agent's page):

- `Open Agent UI` (agent-type feature)
- `Get Pairing Code` (zeroclaw only)
- `Show Connection Token` (openclaw only)

## Design decisions

1. **Always render Start, Restart, Stop**, in fixed
   `[Start, Restart, Stop]` order.
2. **Use `aria-disabled` + guarded `onClick`**, not native `disabled`
   — native `disabled` drops focus and native `title` is not reliably
   exposed to AT or on touch devices (ATX iter-1 B1).
3. **Reason wired via `aria-describedby`** pointing to per-instance
   `sr-only` spans, ids derived from `useId()` so multiple headers
   can co-render on a fleet/list view without id collisions
   (ATX iter-2 W1).
4. **Move `install_missing` hint out of the action-bar row** into its
   own alert below, so the button row width stays stable.
5. **Extract `lifecycleDisabledReason(status, action)` to module scope**
   as a pure function — unit-testable without React, and a future
   status literal only needs a single edit.

## Files changed

| File | Change |
|---|---|
| `gui/src/components/agent-detail/agent-header.tsx` | Unconditional lifecycle button render; `aria-disabled` + `useId()`-scoped `aria-describedby`; extract `lifecycleDisabledReason` helper; move install_missing alert below action row |
| `gui/src/components/agent-detail/agent-header.test.tsx` | Add 28 tests: pure-helper table, always-rendered invariant across 5 states, stable DOM order, aria-disabled correctness, title + describedby wiring, click-guard, two-instance uniqueness |
| `CHANGELOG.md` | Entry under `[Unreleased] > ### Fixed` referencing `#870` |

## Test plan

- Unit tests via `vitest run` — 28 passing for `agent-header.test.tsx`,
  328 total across gui suite.
- Lint via `next lint` — clean.
- Root `make lint` fails on a pre-existing missing
  `src/clawrium/gui/frontend` include (unrelated to this frontend-only
  change).

## ATX Review Summary

Final Review: **Rating 4/5 · Iter-3**
Total Cost: **$4.02** · Total Time: **~6m 52s**

| Review | Rating | Blocking Issues | Status | Cost | Time |
|---|---|---|---|---|---|
| 1 | 3.5/5 | B1 (native disabled + title inaccessible) | Fixed | $1.49 | 2m 44s |
| 2 | 4/5 | None | W1 (hardcoded ids) fixed | $1.48 | 2m 24s |
| 3 | 4/5 | None | Ship it | $1.05 | 1m 44s |

**Note**: ATX does not expose model information per agent.

<details>
<summary>Review 1 Details (Rating 3.5/5)</summary>

**Blocking Issues:**

| # | File | Issue | Resolution |
|---|---|---|---|
| B1 | `agent-header.tsx:186-236` | Native `disabled` + `title` — Firefox suppresses hover, touch shows nothing, screen readers inconsistent, disabled elements drop out of tab order | Fixed — switched to `aria-disabled` + guarded `onClick` + `aria-describedby` → sr-only reason span |

**Warnings:**

| # | File | Warning | Action |
|---|---|---|---|
| W1 | `agent-header.tsx:33-51` | Reason mapping only handles fixed status literals; transitional states could fall through | Fixed — extracted `lifecycleDisabledReason()` at module scope; covered by table-driven tests |
| W2 | `agent-header.tsx:190,199,208,214,224,233` | `aria-label="Start agent"` overrides visible text and drops pending state ("Starting…") from accessible name | Fixed — dropped `aria-label` overrides; visible text is now the accessible name |
</details>

<details>
<summary>Review 2 Details (Rating 4/5)</summary>

**Warnings:**

| # | File | Warning | Action |
|---|---|---|---|
| W1 | `agent-header.tsx:230-244` | Hard-coded module-scope ids (`action-start-reason` etc.) collide if AgentHeader renders twice on a page | Fixed — replaced with `useId()`-scoped ids; added two-instance uniqueness test |
| W2 | `agent-header.tsx:210-228` | `aria-describedby` not wired during pending state — asymmetric a11y UX | Acknowledged — pending state uses visible text ("Starting…") for accessible name; describedby-parity is polish, not a defect |

**Suggestions:**

| # | Suggestion | Action |
|---|---|---|
| S1 | Extract local `<LifecycleButton />` sub-component | Deferred — three near-identical blocks; extraction is polish |
| S2 | Return `string \| null` from `lifecycleDisabledReason` | Deferred — `""` empty-string sentinel is idiomatic and covered by tests |
| S3 | Add keyboard Enter click-guard test | Acknowledged — mouse `.click()` exercises the same handler; keyboard path uses the same guard |
</details>

<details>
<summary>Review 3 Details (Rating 4/5)</summary>

Verdict: **Ship it.** No blocking issues.

**Suggestions:**

| # | Suggestion | Action |
|---|---|---|
| S1 | `useId()` output contains `:`; normalize with `.replace(/:/g, '')` for querySelector safety | Deferred — tests use attribute-suffix `[id$='-restart-reason']` selectors, not `#id` queries; no impact |
| S2 | Extract `<LifecycleButton />` sub-component | Deferred — see iter-2 S1 |

**Coverage note:** `test-coverage` specialist failed with upstream model
404 across all three iterations. Manual coverage confirmed via 28
passing tests spanning: pure helper table, always-rendered invariant
across 5 states, stable DOM order, aria-disabled correctness, title +
describedby wiring, click-guard, two-instance id uniqueness.
</details>
