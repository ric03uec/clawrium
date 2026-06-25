# Issue #770 — Execution

Phase 4 of parent #760: openclaw workspace overlay end-to-end on macOS.
Source scaffold: [`.itx/760/01_EXECUTION.md`](../760/01_EXECUTION.md#phase-4--openclaw-end-to-end-on-macos-deferred).
E2E run log: [`05_E2E_openclaw_esper-macmini.md`](../760/05_E2E_openclaw_esper-macmini.md).

## What shipped

- `src/clawrium/platform/registry/openclaw/playbooks/workspace_macos.yaml`
  replaces the Phase-1 `ansible.builtin.fail: deferred` stub with a
  real copy pipeline. Same task structure as the Linux variant with
  two OS-specific deltas: `/Users/<agent_name>/` prefix (vs `/home/`)
  and hardcoded `group: staff` (vs `group: "{{ agent_name }}"`).
- `src/clawrium/core/playbook_resolver.py` gains `home_root_for(os_family)`
  — the single OS seam for the home-dir root mapping. Keeps
  `workspace_sync.py` free of OS literals per the existing
  `test_workspace_sync_module_has_no_os_family_literals` invariant.
- `src/clawrium/core/workspace_sync.py:_expand_destination_root` accepts
  `os_family` and routes through `home_root_for`. Call site at
  `push_workspace_phase` now threads `host['os_family']`.
- Unit + integration tests: parametrized table for
  `_expand_destination_root` (3 input shapes × 2 OS families + the
  default-arg backward-compat case); new
  `test_push_workspace_phase_threads_os_family_to_{darwin,linux}`
  integration tests stub `ansible_runner` and assert dispatcher
  routing + every extravar the playbook consumes.
- `AGENTS.md` "Workspace Overlay" section updated to document per-OS
  playbook split, the `home_root_for` seam, and `group: staff` macOS
  convention.
- `CHANGELOG.md` `[Unreleased] ### Added` entry for the macOS GA.
- `.itx/760/01_EXECUTION.md` updated `mac-test` → `esper-macmini` for
  consistency.

## ATX review (CLI, per operator directive)

| Iter | Rating | Blockers | Warnings | Cost | Time |
|---|---|---|---|---|---|
| 1 | 3/5 | None | 6 (W1–W6) + 6 suggestions | $3.19 | ~11m |
| 2 | 4/5 | None | 6 (all pre-existing patterns or follow-ups) | n/a | ~14m |

**Iter-1 → iter-2 fixes**: W1 `..` segment rejection in playbook
assert · W2 `follow: no` on both `file: state: directory` tasks · W4
absolute-path passthrough parametrized · W5 integration tests for
dispatcher + extravars · W6 `pytest.raises(match=...)` on
`home_root_for` · W7 (S6) `^0[0-7]{3,4}$` regex on `item.mode` ·
S1 top-level import of `home_root_for` · S3 header comment enumerates
both macOS deltas · S4 tests collapsed into `@pytest.mark.parametrize`.

**Iter-2 small fixes before PR**: W4 extravars pinning expanded to
include `agent_name`, `agent_type`, excludes, `staging_dir`; W6
comment-stripping helper applied uniformly across positive + negative
playbook text scans.

**Deferred to follow-up** (documented as Callouts in the PR body):
iter-2 W1 (uncaught `ValueError` from `home_root_for` — pre-existing
surface), iter-2 W2 (intermediate parent symlinks still traversed —
comment-only clarification), iter-2 W3 (`agent_name='root'` allowed
by slug regex — cross-OS issue), iter-2 W5 (capital-D `'Darwin'`
contract test), S5 (mirror W1 `..` check into Linux playbook next
time it's touched), S6 (replace `staging_dir` substring check with
extravar-driven startswith).

## Test results

- `uv run pytest`: 3925 passed, 8 skipped (up from 3913 on main).
- `uv run ruff check src tests`: clean.

## E2E

- Real host: `esper-macmini` (espers-mac-mini.tailf7742d.ts.net,
  darwin/arm64).
- Agent: `esper-mac-oc` (existing healthy openclaw agent reused
  instead of provisioning a fresh `ws-openclaw-mac` — see E2E log for
  reasoning).
- Marker landed at `/Users/esper-mac-oc/.openclaw/workspace/MARKER.md`,
  owner `esper-mac-oc:staff`, mode `0664`. `agent doctor` healthy
  after sync.

## Prompt Log

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-06-23T20:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 770

Operator directives (orchestrate parent #760):
- Use ATX via CLI only (`atx review --format json ...`). Do NOT use the MCP path.
- Real-host E2E target is `esper-macmini` (espers-mac-mini.tailf7742d.ts.net, darwin/arm64). The issue body already reflects this swap.
- This is the first phase in a stacked-PR chain. Open PR against `main`.
- Also update `.itx/760/01_EXECUTION.md` in your PR to replace `mac-test` with `esper-macmini` for consistency.
```

**Output**: Phase-1 macOS stub replaced with real copy pipeline;
`home_root_for` added to playbook_resolver as the OS seam;
`workspace_sync` threads `os_family` end-to-end; 12 new unit /
integration tests cover the darwin path; AGENTS.md + CHANGELOG +
parent scaffold updated; E2E green on `esper-macmini`; ATX iter-2
rating 4/5 with no blockers. PR opened against `main` as the first
phase of the stacked-PR chain.
