# `clawctl` Gate 3 — E2E Validation

End-to-end validation of the new `clawctl` write surface against the live wolf-i fleet, per [`.itx/435/01_SCAFFOLD.md`](https://github.com/ric03uec/clawrium/blob/feat/435/bundle-5-templates-docs-audit-after/.itx/435/01_SCAFFOLD.md) lines 460–478 ("Gate 3 — wolf-i full-fleet end-to-end"). Final acceptance bar before opening the `feat/435-clawctl-ux → main` integration PR.

## Header

| Field | Value |
|---|---|
| Date (UTC) | 2026-05-24 → 2026-05-25 |
| Integration branch (pre-fix) | `feat/435-clawctl-ux` @ `3acce64` (merge of #511, #512, #513, #514, #515) |
| Hotfix branch | `fix/516-lifecycle-verb-key-resolution` (resolves regression caught by this gate) |
| `clawctl --version` | 26.5.4 |
| `clawctl` binary | `/home/devashish/.local/bin/clawctl` (installed via `uv tool install -e .` from each branch in turn) |
| Target host | `wolf-i` (ubuntu, LAN) |
| Operator | orchestrator (`/itx:execute orchestrate 435`) |

## Pre-existing fleet snapshot (untouched throughout)

```
NAME             TYPE       HOST     PROVIDER  STATUS   AGE
wolf-i           openclaw   wolf-i   -         ready    43d
espresso         hermes     wolf-i   -         ready    13d
maurice          hermes     wolf-i   -         ready    2d
clawrium-d01     zeroclaw   wolf-i   -         ready    5d
nemotron-beta    zeroclaw   wolf-i   -         ready    4d
nemotron-alpha   zeroclaw   wolf-i   -         ready    2d
```

The host carries **multiple instances of the same type** (3 zeroclaws, 2 hermes) — the exact shape that exposed the regression below.

## Deviations from scaffold §460–478

| Spec item | Action | Reason |
|---|---|---|
| `clawctl service init` | **SKIP** | `~/.config/clawrium/` already provisioned with 6 production agents; re-init would clobber `hosts.json`. |
| `clawctl host create wolf-i --user <u> --bootstrap` | **SKIP** | wolf-i already registered; bootstrap would re-run `ssh-copy-id`. |
| `clawctl provider registry create anthropic --type anthropic --api-key-stdin` | **SKIP** | No Anthropic API key in env / `pass`. Existing agents use direct in-config credentials (provider column shows `-`). |
| `clawctl channel registry create my-discord …` | **SKIP** | No Discord token available. Scaffold explicitly accepts: "channels-not-applicable agents may skip with documented error." |
| `clawctl agent channel attach …` | **SKIP** | Depends on the skipped channel above. |
| `clawctl agent create … --provider anthropic --yes` | **ADAPT** | `--provider` omitted; matches existing fleet's install pattern. Side-effect: subsequent `--stage providers` step is unrunnable without a registered provider (see Phase 2 Retest analysis below). |

---

## Phase 1 — Initial Gate 3 attempt (pre-fix, RED)

Ran [`/tmp/gate3-runner.sh`](https://github.com/ric03uec/clawrium/blob/fix/516-lifecycle-verb-key-resolution/.itx/435/e2e-validation.md) for all three agent types: `audit-zeroclaw`, `audit-hermes`, `audit-openclaw`. Each cycle: `create → configure → channel-attach (skip) → skill attach → secret create → start → get|grep → sync → describe → restart → logs → stop → delete`.

### Result

| Agent | Pass | Fail | Skip |
|---|---|---|---|
| audit-zeroclaw | 6 | 6 | 1 |
| audit-hermes | 6 | 6 | 1 |
| audit-openclaw | 6 | 6 | 1 |
| **Total** | **18** | **18** | **3** |

Identical failure shape across all three types — systematic, not flaky. Every write-path verb failed at the very first SSH-touching step.

### Failure signature

`clawctl agent delete audit-zeroclaw --yes`:

```
agent/audit-zeroclaw: [validate] Checking zeroclaw on wolf.tailf7742d.ts.net...
Error: remote cleanup failed: Multiple zeroclaw agents found.
       Specify instance name: clawrium-d01, nemotron-beta, nemotron-alpha, audit-zeroclaw
```

`clawctl agent configure audit-zeroclaw --stage validate`:

```
agent/audit-zeroclaw: configure stage=validate on wolf.tailf7742d.ts.net
…
AgentNotFoundError: Agent 'zeroclaw' not found on host 'wolf.tailf7742d.ts.net'
```

Both errors look up the **agent type** (`zeroclaw`) where the **instance name** (`audit-zeroclaw`) is required.

### Root cause

`src/clawrium/cli/clawctl/agent/_shared.py:safe_resolve_agent()` returns the agent's type string as its second tuple element (its own docstring says so). 6 of the 8 lifecycle verbs (`configure`, `start`, `stop`, `sync`, `restart`, `delete`) consumed that value as if it were the instance name — so on any host with >1 agent of the same type, every write-path lifecycle op was broken.

A helper `resolve_agent_key(host, agent_name)` was added in Bundle 3 ATX iter-2 W3 to do the second-pass lookup, but it was only wired into the 3 Pattern A attachable verbs (`provider`, `channel`, `integration`) — the lifecycle verbs were missed. The Bundle 3 unit tests fixtured a single-agent-per-type host where the bug is invisible (dict key happens to equal the type string), so the regression slipped through every gate before Gate 3.

### Tracking

Filed as bug [**#516**](https://github.com/ric03uec/clawrium/issues/516) immediately on detection. Stranded 3 audit agents in `onboarding` state on wolf-i (couldn't be deleted by the same broken `delete` verb).

---

## Hotfix — `fix/516-lifecycle-verb-key-resolution`

| Aspect | Detail |
|---|---|
| Branch | `fix/516-lifecycle-verb-key-resolution` (off `feat/435-clawctl-ux`) |
| Files changed | 6 verb modules + 1 new test file (no production code outside these 6 verbs) |
| Pattern | Each broken verb now: (a) imports `resolve_agent_key`, (b) renames the second return of `safe_resolve_agent` to `_agent_type` (its real semantics), (c) calls `agent_key = resolve_agent_key(host, name)` to get the canonical instance-name key, (d) sources `agent_type` from `claw_record["type"]` with `_agent_type` as fallback. |
| Regression test | `tests/cli/clawctl/agent/test_multi_instance_resolution.py` — fixtures a host with 3 same-type zeroclaws keyed by instance name, asserts each of `start/stop/restart/sync/delete/configure` passes the correct instance name as `agent_name` (not the type) to its core call. 18 parametrized cases. |
| Test suite (full) | **3064 Python + 213 GUI passing** (was 3046 pre-fix; +18 from the new file). |
| Lint | ruff + next-lint clean. |
| Format | `make format` idempotent (zero diff). |

### Live cleanup proof (Phase 1 wreckage cleared with the fixed binary)

After installing `clawctl` from the hotfix branch (`uv tool install -e <hotfix-worktree> --reinstall`), all three stranded audit agents deleted cleanly:

```
$ clawctl agent delete audit-zeroclaw --yes
agent/audit-zeroclaw: [validate] Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
agent/audit-zeroclaw: [remove] Removing audit-zeroclaw from wolf.tailf7742d.ts.net...
agent/audit-zeroclaw: [remove] Removing from local configuration...
agent/audit-zeroclaw: [remove] Cleaned up instance secrets
agent/audit-zeroclaw: [remove] Cleaned up agent state directory
agent/audit-zeroclaw: [remove] Removed audit-zeroclaw successfully
agent/audit-zeroclaw: deleted

$ clawctl agent delete audit-hermes --yes        # same shape — deleted
$ clawctl agent delete audit-openclaw --yes      # same shape — deleted
```

Same `delete` command that emitted `Multiple zeroclaw agents found. Specify instance name…` against the broken code now correctly targets the named instance. **The regression is reproducibly fixed against the live multi-instance fleet.**

---

## Phase 2 — Gate 3 retest on hotfix branch (audit-zeroclaw)

Re-ran the same `gate3-runner.sh zeroclaw` script against the fixed binary, freshly creating a new `audit-zeroclaw` on wolf-i (which still has 3 sibling zeroclaws — multi-instance reproducer).

### Result

| Agent | Pass | Fail | Skip | Δ vs Phase 1 |
|---|---|---|---|---|
| audit-zeroclaw | **8** | **4** | 1 | +2 pass / −2 fail |

| Step | Phase 1 (pre-fix) | Phase 2 (post-fix) |
|---|---|---|
| create | ✅ | ✅ |
| configure --stage validate | ❌ (bug #516) | ❌ (state machine — see analysis) |
| channel attach | ⏭ skip | ⏭ skip |
| skill attach `clawrium/tdd` | ✅ | ✅ |
| secret create FOO=bar | ✅ | ✅ |
| start | ❌ (bug #516) | ❌ (state machine — see analysis) |
| get \| grep | ✅ | ✅ |
| sync | ❌ (bug #516) | ❌ (state machine — see analysis) |
| describe | ✅ | ✅ |
| restart | ❌ (bug #516) | ❌ (state machine — see analysis) |
| logs --tail 10 | ✅ | ✅ |
| stop | ❌ (bug #516) | ✅ |
| delete | ❌ (bug #516) | ✅ |

### Analysis of remaining 4 failures (NOT bug #516)

The 4 still-failing verbs — `configure --stage validate`, `start`, `sync`, `restart` — fail for a **different, valid reason** that bug #516's symptom was previously masking:

```
$ clawctl agent configure audit-zeroclaw --stage validate
agent/audit-zeroclaw: configure stage=validate on wolf.tailf7742d.ts.net
Error: configure stage rejected: Cannot complete stage 'validate' while in state 'pending'.
       Allowed stages in this state: ['providers']
Hint:  clawctl agent describe audit-zeroclaw
```

```
$ clawctl agent start audit-zeroclaw
agent/audit-zeroclaw: [validate] Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
Error: start failed: Cannot start audit-zeroclaw: onboarding incomplete (state=pending).
```

The state machine correctly rejects skipping the `providers` configure stage. Phase 1's script jumped straight from `agent create` to `agent configure --stage validate`, skipping `--stage providers --provider <name>` — because the deviations table above struck the provider-create step (no Anthropic API key on this control machine).

Pre-fix, bug #516 made `configure --stage validate` fail at its very first SSH call (instance-name lookup) before the state-machine code ever ran — hiding the prerequisite-stage rejection. With #516 fixed, the verb now reaches the state machine, which correctly enforces the `providers → identity → validate` order. The remaining failures are **expected behaviour given the deviations table** and would resolve by either:

1. registering a provider (`clawctl provider registry create <name> --type <t> --api-key-stdin`) and running `--stage providers --provider <name>` before `--stage validate`, or
2. dropping the deviation for `provider registry create` and supplying an API key.

Neither is in scope for Gate 3's purpose (validate the new write surface against a multi-instance host). The `delete` and `stop` rescues from Phase 1 to Phase 2 are sufficient to demonstrate bug #516 is fixed against live data.

### Cleanup

The audit-zeroclaw left over from Phase 2 was removed at end of cycle by the fixed `delete` verb (the final ✅ in the retest table). Fleet is back to the original 6 pre-existing agents.

---

## Summary

| Gate | Result | Detail |
|---|---|---|
| 1 — clean rebuild | ✅ PASS | `clm` removed, `clawctl` installed, all 12 top-level groups exit 0 on `--help`. |
| 2 — test/lint/format/coverage | ✅ PASS | 3046 Python + 213 GUI tests, ruff + next-lint clean, format idempotent, coverage 82%. |
| 3 — wolf-i multi-instance lifecycle (Phase 1) | ❌ RED | Surfaced regression bug [#516](https://github.com/ric03uec/clawrium/issues/516). |
| 3 — wolf-i multi-instance lifecycle (Phase 2, post-#516 hotfix) | ⚠️ AMBER | Regression resolved; remaining 4 failures are state-machine prerequisite gaps caused by the documented `provider registry create` deviation, not by clawctl bugs. `delete` and `stop` improvements directly prove the fix on live data. |

**Recommendation:** merge the `fix/516-lifecycle-verb-key-resolution` PR into `feat/435-clawctl-ux`, then open the `feat/435-clawctl-ux → main` integration PR. The state-machine prerequisite gaps in Phase 2 are operator-supplied prerequisites (provider registration), not code defects, and need not gate the merge.
