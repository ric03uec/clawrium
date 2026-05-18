# Issue #364 — Execution Scaffolding

**Mode**: multi-phase (6 PR phases + 1 research phase)

**Sequencing intent**: Ship the full **CLI** capability first (Phases 1–3) — at the end of Phase 3 a CLI user can browse, install, list, and remove a skill on any of the three claw types. Then mirror the same outcomes in the **browser** (Phases 4–5). Phase 6 lands the contributor safety net last, securing a fully working surface rather than half-built scaffolding.

**Verification model**:
- **Unit tests** (mocked `ansible-runner`) are checked into `tests/` and gate `make test`.
- **Real-host smoke tests** are executor-run during `/itx:execute`, documented in each PR's body and the phase's execution notes, and are **never committed**.
- **One shared test host** is pre-staged in Phase 0 with all three claw types installed; every subsequent phase installs/removes the seed skill `clawrium/tdd` against those already-running agents.

---

## Phase 0: Research & Test-Fleet Stand-Up

**Tracked as subtask #386.** Originally scoped as research-only with no PR; repackaged for orchestrate-mode compatibility as a tiny artifact PR (one doc file) whose existence signals the downstream chain to start.

**Entry Criteria**
- [ ] Plan `.itx/364/00_PLAN.md` exists and is current
- [ ] Issue #364 has `planned` label
- [ ] Real test host reachable from operator's machine via SSH (`clm host add` candidate)

**Work**
1. Verify whether openclaw in this fork uses **auto-scan** (`~/.openclaw/skills/<name>/` is enough) or is **config-driven** (`openclaw.json` must be re-rendered). Read upstream / fork source under `src/clawrium/platform/registry/openclaw/`.
2. Confirm zeroclaw on-host skill path is `~/.zeroclaw/skills/<name>/` and that the native `zeroclaw skills install <staging-path>` CLI exists in the version pinned by the manifest.
3. Lock the normalized `_meta.yaml` / frontmatter shape for `clawrium/tdd` such that it passes all three native schemas (openclaw, hermes, zeroclaw). Draft as a working JSON document, not yet a schema file.
4. Pre-install all three claw types on the shared test host:
   ```bash
   clm host add <ip> --alias smoke
   clm agent install --type hermes   --host smoke
   clm agent install --type openclaw --host smoke
   clm agent install --type zeroclaw --host smoke
   clm agent configure <each>
   clm agent start     <each>
   clm ps   # all three Running
   ```
5. Record the three agent names in the Phase 0 comment so every subsequent phase reuses them verbatim.

**Exit Criteria**
- [ ] `.itx/364/02_PHASE0_FINDINGS.md` committed answering Q1 (openclaw auto-scan vs config-driven), Q2 (zeroclaw path + CLI version), Q3 (locked `_meta.yaml` shape), Q4 (test fleet agent names)
- [ ] All three test agents are `Running` (paste `clm ps` output into findings doc)
- [ ] PR opened against `main` titled `chore(#364): Phase 0 — research + test-fleet stand-up`
- [ ] ATX rating > 3/5

**Dependencies**: None

**Complexity**: simple (research + one-time host setup + one doc commit)

---

## Phase 1: CLI — Browse the Catalog

**User outcome**: `clm skill list` and `clm skill show clawrium/tdd` return real data from the in-repo catalog.

**Entry Criteria**
- [ ] Phase 0 complete; openclaw discovery mode + zeroclaw path known; normalized `_meta.yaml` shape locked
- [ ] Branch `issue-364-phase-1-catalog-browse` cut from `main`

**Files Affected**

| File | Change |
|------|--------|
| `skills/README.md` | New — namespace rules, authoring guide |
| `skills/_schema/clawrium.schema.json` | New |
| `skills/_schema/native/openclaw.schema.json` | New |
| `skills/_schema/native/hermes.schema.json` | New |
| `skills/_schema/native/zeroclaw.schema.json` | New |
| `skills/clawrium/tdd/SKILL.md` | New — seed skill content |
| `skills/clawrium/tdd/README.md` | New |
| `skills/clawrium/tdd/_meta.yaml` | New — fields satisfy all three native schemas |
| `skills/openclaw/README.md` | New — namespace placeholder |
| `skills/hermes/README.md` | New |
| `skills/zeroclaw/README.md` | New |
| `src/clawrium/core/skills.py` | New — `parse_skill_ref`, `load_skill`, `validate_skill` (dual-schema dispatch), `check_agent_compatibility`, error classes (`MissingRegistryPrefix`, `IncompatibleSkillRegistry`, `SkillNotFound`, `ExternalSourceBlocked`) |
| `src/clawrium/cli/skill.py` | New — `list`, `show` |
| `src/clawrium/cli/main.py` | Modify — register `skill_app` |
| `tests/test_core_skills.py` | New — schema validation, dual-schema dispatch |
| `tests/test_skills_namespace.py` | New — `parse_skill_ref` errors, external-source blocked |
| `tests/test_cli_skill.py` | New — `list`, `show` CLI surface |

**Exit Criteria**
- [ ] `clm skill list` shows `clawrium/tdd` with its registry, name, description, and supported claws
- [ ] `clm skill list --registry clawrium` filters to clawrium-only
- [ ] `clm skill show clawrium/tdd` prints manifest + README
- [ ] `clm skill show clawrium/does-not-exist` returns `SkillNotFound` with non-zero exit
- [ ] `clm skill show tdd` (bare name) returns `MissingRegistryPrefix` with a hint
- [ ] `clm skill show https://example.com/foo` returns `ExternalSourceBlocked`
- [ ] `make test` green; `make lint` clean
- [ ] **Smoke test (executor, documented in PR body, not committed)**:
  - On operator's machine (no remote host needed): exercise the four CLI cases above and confirm exit codes + human-readable output

**Dependencies**: Phase 0

**Complexity**: moderate (new module + new CLI + dual schemas)

---

## Phase 2: CLI — Install Skill on Hermes End-to-End

**User outcome**: `clm agent skill install <hermes-agent> clawrium/tdd` writes desired-state, runs the per-claw apply playbook, and the skill lands on the host. `list` and `remove` round-trip works. Re-running `install` after manually deleting the on-host file reconverges (drift recovery).

**Entry Criteria**
- [ ] Phase 1 merged to `main`
- [ ] Phase 0 test host still has a `Running` hermes agent
- [ ] Branch `issue-364-phase-2-cli-install-hermes` cut from `main`

**Files Affected**

| File | Change |
|------|--------|
| `src/clawrium/core/skills_state.py` | New — desired-state file at `~/.config/clawrium/agents/<agent>/skills.json`, entries `<registry>/<name>` |
| `src/clawrium/core/skills.py` | Extend — `apply_state(agent)` entrypoint that dispatches to per-claw playbook |
| `src/clawrium/platform/registry/hermes/playbooks/skills_apply.yaml` | New — copy to `~/.hermes/skills/clawrium/<name>/`, bounded prune of `~/.hermes/skills/clawrium/` only |
| `src/clawrium/cli/agent.py` | Modify — register `skill` sub-app: `list`, `install`, `remove` (verb-first: `clm agent skill install <agent> <ref>`) |
| `tests/test_skills_state.py` | New — state-file round-trip, idempotent writes |
| `tests/test_skills_apply_hermes.py` | New — install → list → remove round-trip via mocked `ansible-runner`, pruning bounds, drift simulation |
| `tests/test_cli_skill_agent.py` | New — verb-first surface, error propagation |

**Exit Criteria**
- [ ] `make test` green; `make lint` clean
- [ ] CLI: `clm agent skill install <hermes> bare-name` → `MissingRegistryPrefix`
- [ ] CLI: `clm agent skill install <hermes> openclaw/something` → `IncompatibleSkillRegistry` (skill is a native-openclaw skill on a hermes agent)
- [ ] **Smoke test on Phase 0's hermes agent (documented in PR body, not committed)**:
  - `clm agent skill install <hermes> clawrium/tdd` → 0 exit
  - SSH to host: `ls ~/.hermes/skills/clawrium/tdd/` shows the materialized files
  - `clm agent skill list <hermes>` → shows `clawrium/tdd`
  - Re-run install (idempotent) → no diff, no error
  - SSH to host: `rm -rf ~/.hermes/skills/clawrium/tdd/`
  - Re-run install → reconverges, file present again (drift recovery)
  - `clm agent skill remove <hermes> clawrium/tdd` → file gone from host, gone from state file
  - User-authored file `~/.hermes/skills/user-thing/` survives the round-trip (pruning bounds)

**Dependencies**: Phase 1

**Complexity**: moderate (state store + first per-claw playbook + CLI subapp)

---

## Phase 3: CLI — Same Skill on Openclaw + Zeroclaw

**User outcome**: `clawrium/tdd` installs identically on openclaw and zeroclaw agents. All three claw types are now reachable from the CLI.

**Entry Criteria**
- [ ] Phase 2 merged to `main`
- [ ] Phase 0 test host still has `Running` openclaw and zeroclaw agents
- [ ] Branch `issue-364-phase-3-cli-install-openclaw-zeroclaw` cut from `main`

**Files Affected**

| File | Change |
|------|--------|
| `src/clawrium/platform/registry/openclaw/playbooks/skills_apply.yaml` | New — copy to `~/.openclaw/skills/<name>/`; re-render `openclaw.json` iff Phase 0 confirmed config-driven; bounded prune |
| `src/clawrium/platform/registry/zeroclaw/playbooks/skills_apply.yaml` | New — stage to temp dir; invoke `zeroclaw skills install <staging>` so native audit gate runs; idempotency via `zeroclaw skills list` diff |
| `tests/test_skills_apply_openclaw.py` | New — round-trip via mocked `ansible-runner`, assert `openclaw.json` re-render hook fires (if config-driven), bounded prune |
| `tests/test_skills_apply_zeroclaw.py` | New — round-trip via mocked `ansible-runner`, assert native `zeroclaw skills install` is invoked (not raw copy), idempotency diff check |

**Exit Criteria**
- [ ] `make test` green; `make lint` clean
- [ ] **Smoke test on Phase 0's openclaw agent**:
  - Same install / list / remove / drift / pruning sequence as Phase 2
  - SSH: `ls ~/.openclaw/skills/tdd/` shows the materialized files
  - If config-driven: `~/.openclaw/openclaw.json` references the new skill after install, no longer references it after remove
- [ ] **Smoke test on Phase 0's zeroclaw agent**:
  - Same install / list / remove / drift sequence
  - SSH: `zeroclaw skills list` shows `tdd` after install, omits it after remove
  - SSH: `~/.zeroclaw/skills/tdd/` present (materialized by the native CLI, not by raw copy)
  - Re-installing an already-installed skill is a no-op (idempotency via `zeroclaw skills list` diff)
- [ ] **Cross-claw parity check**: same `clawrium/tdd` content surfaces correctly on all three claws

**Dependencies**: Phase 2

**Complexity**: moderate (two more playbooks, zeroclaw native-CLI wrap is the trickiest)

---

> **🏁 Milestone: CLI complete** — at the end of Phase 3, every user-facing outcome is reachable from the terminal. Phases 4 and 5 only mirror these into the browser.

---

## Phase 4: Browser — Browse the Catalog (mirror of Phase 1)

**User outcome**: User opens the GUI, navigates to `/skills`, sees registry-tabbed catalog, opens skill detail.

**Entry Criteria**
- [ ] Phase 3 merged to `main`
- [ ] GUI dev server runs locally (`make gui-dev` or equivalent)
- [ ] Branch `issue-364-phase-4-gui-browse` cut from `main`

**Files Affected**

| File | Change |
|------|--------|
| `src/clawrium/gui/routes/skills.py` | New — `GET /api/skills` (grouped by registry), `GET /api/skills/{registry}/{name}` |
| `src/clawrium/gui/server.py` | Modify — register skills router |
| `gui/src/app/skills/page.tsx` | New — registry-tab catalog browse |
| `gui/src/components/skills/SkillCard.tsx` | New |
| `gui/src/components/skills/SkillDetail.tsx` | New |
| `tests/test_gui_skills_routes.py` | New — route 200/404/422 paths |
| `gui/src/app/skills/page.test.tsx` | New — Vitest page render |

**Exit Criteria**
- [ ] `make test` green; `make lint` clean; Vitest passes
- [ ] **Smoke test (browser session, documented in PR body, not committed)**:
  - Open GUI; navigate to `/skills`; see tabs for `clawrium`, `openclaw`, `hermes`, `zeroclaw`
  - Click `clawrium/tdd` card; detail page renders manifest fields + README
  - 404 path: directly navigate to `/skills/clawrium/does-not-exist` → friendly error
  - No remote host required for this phase

**Dependencies**: Phase 3 (depends on `core/skills.py` API stabilized after Phase 2; Phase 3 added no new core surface)

**Complexity**: moderate

---

## Phase 5: Browser — Install / List / Remove on All Three Real Agents (mirror of Phases 2–3)

**User outcome**: User opens an agent detail page, opens the Skills tab, picks `clawrium/tdd` from the filtered picker, clicks Install, sees it in the installed list. Same for remove. All three real agents reachable.

**Entry Criteria**
- [ ] Phase 4 merged to `main`
- [ ] All three Phase 0 agents still `Running`
- [ ] Branch `issue-364-phase-5-gui-install` cut from `main`

**Files Affected**

| File | Change |
|------|--------|
| `src/clawrium/gui/routes/agents.py` | Extend — `GET /api/agents/{agent}/skills`, `POST /api/agents/{agent}/skills/{registry}/{skill}`, `DELETE /api/agents/{agent}/skills/{registry}/{skill}` |
| `gui/src/app/agents/page.tsx` | Modify — add Skills tab on agent detail with filtered install picker (`clawrium/*` + matching `<claw>/*`) |
| `gui/src/components/skills/AgentSkillsPanel.tsx` | New |
| `tests/test_gui_agent_skills_routes.py` | New — install/list/remove routes against mocked `apply_state` |
| `gui/src/components/skills/AgentSkillsPanel.test.tsx` | New — Vitest install dialog flow |

**Exit Criteria**
- [ ] `make test` green; `make lint` clean; Vitest passes
- [ ] **Smoke test on each of the three Phase 0 agents (documented in PR body, not committed)**:
  - For hermes, openclaw, zeroclaw in turn:
    - Open agent detail → Skills tab → install `clawrium/tdd` via picker
    - SSH to host: file materialized at expected path
    - Skills tab shows `clawrium/tdd` as installed
    - Click Remove → file gone from host, tab updates
    - Drift: SSH-delete the file, click Install again → reconverges
  - Verify filtered picker correctness: on hermes agent detail, `openclaw/*` skills do not appear in the install picker
- [ ] **Cross-surface parity check**: a skill installed via the browser shows up in `clm agent skill list <agent>` (and vice versa) — confirms both surfaces share `desired-state`

**Dependencies**: Phase 4 (GUI scaffolding); Phase 3 (all three playbooks landed)

**Complexity**: moderate (GUI install flow + agent-type-filtered picker)

---

## Phase 6: Contributor Safety Net (Docs + CI)

**User outcome**: A new contributor can read `docs/skills/authoring-clawrium.md`, drop a skill into `skills/clawrium/<name>/`, open a PR, and have CI catch schema mistakes before maintainer review.

**Entry Criteria**
- [ ] Phase 5 merged to `main`
- [ ] Branch `issue-364-phase-6-docs-ci` cut from `main`

**Files Affected**

| File | Change |
|------|--------|
| `.github/workflows/skills-validate.yml` | New — runs `scripts/validate_skills.py` on PRs touching `skills/**` |
| `scripts/validate_skills.py` | New — dual-schema validation, path-traversal check, schema-mismatch rejection (e.g. clawrium-schema fields under `skills/zeroclaw/` rejected) |
| `docs/skills/index.md` | New |
| `docs/skills/authoring-clawrium.md` | New |
| `docs/skills/authoring-native.md` | New |
| `website/docs/skills/intro.md` | New |
| `website/docs/skills/authoring.md` | New |
| `AGENTS.md` | Modify — quickstart update with `clm agent skill install` example |
| `tests/fixtures/skills/_invalid/clawrium-schema-under-zeroclaw/` | New (fixture, NOT a real skill) — used to assert CI rejection |
| `tests/fixtures/skills/_invalid/path-traversal/` | New (fixture) — used to assert CI rejection |
| `tests/test_validate_skills.py` | New — drives `scripts/validate_skills.py` on the fixtures |

**Exit Criteria**
- [ ] `make test` green; `make lint` clean
- [ ] CI workflow exercised on a draft PR with an intentionally-broken skill (path traversal, schema mismatch) — rejected with a clear message
- [ ] CI workflow on a draft PR with a valid new skill passes
- [ ] **Final acceptance smoke test (executor, documented in PR body)** — one full sweep on the Phase 0 host:
  - `clm skill list` ✓
  - CLI install/list/remove on hermes ✓
  - CLI install/list/remove on openclaw ✓
  - CLI install/list/remove on zeroclaw ✓
  - GUI browse + install/remove on all three ✓
- [ ] Docs render cleanly on the website preview build
- [ ] `AGENTS.md` quickstart works verbatim when copied to a fresh shell

**Dependencies**: Phase 5

**Complexity**: simple-to-moderate (mostly content + a single workflow file)

---

## Subtasks Created

| Phase | Subtask Issue |
|---|---|
| 0 | #386 — Research + test-fleet stand-up |
| 1 | #380 — CLI: Browse the skills catalog |
| 2 | #381 — CLI: Install on real hermes agent end-to-end |
| 3 | #382 — CLI: Same skill on real openclaw + zeroclaw agents |
| 4 | #383 — Browser: Browse the skills catalog |
| 5 | #384 — Browser: Install/list/remove on all three real agents |
| 6 | #385 — Contributor safety net: docs + CI dual-schema validation |

Phase 0 originally was research-only; repackaged as a subtask with a tiny artifact PR (`.itx/364/02_PHASE0_FINDINGS.md`) so the orchestrator has a "PR open ⇒ ATX cleared ⇒ spawn next phase" signal.

---

## Risks Carried Forward From Plan

1. **Openclaw discovery mode unknown** — Phase 0 verifies. If config-driven, Phase 3 must re-render `openclaw.json`; the playbook handles both modes behind a manifest flag.
2. **Zeroclaw native CLI version drift** — the manifest pins the zeroclaw version; Phase 3's smoke test catches mismatch.
3. **Pruning blast radius** — every playbook prunes only `<host-skill-root>/clawrium/` (or equivalent claw-owned subtree). User-authored skills are out of scope of pruning; Phase 2's smoke test asserts a user file survives.
4. **CLI ↔ GUI drift** — both surfaces share `core/skills.py` and `skills_state.py`. Phase 5's parity check (install via GUI, see it in `clm agent skill list`) is the explicit anti-drift assertion.
5. **Real-host tests are not in CI** — by design (per scaffolding decision). They are executor-run during `/itx:execute` and recorded in each PR body. A failed smoke test blocks merge of that phase.

---

<details>
<summary>Prompt Log</summary>

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-17T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold https://github.com/ric03uec/clawrium/issues/364
```

Iterations in conversation refined the phase structure:
1. v1 (rejected): mirrored 00_PLAN.md's seven horizontal phases. User flagged as "too granular, not outcome focussed."
2. v2: vertical slices — each phase ships a user-visible capability. CLI complete after Phase 3, then GUI mirrors it.
3. v3: split GUI into two phases (browse / install) so each CLI phase has a 1:1 browser counterpart.
4. v4: real-host E2E smoke tests added as exit criteria (executor-run, not committed; only unit tests checked in).
5. v4 final (this doc): single shared host with all three claws pre-installed in Phase 0; reused across Phases 2, 3, 5, and 6.

Customer outcome (carried from issue): "User can browse the clawrium-managed skills registry and install any vetted skill onto any of their agents."

</details>

<details>
<summary>Prompt Log — orchestrate-mode launch</summary>

**Stage**: orchestration
**Skill**: /itx:execute (orchestrate mode)
**Timestamp**: 2026-05-17T16:34:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute orchestrate 364
```

Pre-flight decisions captured during conversation:
1. Phase 0 originally had no PR; repackaged as subtask #386 producing a tiny artifact PR (`.itx/364/02_PHASE0_FINDINGS.md`) so the orchestrator has a "PR open ⇒ spawn next" signal. #386 was reprioritized to first position in the parent's sub-issue list.
2. Real-host smoke tests in Phases 2/3/5/6 will be attempted autonomously by each child claude session (relies on the operator's `~/.config/clawrium/hosts.json` and `~/.ssh` being accessible from the worktree).
3. Stacked PR chain: 0 → 1 → 2 → 3 → 4 → 5 → 6. Each phase's PR base is the predecessor's branch; GitHub auto-updates bases to `main` as predecessors merge.
4. Polling lives in `.itx/364/orchestrate-runner.sh` running in tmux window `itx/364:runner`. Polls every 5 min; halts on `[ITX-STUCK]` comments and surfaces them via the runner log.

</details>
