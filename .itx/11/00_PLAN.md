# Issue #11 — Implementation Plan

**Title**: PRD: Implement NemoClaw reference architecture across supported claws
**Labels**: enhancement, planning
**Base**: `origin/main` @ `fd9e72f`
**Scope**: expand the owner's implementation-plan comment (2026-05-18) into an execution plan against **current main**, correcting drift and adopting the owner's directive (2026-07-24) that **NemoClaw is a HARD dependency of openclaw — no bare-openclaw install path survives**.

---

## 0. Drift Audit vs Current Main

| Owner-plan claim | Current-main reality | Impact |
|---|---|---|
| Delete `nemoclaw` claw type (manifest, role, tests, registry entry) | No `src/clawrium/platform/registry/nemoclaw/` exists. Only `openclaw`, `zeroclaw`, `hermes`, `ethos`. | Cleanup scope: (a) `website/docs/reference/cli/registry.md:36` stale row; (b) `src/clawrium/core/lifecycle.py:136` `"nc": "nemoclaw"` alias; (c) `tests/**` fixtures; (d) `docs/agent-support/hermes.md:170` + website mirror name-drop; (e) `docs/releases/26.7.0/CHANGELOG.md:549` (historical — leave). `nc` alias removal → `### BREAKING`. |
| All examples use `clm agent install …` | CLI is `clawctl`; `clm` purged in `2a93d21` (2026-07). Verbs: `clawctl agent {create,configure,sync,start,stop,logs,status,remove}`. There is no `clawctl host validate` or `clawctl ps` today. | Owner-plan strings translate to `clawctl`. `host validate` is a new verb; fleet-status extends `clawctl agent get`. |
| "NemoClaw is a hard dependency. No bare-OpenClaw install path remains." | Bare openclaw ships today (`openclaw/playbooks/install.yaml`, `install_macos.yaml`, brave plugin + slack MCP integrations). | **Confirmed by owner 2026-07-24.** Every existing openclaw fleet must reinstall. No opt-in / `--runtime` flag. Large-blast `### BREAKING`. |
| Sync-time install of NemoClaw via `curl \| bash` | AGENTS.md ~L302-360 "Integration Binary Install" pattern mandates one runbook per binary, checksum-pinned `get_url`, task-0 OS dispatcher guard, fail-fast on unsupported arch. `curl \| bash` violates rules 3 and 5. | Install runbook MUST use `get_url` with `sha256:` against pinned upstream tarballs. If NVIDIA does not publish per-arch tarballs with SHAs, approach is blocked. |
| NVIDIA NemoClaw at `docs.nvidia.com/nemoclaw` + `github.com/NVIDIA/NemoClaw`, tag `v0.0.44` | **Not independently verified.** Only referenced in the owner's plan comment. `v0.0.44` is unusually low for a security-critical runtime. NVIDIA is publicly known for NeMo (LLM framework) and NeMo Guardrails, not a sandbox runtime by this name. | **Phase 1's validity gate MUST confirm this before any host-touching code lands.** If it doesn't exist, the issue is unexecutable as scoped. |

---

## 1. Overview

Every openclaw installation Clawrium ever produces from here on runs inside a NemoClaw sandbox. Bare openclaw is deleted. `clawctl` remains the only operator surface — NemoClaw is invisible in default output. Zeroclaw, hermes, ethos are untouched throughout this issue.

The 4 phases delay the breaking cut-over as long as possible: phases 1–2 land NemoClaw on hosts and prove sandboxed openclaw works side-by-side with the existing bare path before phase 3 deletes bare openclaw.

---

## 2. Customer-Outcome Phases (4)

Each phase's DoD is a single command with a specific, quotable result — not a code diff.

| # | Customer outcome | Operator-visible "done" | Breaking? |
|---|---|---|---|
| **1. Groundwork** | "I can see what NemoClaw is, prove it's real, and stop seeing stale nemoclaw noise in the fleet." | New `docs/agent-support/nemoclaw.md` + website mirror published. `clawctl doctor nemoclaw` fetches upstream release metadata and reports `reachable / correct-sha / arch-match` — no host changes. `clawctl agent registry get` no longer lists the phantom Ollama-era `nemoclaw`; `clawctl agent create --type nc …` returns "unknown alias" instead of silently mapping. | Small — `nc` alias removal only. `### BREAKING`, tiny blast radius. |
| **2. NemoClaw on hosts, sandboxed openclaw available** | "When I prep a host, NemoClaw is installed. When I create a new openclaw, it runs inside a NemoClaw sandbox. My existing bare openclaw still runs." | On wolf-i: `clawctl host prepare wolf-i` completes → SSH → `nemoclaw --version` returns the pin. `clawctl agent create --type openclaw --host wolf-i --name e2e-openclaw-nemo` succeeds; `clawctl agent get` shows `runtime: nemoclaw@<version>` on that row. Old bare `e2e-openclaw` unchanged (proof of non-regression). | No — additive. Bare + sandboxed openclaw run side-by-side on wolf-i. |
| **3. Bare openclaw deleted, full lifecycle + fleet visibility** | "Bare openclaw is gone. Every openclaw runs inside NemoClaw. I can start/stop/sync/upgrade/remove them, and see runtime + sandbox health in one command." | On wolf-i: `clawctl agent remove e2e-openclaw` → re-create → sandboxed. Repo grep for bare install path returns nothing. Full `clawctl agent {start,stop,status,logs,sync,remove}` round-trip works on sandboxed openclaw. `clawctl agent get` shows `runtime: nemoclaw@<version>` on every openclaw row. `clawctl host validate wolf-i` aggregates `nemoclaw <sandbox> status` and exits non-zero on any unhealthy sandbox. | **YES — the breaking moment.** Every existing openclaw fleet must remove + re-create. `### BREAKING` with explicit manual steps in `docs/releases/<version>/`. |
| **4. Provider keys leave the openclaw process** | "I configure a provider on openclaw, and my API key never lives inside the openclaw process." | `clawctl agent configure e2e-openclaw` with a provider key → `clawctl agent exec e2e-openclaw -- env` inside the sandbox shows no `*_API_KEY`; provider call from openclaw still succeeds via the NemoClaw gateway proxy. All integration-carrying hermes / zeroclaw agents still work (shared `core/render.py`). | Yes for scripts reading keys from openclaw's process env (not a supported interface). `### BREAKING`, small blast radius. |

### Serialization

Strictly 1 → 2 → 3 → 4.

### Non-breaking guarantee (phases 1–2)

Every existing agent on wolf-i — `espresso`, `clawrium-triage`, `clawrium-gtm`, `clawrium-exec`, `clawrium-maurice` (hermes with `clawrium-github`), `clawrium-d01` (zeroclaw with `clawrium-d01-github`), `e2e-openclaw` (bare openclaw), `e2e-hermes`, `e2e-zeroclaw`, `ep6-hermes` — runs identically through phases 1–2. Bare `e2e-openclaw` is only removed in phase 3 and immediately re-created sandboxed.

---

## 3. Technical Realization (per phase)

Any host-side binary install MUST follow the "Integration Binary Install" pattern (AGENTS.md ~L302-360), even though NemoClaw is a runtime substrate rather than an integration.

### Phase 1 — Groundwork
- **Validity gate**: fetch and verify `docs.nvidia.com/nemoclaw`, `github.com/NVIDIA/NemoClaw`, tag `v0.0.44`, per-arch tarballs, published SHA256s. If missing, **STOP and re-triage the issue.**
- Author `docs/agent-support/nemoclaw.md` + website mirror.
- New: `src/clawrium/cli/clawctl/doctor/nemoclaw.py` — read-only probe. Fetches upstream release metadata (no download, no execution).
- New: `src/clawrium/core/nemoclaw.py` — skeleton holding the version constant and upstream URL/SHA table. Behavior added in phases 2 and 3.
- Delete `"nc": "nemoclaw"` alias in `core/lifecycle.py:136`.
- Drop `nemoclaw` row from `website/docs/reference/cli/registry.md:36`.
- Remove `nemoclaw` from `docs/agent-support/hermes.md:170` + website mirror.
- Scrub `nemoclaw` from test fixtures.

### Phase 2 — NemoClaw on hosts + sandboxed openclaw path available
- New Ansible runbook `openclaw/playbooks/install_nemoclaw.yaml` (+ `_macos` sibling per §7.2). Integration-binary contract: task-0 OS dispatcher guard, arch guard, `get_url` with `sha256:` against pinned tarball, extract to `/usr/local/lib/nemoclaw/<version>/`, idempotent by version-dir + checksum.
- New `openclaw/playbooks/install_prereqs.yaml`: Ubuntu ≥ 24.04 / ≥ 8 GB RAM / ≥ 20 GB disk asserts; `apt-get install git zstd`; Docker Engine via Docker's Ubuntu apt repo; NVM + Node 22.16; SSH user in `docker` group.
- Wire both into `openclaw/playbooks/install.yaml`'s host-prep phase.
- 3-way version-pin lockstep test (constant in `core/nemoclaw.py` ↔ `manifest.yaml`'s `runtime.nemoclaw.version` ↔ `install_nemoclaw.yaml`'s `nemoclaw_version` var).
- `core/nemoclaw.py` grows a thin CLI wrapper (onboard / start / stop / status / logs / destroy).
- New `_openclaw_nemoclaw_onboard` helper in `core/lifecycle_canonical.py`, invoked by `sync_agent_canonical` before the file-write loop (mirrors `_openclaw_install_plugins` / `_openclaw_install_slack_mcp` shape).
- New openclaw creates run through NemoClaw; `hosts.json.agents.<name>.config` gets `{runtime: "nemoclaw", sandbox_name, nemoclaw_version}`.
- Legacy bare `e2e-openclaw` on wolf-i is NOT migrated in this phase — that's phase 3.

### Phase 3 — Delete bare openclaw + full lifecycle + fleet visibility (BREAKING)
- Delete every code branch keyed on "no runtime" / bare openclaw. Every openclaw create goes through NemoClaw. No `--runtime bare` flag.
- `clawctl agent {start,stop,status,logs,sync,remove}` fully delegate to NemoClaw. `sync` re-onboards on pin changes and short-circuits before restart on failure. `remove` destroys the sandbox before uninstalling openclaw bits.
- Extend `clawctl agent get` row: `runtime: nemoclaw@<version>` on every openclaw row.
- New `src/clawrium/cli/clawctl/host/validate.py` — aggregates `nemoclaw <sandbox> status` for every openclaw on the host.
- On wolf-i: `clawctl agent remove e2e-openclaw`, then `clawctl agent create --type openclaw --host wolf-i --name e2e-openclaw` → sandboxed.
- `### BREAKING` in `CHANGELOG.md` with explicit "remove + re-create" instructions; migration note in `docs/releases/<next-version>/`.

### Phase 4 — Provider credential handoff to the NemoClaw gateway
- Delete provider env injection from openclaw's render path in `src/clawrium/core/render.py`.
- Route provider `api_key` / `base_url` to a NemoClaw gateway-registration payload on `clawctl agent configure`.
- Test: no `*_API_KEY` visible from inside the sandbox; egress calls still succeed via the gateway proxy.
- Non-regression: `render.py` is shared — hermes / zeroclaw agents with `clawrium-github` and `clawrium-d01-github` must still work.

---

## 4. Files to Modify / Create

### Modify
- `src/clawrium/platform/registry/openclaw/manifest.yaml` — `runtime.nemoclaw.version` pin (phase 1 stub, phase 2 wired); Ubuntu ≥ 24.04 requirement.
- `src/clawrium/platform/registry/openclaw/playbooks/install.yaml` — insert host-prep + NemoClaw install hooks (phase 2); delete bare branch (phase 3).
- `src/clawrium/platform/registry/openclaw/playbooks/install_macos.yaml` — harden per §7.2 outcome (phase 3).
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml` — swap env injection for gateway registration (phase 4).
- `src/clawrium/platform/registry/openclaw/playbooks/remove.yaml` — destroy sandbox first (phase 3).
- `src/clawrium/core/render.py` — route provider keys to gateway payload (phase 4).
- `src/clawrium/core/lifecycle_canonical.py` — `_openclaw_nemoclaw_onboard` (phase 2); teardown mirror (phase 3).
- `src/clawrium/core/lifecycle.py:136` — delete `"nc": "nemoclaw"` alias (phase 1).
- `website/docs/reference/cli/registry.md:36` — drop stale row (phase 1).
- `docs/agent-support/hermes.md:170` + website mirror — drop `nemoclaw` mention (phase 1).
- `docs/agent-support/openclaw.md` + website mirror — document NemoClaw substrate, Ubuntu 24.04+ floor, upgrade, rollback (phase 3).
- `CHANGELOG.md` — `### BREAKING` entries for phases 1, 3, 4.
- Tests per §5.

### Create
- `docs/agent-support/nemoclaw.md` + website mirror (phase 1).
- `src/clawrium/core/nemoclaw.py` (phase 1 skeleton, phase 2 CLI wrapper).
- `src/clawrium/cli/clawctl/doctor/nemoclaw.py` (phase 1).
- `src/clawrium/platform/registry/openclaw/playbooks/install_nemoclaw.yaml` (+ `_macos` sibling per §7.2) (phase 2).
- `src/clawrium/platform/registry/openclaw/playbooks/install_prereqs.yaml` (phase 2).
- `src/clawrium/cli/clawctl/host/validate.py` (phase 3).

---

## 5. Test Strategy

- **Renderer**: `tests/core/test_render_openclaw*.py` — provider `api_key` no longer in openclaw config (phase 4); new sibling asserts gateway-registration payload contains it.
- **Playbook lint**: `tests/platform/` — (a) 3-way NemoClaw version lockstep; (b) task-0 dispatcher-guard invariant for the new runbook.
- **Lifecycle**: `tests/test_lifecycle.py` + `tests/cli/clawctl/agent/` — `_openclaw_nemoclaw_onboard` runs before file-write loop and before `_restart_unit`; onboard/destroy round-trip.
- **CLI**: `tests/cli/clawctl/doctor/test_nemoclaw.py` (phase 1); `tests/cli/clawctl/host/test_validate.py` (phase 3).
- **Real-host UAT**: per §6.
- **CI floor**: `make lint && make test` before every push (per memory `run make lint before push`).

---

## 6. Real-host UAT (MANDATORY before every PR)

Per AGENTS.md memory `no PR without real-host UAT`: no PR may open until the changed code path is exercised end-to-end on **wolf-i** and non-regression is confirmed against every already-attached integration on that host.

### Fixed target host
- `wolf-i` (`wolf.tailf7742d.ts.net`, Ubuntu 24.04, x86_64, 15.5 GB RAM). Only host for this issue's UAT. macOS UAT only if §7.2 keeps openclaw on macOS (mac-test mirror pass).

### Agents on wolf-i (source: `~/.config/clawrium/hosts.json`, verified 2026-07-24)

| Agent | Type | Integrations | UAT role |
|---|---|---|---|
| `e2e-openclaw` | openclaw | *(none)* | Bare openclaw. Non-regression through phase 2; **remove + re-create as sandboxed in phase 3**. |
| `espresso` | hermes | *(none)* | Non-regression: hermes plain lifecycle. |
| `clawrium-triage` | hermes | `clawrium-github` | **Non-regression: integration must survive phase 1 (lifecycle.py) and phase 4 (render.py) changes.** |
| `clawrium-gtm` | hermes | `clawrium-github` | Same. |
| `clawrium-exec` | hermes | `clawrium-github` | Same. |
| `clawrium-maurice` | hermes | `clawrium-github` | Same. |
| `clawrium-d01` | zeroclaw | `clawrium-d01-github` | Non-regression: zeroclaw + integration survive phase 1 / phase 4. |
| `e2e-hermes` | hermes | *(none)* | Non-regression: hermes plain lifecycle. |
| `e2e-zeroclaw` | zeroclaw | *(none)* | Non-regression: zeroclaw plain lifecycle. |
| `ep6-hermes` | hermes | *(none)* | Optional smoke. |

Re-run discovery at the start of every phase:
```bash
jq '.[] | select(.key_id == "wolf-i") | .agents | to_entries |
    map({name: .key, type: .value.type,
         integrations: (.value.integrations // [])})' \
   ~/.config/clawrium/hosts.json
```

### PR-body UAT template (required)

```
## Real-host UAT

**Host**: wolf-i (wolf.tailf7742d.ts.net, Ubuntu 24.04, x86_64)
**Date**: <ISO-8601>
**Clawrium version**: <output of `clawctl --version`>

### Primary happy path
- Command(s) run: <exact clawctl invocations>
- Observed behavior: <what actually happened, terminal excerpts>
- Persisted state check: <relevant hosts.json keys before → after>

### Non-regression: attached integrations
| Agent | Type | Integration(s) | Verified how | Result |
|---|---|---|---|---|
| clawrium-triage | hermes | clawrium-github | <cmd> | PASS/FAIL |
| clawrium-gtm | hermes | clawrium-github | <cmd> | PASS/FAIL |
| clawrium-exec | hermes | clawrium-github | <cmd> | PASS/FAIL |
| clawrium-maurice | hermes | clawrium-github | <cmd> | PASS/FAIL |
| clawrium-d01 | zeroclaw | clawrium-d01-github | <cmd> | PASS/FAIL |

### Non-regression: plain-lifecycle agents
| Agent | Type | Verified how | Result |
|---|---|---|---|
| espresso | hermes | `clawctl agent sync espresso` | PASS/FAIL |
| e2e-hermes | hermes | `clawctl agent sync e2e-hermes` | PASS/FAIL |
| e2e-zeroclaw | zeroclaw | `clawctl agent sync e2e-zeroclaw` | PASS/FAIL |
| e2e-openclaw | openclaw | `clawctl agent sync e2e-openclaw` (phases 1–2) OR remove+re-create (phase 3+) | PASS/FAIL |
```

### Per-phase minimum happy path on wolf-i

| Phase | Primary happy path | Non-regression scope |
|---|---|---|
| 1 | `clawctl doctor nemoclaw` reports `reachable/correct-sha/arch-match`. `clawctl --help` shows no `nc` alias. `clawctl agent registry get` no `nemoclaw`. `clawctl agent sync` across all agents. | **all agents** (shared `lifecycle.py` touch). |
| 2 | `clawctl host prepare wolf-i` → SSH → `nemoclaw --version` returns pin. Re-run → idempotent. `clawctl agent create --type openclaw --host wolf-i --name e2e-openclaw-nemo` → sandboxed openclaw runs alongside bare `e2e-openclaw`. `clawctl agent get` shows both. | all agents (host-lifecycle + shared code). |
| 3 | `clawctl agent remove e2e-openclaw` → `clawctl agent create --type openclaw --host wolf-i --name e2e-openclaw` → sandboxed. `e2e-openclaw-nemo` from phase 2 removed as duplicate. Full `clawctl agent {start,stop,status,logs,sync,remove}` round-trip. `clawctl host validate wolf-i` exits 0. `clawctl agent get` shows `runtime: nemoclaw@<version>` on every openclaw row. | all agents; **explicit smoke on integration-carrying hermes to confirm no shared-code regression**. |
| 4 | `clawctl agent configure e2e-openclaw` with a provider key → `clawctl agent exec e2e-openclaw -- env` shows no `*_API_KEY`; provider call succeeds via gateway. | **critical**: re-configure every integration-carrying hermes / zeroclaw agent and confirm `clawrium-github` / `clawrium-d01-github` still functional. |

### Failure handling
Any FAIL blocks the PR. Fix in the same branch, re-run the FULL UAT (regressions cluster), update the section, then open.

---

## 7. Open Questions (block execution — resolve before phase 2)

1. **Does NVIDIA NemoClaw actually exist as described?** Phase 1's validity gate. If not, close or re-scope.
2. **macOS openclaw fate.** NemoClaw is Linux/Ubuntu-only per owner's plan, and phase 3 deletes the bare path. Options: (a) delete openclaw macOS support outright (BREAKING for mac-test operators; consistent with hard-dependency stance); (b) block openclaw macOS installs at preflight with a clear message pending future NemoClaw-on-mac; (c) NemoClaw ships a mac binary — resolves once phase 1 lands. Owner decision.
3. **Existing bare openclaw fleets: migration UX.** Hard stance is "remove + re-create." Confirm zero automated migration is acceptable and the phase 3 release note is the only guardrail. In-flight openclaw sessions are lost at cut-over.
4. **`clawctl host validate` and fleet-view shape.** Neither exists today. Confirm `clawctl agent get` row extension + new `host validate` verb is the right shape (vs. e.g. a `clawctl fleet status`).
5. **Blueprint override path.** Owner-plan says "no Clawrium-shipped blueprint, use upstream default" but also "NemoClaw CLI never exposed to end users." If a customer needs a custom provider added, they'd need direct NemoClaw CLI access — reconcile before phase 4.

---

## 8. Risks

- **Upstream doesn't exist** → whole issue unexecutable (phase 1 gate).
- **NVIDIA doesn't publish per-arch tarballs + SHAs** → forced to vendor or block (`curl | bash` forbidden by AGENTS.md).
- **Phase 3 blast radius** — every existing openclaw fleet needs manual reinstall. Requires very loud release note and probably a major version bump.
- **Docker group + Ansible session** — SSH user added to `docker` group in phase 2 may not be picked up by the same Ansible session; may need `reset_connection`.
- **macOS openclaw regression** if §7.2 picks option (a) — mac-test currently exercises openclaw macOS paths per multiple memories.
- **Version-pin drift** across constant / manifest / runbook — mitigated by lockstep test asserting direct equality against each side (not transitively).
- **Hermes/zeroclaw shared-code regression** in phases 1 and 4 — `core/lifecycle.py` and `core/render.py` are shared. UAT non-regression rows exist precisely for this.

---

## 9. Subtasks

Not created yet (per user instruction: planning only). Natural subtask breakdown once §7 resolves:

- `[Parent #11] Phase 1: Groundwork — validity gate, doctor probe, purge stale nemoclaw residue`
- `[Parent #11] Phase 2: NemoClaw on hosts + sandboxed openclaw available`
- `[Parent #11] Phase 3: Delete bare openclaw + full lifecycle + fleet visibility (BREAKING)`
- `[Parent #11] Phase 4: Provider credential handoff to NemoClaw gateway`

---

## Prompt Log

### Planning (v1)

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Planning ONLY for issue #11. Do NOT execute or write any implementation code.
Fetch main, drift-check the issue against current main, invoke /itx:plan-create,
write plan to .itx/11/00_PLAN.md, stop.
```

### Planning (v2 — add UAT contract)

```prompt
Additional planning requirement: include an explicit "Real-host UAT" section
that MUST run before the PR is opened during execution. Target: wolf-i.
Discover attached integrations. Record host + observed behavior in PR body.
```

### Planning (v3 — customer-outcome reframe)

```prompt
This plan is too technical and engineering focused. I need a phase wise
breakdown that is customer outcome focused. Each phase independently
verifiable, not breaking existing workflows.
```

### Planning (v4 — hard-dependency stance)

```prompt
Don't make NemoClaw as an optional dependency of OpenClaw. When using
Clawrium, OpenClaw will only be installed as a NemoClaw or with NemoClaw
as part of it because of security reasons. Update the plan.
```

### Planning (v5 — collapse to 4 phases)

**Timestamp**: 2026-07-24T00:00:00Z

```prompt
Update the plan with 4 phases. Use /itx-scaffold and send pr for updated plan.
```

**Output**: `.itx/11/00_PLAN.md` — 4-phase customer-outcome plan with NemoClaw as a hard prerequisite of every openclaw install. Phases 1–2 additive; phase 3 breaking cut-over; phase 4 credential handoff on shared code. Scaffold in `01_SCAFFOLD.md`. PR opened for review.
