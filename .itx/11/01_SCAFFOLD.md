# Issue #11 — Execution Scaffold

**Mode**: multi-phase (4 phases)
**Base**: `origin/main` @ `fd9e72f`
**Plan**: `.itx/11/00_PLAN.md`
**Target host for all UAT**: `wolf-i` (Ubuntu 24.04, x86_64)

Ordering rule: strictly 1 → 2 → 3 → 4. Exit criteria of phase N == entry criteria of phase N+1. No parallel execution — phases 1 and 4 both touch shared code (`core/lifecycle.py`, `core/render.py`), and phase 2's outcome (sandboxed openclaw path) is the precondition for phase 3's bare-path delete.

---

## Phase 1 — Groundwork

**Complexity**: moderate

**Entry Criteria**
- Branch created off `origin/main` @ `fd9e72f` or later.
- Owner has answered §7.1 of the plan (NVIDIA NemoClaw exists as described) OR phase-1 validity gate is expected to answer it (in which case phase 1 may fail closed and STOP).
- `wolf-i` reachable via `clawctl agent get` on the developer machine.

**Work**
- Validity gate: fetch `docs.nvidia.com/nemoclaw`, `github.com/NVIDIA/NemoClaw`, tag `v0.0.44`, per-arch tarballs, published SHA256s.
- Create `docs/agent-support/nemoclaw.md` + `website/docs/agent-support/nemoclaw.md` mirror.
- Create `src/clawrium/core/nemoclaw.py` skeleton (version constant + upstream URL/SHA table only; no behavior).
- Create `src/clawrium/cli/clawctl/doctor/nemoclaw.py` — read-only probe.
- Delete `"nc": "nemoclaw"` alias in `src/clawrium/core/lifecycle.py:136`.
- Drop `nemoclaw` row from `website/docs/reference/cli/registry.md:36`.
- Remove `nemoclaw` from `docs/agent-support/hermes.md:170` + website mirror.
- Scrub `nemoclaw` from test fixtures (grep-driven).
- `CHANGELOG.md` `### BREAKING`: `nc` alias removal.

**Files Affected**
- `docs/agent-support/nemoclaw.md` (new)
- `website/docs/agent-support/nemoclaw.md` (new)
- `src/clawrium/core/nemoclaw.py` (new)
- `src/clawrium/cli/clawctl/doctor/nemoclaw.py` (new)
- `src/clawrium/core/lifecycle.py` (delete `nc` alias)
- `website/docs/reference/cli/registry.md` (drop row)
- `docs/agent-support/hermes.md` + `website/docs/agent-support/hermes.md` (drop mention)
- `tests/**` (scrub `nemoclaw` fixtures)
- `tests/cli/clawctl/doctor/test_nemoclaw.py` (new)
- `CHANGELOG.md` (BREAKING entry)

**Exit Criteria**
- `make lint && make test` pass.
- `clawctl --help` shows no `nc` alias.
- `clawctl agent registry get` no longer lists `nemoclaw`.
- `clawctl agent create --type nc <…>` returns "unknown alias" cleanly (no traceback).
- `clawctl doctor nemoclaw` on the developer machine reports `reachable / correct-sha / arch-match` OR the validity gate has failed and the phase halts with a `re-triage` recommendation on the issue.
- Real-host UAT run on wolf-i per `.itx/11/00_PLAN.md` §6, phase-1 row; every agent in the non-regression table is PASS.
- PR body includes the §6 UAT template, fully populated.

**Dependencies**: None (first phase).

---

## Phase 2 — NemoClaw on hosts + sandboxed openclaw available

**Complexity**: complex

**Entry Criteria**
- Phase 1 merged to `main`.
- Validity gate passed (NVIDIA NemoClaw upstream confirmed real).
- Owner has answered §7.2 (macOS openclaw fate).

**Work**
- New `src/clawrium/platform/registry/openclaw/playbooks/install_nemoclaw.yaml` (+ `_macos` sibling per §7.2). Task-0 OS dispatcher guard, arch guard, `get_url` with `sha256:` against pinned tarball, extract to `/usr/local/lib/nemoclaw/<version>/`, idempotent by version-dir + checksum.
- New `src/clawrium/platform/registry/openclaw/playbooks/install_prereqs.yaml` — Ubuntu ≥ 24.04 / ≥ 8 GB RAM / ≥ 20 GB disk asserts; `apt-get install git zstd`; Docker Engine via Docker's Ubuntu apt repo; NVM + Node 22.16; SSH user in `docker` group.
- Wire both into `openclaw/playbooks/install.yaml`'s host-prep phase.
- `src/clawrium/core/nemoclaw.py` grows a thin CLI wrapper (onboard / start / stop / status / logs / destroy).
- New `_openclaw_nemoclaw_onboard` helper in `src/clawrium/core/lifecycle_canonical.py`, invoked by `sync_agent_canonical` before the file-write loop (mirror `_openclaw_install_plugins` / `_openclaw_install_slack_mcp` shape).
- `src/clawrium/platform/registry/openclaw/manifest.yaml` grows `runtime.nemoclaw.version` pin.
- 3-way version-pin lockstep test in `tests/platform/`.
- New openclaw creates persist `{runtime: "nemoclaw", sandbox_name, nemoclaw_version}` in `hosts.json.agents.<name>.config`.
- Bare openclaw path remains intact — legacy `e2e-openclaw` on wolf-i must still sync cleanly.

**Files Affected**
- `src/clawrium/platform/registry/openclaw/manifest.yaml` (add pin)
- `src/clawrium/platform/registry/openclaw/playbooks/install.yaml` (wire host-prep)
- `src/clawrium/platform/registry/openclaw/playbooks/install_nemoclaw.yaml` (new)
- `src/clawrium/platform/registry/openclaw/playbooks/install_nemoclaw_macos.yaml` (new, conditional on §7.2)
- `src/clawrium/platform/registry/openclaw/playbooks/install_prereqs.yaml` (new)
- `src/clawrium/core/nemoclaw.py` (CLI wrapper)
- `src/clawrium/core/lifecycle_canonical.py` (`_openclaw_nemoclaw_onboard`)
- `tests/platform/test_nemoclaw_pin_lockstep.py` (new)
- `tests/core/test_lifecycle_canonical.py` (extend)
- `tests/cli/clawctl/agent/test_create.py` (extend)

**Exit Criteria**
- `make lint && make test` pass.
- On wolf-i: `clawctl host prepare wolf-i` completes idempotently; SSH → `nemoclaw --version` returns the pin.
- On wolf-i: `clawctl agent create --type openclaw --host wolf-i --name e2e-openclaw-nemo` succeeds; `clawctl agent get` shows `runtime: nemoclaw@<version>` on that row; `nemoclaw <sandbox> status` reports healthy.
- On wolf-i: legacy bare `e2e-openclaw` still runs; `clawctl agent sync e2e-openclaw` is a clean no-op.
- Non-regression UAT (phase-2 row of §6) — all agents PASS.
- PR body includes fully-populated UAT template.

**Dependencies**: Phase 1.

---

## Phase 3 — Delete bare openclaw + full lifecycle + fleet visibility (BREAKING)

**Complexity**: complex

**Entry Criteria**
- Phase 2 merged to `main`.
- Owner has answered §7.3 (existing-fleet migration: confirmed "remove + re-create" with no automated migration) and §7.4 (`clawctl host validate` + `agent get` extension is the right shape).
- Sandboxed openclaw path proven on wolf-i by `e2e-openclaw-nemo` running healthily since phase 2.

**Work**
- Delete every code branch keyed on "no runtime" / bare openclaw. No `--runtime bare` flag.
- `clawctl agent {start,stop,status,logs,sync,remove}` fully delegate to NemoClaw. `sync` re-onboards on pin changes and short-circuits before restart on failure. `remove` destroys the sandbox before uninstalling openclaw bits.
- Extend `clawctl agent get` row: `runtime: nemoclaw@<version>` on every openclaw row.
- New `src/clawrium/cli/clawctl/host/validate.py` — aggregates `nemoclaw <sandbox> status` for every openclaw on the host.
- Update `docs/agent-support/openclaw.md` + website mirror: NemoClaw substrate, Ubuntu 24.04+ floor, upgrade + rollback path.
- Migration note in `docs/releases/<next-version>/` with explicit "remove + re-create" instructions.
- `CHANGELOG.md` `### BREAKING`: bare openclaw removed.

**Files Affected**
- `src/clawrium/platform/registry/openclaw/playbooks/install.yaml` (delete bare branch)
- `src/clawrium/platform/registry/openclaw/playbooks/install_macos.yaml` (per §7.2 outcome)
- `src/clawrium/platform/registry/openclaw/playbooks/remove.yaml` (sandbox teardown first)
- `src/clawrium/core/lifecycle_canonical.py` (teardown mirror)
- `src/clawrium/core/lifecycle.py` (verb delegation)
- `src/clawrium/cli/clawctl/agent/create.py`, `remove.py`, `get.py` (row extension)
- `src/clawrium/cli/clawctl/host/validate.py` (new)
- `docs/agent-support/openclaw.md` + website mirror
- `docs/releases/<next-version>/CHANGELOG.md` (migration note)
- `CHANGELOG.md` (BREAKING)
- `tests/cli/clawctl/host/test_validate.py` (new)
- `tests/cli/clawctl/agent/` (extend)

**Exit Criteria**
- `make lint && make test` pass.
- `git grep` for the bare openclaw install code path returns nothing.
- On wolf-i: `clawctl agent remove e2e-openclaw` succeeds; `clawctl agent create --type openclaw --host wolf-i --name e2e-openclaw` re-creates it sandboxed. `e2e-openclaw-nemo` from phase 2 removed as duplicate.
- On wolf-i: full `clawctl agent {start,stop,status,logs,sync,remove}` round-trip works on sandboxed `e2e-openclaw`.
- On wolf-i: `clawctl host validate wolf-i` exits 0.
- On wolf-i: `clawctl agent get` shows `runtime: nemoclaw@<version>` on every openclaw row.
- Non-regression UAT (phase-3 row of §6) — all agents PASS. **Explicit smoke on integration-carrying hermes agents to confirm no shared-code regression.**
- PR body includes fully-populated UAT template + link to migration note.

**Dependencies**: Phase 2.

---

## Phase 4 — Provider credential handoff to the NemoClaw gateway

**Complexity**: moderate

**Entry Criteria**
- Phase 3 merged to `main`.
- Owner has answered §7.5 (blueprint override path — reconcile "no Clawrium blueprint" with "NemoClaw CLI never exposed to end users" for custom providers).
- All openclaw agents on wolf-i are sandboxed (phase 3 exit).

**Work**
- Delete provider env injection from openclaw's render path in `src/clawrium/core/render.py`.
- Route provider `api_key` / `base_url` to a NemoClaw gateway-registration payload on `clawctl agent configure`.
- `openclaw/playbooks/configure.yaml`: swap env injection for gateway-registration step.
- Test: no `*_API_KEY` visible from inside the sandbox; egress calls still succeed via gateway proxy.
- `CHANGELOG.md` `### BREAKING`: scripts reading keys from openclaw process env stop working.

**Files Affected**
- `src/clawrium/core/render.py` (delete openclaw env-key path; add gateway payload)
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml` (gateway registration)
- `tests/core/test_render_openclaw.py` (extend — assert no api_key in openclaw config)
- `tests/core/test_render_openclaw_gateway.py` (new — assert gateway payload carries key)
- `CHANGELOG.md` (BREAKING)

**Exit Criteria**
- `make lint && make test` pass.
- On wolf-i: `clawctl agent configure e2e-openclaw` with a provider key succeeds.
- On wolf-i: `clawctl agent exec e2e-openclaw -- env` inside the sandbox shows no `*_API_KEY`.
- On wolf-i: provider call from openclaw succeeds via gateway proxy (verified by whatever agent-side test the sandbox permits).
- **Critical non-regression**: every integration-carrying hermes / zeroclaw agent on wolf-i is re-configured and `clawrium-github` / `clawrium-d01-github` remain functional. `core/render.py` is shared code — this is the whole point of the phase-4 non-regression scope.
- PR body includes fully-populated UAT template.

**Dependencies**: Phase 3.

---

## Subtasks

Not created yet (owner instruction: planning only, no execution). Once §7 open questions resolve, create four subtasks with `--label ready`:

- `[Parent #11] Phase 1: Groundwork — validity gate, doctor probe, purge stale nemoclaw residue`
- `[Parent #11] Phase 2: NemoClaw on hosts + sandboxed openclaw available`
- `[Parent #11] Phase 3: Delete bare openclaw + full lifecycle + fleet visibility (BREAKING)`
- `[Parent #11] Phase 4: Provider credential handoff to NemoClaw gateway`

---

## Prompt Log

### Scaffolding

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-07-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Update the plan with 4 phases. Use /itx-scaffold and send pr for updated plan.
```

**Output**: `.itx/11/01_SCAFFOLD.md` — 4-phase execution scaffold with entry/exit criteria per phase, strictly serialized. Real-host UAT on wolf-i required for every phase exit. Subtasks documented but not yet created.
