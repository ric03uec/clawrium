# Issue #760 — Execution Scaffolding

**Mode**: multi-phase, **vertical agent slices** (6 phases — 3 Ubuntu in scope + 3 macOS deferred)

Source plan: [`.itx/760/00_PLAN.md`](./00_PLAN.md) — merged across iters
1–3 (PRs #763, #765). `clawctl agent shell` available via #761 (PR
#764 merged).

## Slicing Strategy

Each phase ships **one agent type on one OS, fully end-to-end**:
manifest + playbook + lifecycle integration + CLI + tests + E2E on a
real host. The next agent only starts once the prior agent is green
on the host.

Why vertical:
- Every phase is independently shippable and reversible.
- The design contracts (Ansible extravar shape, phase ordering, error
  surface) get stress-tested on a real host before complicating with
  the next agent's invariants.
- Cross-agent shared infrastructure (the `workspace_sync.py` module,
  the manifest loader, the CLI flags) lands in Phase 1 alongside
  openclaw — the simplest agent — so it's exercised end-to-end on day
  one rather than carried unverified across multiple horizontal phases.

Ordering, simplest-to-hardest:
1. **openclaw** first — no bearer rotation, no excludes, native
   `~/.openclaw/workspace/` matches the destination directly.
2. **zeroclaw** second — adds the bearer-rotation invariant (#437),
   the highest-risk piece in the project. Adding it on top of an
   already-shipped openclaw flow means we only debug bearer issues,
   not the file-push pipeline.
3. **hermes** third — adds the exclude list (no native workspace dir;
   shares destination root with canonical-render output). Most complex
   destination semantics.

macOS slices (Phase 4/5/6) follow the same ordering but are deferred
out of this iteration.

## Dependency Graph

```
Phase 1 (openclaw / Ubuntu)
   └──> Phase 2 (zeroclaw / Ubuntu) — depends on (1) for shared infra
            └──> Phase 3 (hermes / Ubuntu) — depends on (1,2)
                    └──> Phase 4 (openclaw / macOS)
                            └──> Phase 5 (zeroclaw / macOS)
                                    └──> Phase 6 (hermes / macOS)
```

Phases 2 and 3 ride on the foundation Phase 1 ships. Phases 4–6 are
follow-ups; the `_macos.yaml` stubs land in Phases 1–3 so dispatcher
routing exists from day one.

---

## Phase 1 — openclaw end-to-end on Ubuntu (`wolf-i`)

Ships the **shared foundation** (workspace_sync module, manifest
loader, CLI flags, install scaffold) alongside the openclaw-specific
manifest and playbook.

**Entry Criteria**:
- Plan iter-3 merged to main (true — `34f7222`).
- `clawctl agent shell` on main (true — #764).
- `wolf-i` reachable and healthy.
- Branch `feat/760-phase-1-openclaw` from main.

**Exit Criteria** (must all be true to call Phase 1 done):

*Code:*
- `src/clawrium/core/workspace_sync.py` exports `push_workspace_phase`,
  `enumerate_workspace_files`, `WorkspaceOverlaySpec`,
  `WorkspaceSyncError`, `WorkspacePhaseResult`. No `paramiko` import,
  no `sys.platform` / `platform.system()` / `os_family ==` literals.
- Manifest loader returns a typed `WorkspaceOverlaySpec` when
  `features.workspace_overlay` is present.
- `src/clawrium/platform/registry/openclaw/manifest.yaml` carries
  `features.workspace_overlay: {destination_root: "~/.openclaw/workspace",
  excludes: []}`.
- `src/clawrium/platform/registry/openclaw/playbooks/workspace.yaml`
  + `workspace_macos.yaml` (stub) present. Linux playbook uses
  `become_user: "{{ agent_name }}"`, dest as `{{ workspace_dest_root }}/{{ item.rel }}`,
  asserts `/home/{{ agent_name }}/` prefix, NEVER references
  `ansible_user_dir` (B1 iter-3).
- `sync_agent_canonical` runs the workspace phase between canonical
  write loop and restart per §1.4. `configure_agent` (core) calls
  `push_workspace_phase` alongside `_do_pair()` (W3 iter-3).
- `CanonicalSyncResult` carries `workspace_files_pushed` /
  `workspace_files_excluded`.
- CLI flags landed: `--workspace-only`, `--no-restart`, `--workspace`
  hard error (hidden=True). `--workspace-only --diff` mutex rejected
  via `cli/output/errors.py`. Help text + short string updated.
- `install.py:create_agent` mkdirs the local workspace scaffold for
  openclaw (idempotent on pre-existing).

*Tests (the openclaw-applicable subset of §3.1 / §3.2):*
- Unit: U1 (openclaw row), U2 (openclaw destination pinned), U4
  (openclaw empty excludes), U5 (openclaw renderer-output-vs-exclude
  invariant — parametrized per S8), U6, U7, U8, U9, U10, U11, U12, U13
  (AST-grep no paramiko / no OS literals in `workspace_sync.py`),
  U14, U15, U17 (openclaw scaffold), U18 (idempotent on existing),
  U19, U20, U21, U22 (openclaw playbook — no `ansible_user_dir`), U23
  (openclaw `follow: no`), U24, U25, U26, U27, U29, U30, U31, U32,
  U34, U35.
- Integration: I1 (openclaw push), I4 (workspace-only skips render +
  restart), I5 (empty workspace no-op), I6 (dry-run check mode), I7
  (mutex), I8 (workspace-failure short-circuits, with W19 frozen-enum
  payload), I9 (NDJSON per file), I10 (darwin dispatch to stub —
  Ansible `fail:` surface only, openclaw stub), I11 (workspace-only
  dry-run), I12 (openclaw configure-path), I15 (result shape — openclaw
  case), I16 (diff renders staged files).
- `make test` green; `make lint` clean.

*E2E on `wolf-i`:*
- §3.3.1 provisioning for `ws-openclaw` clean.
- §3.3.2 E1 matrix passes: marker file lands at
  `/home/ws-openclaw/.openclaw/workspace/MARKER.md` with correct
  mode + owner; `agent doctor` healthy.
- `clawctl agent delete --yes ws-openclaw` cleanup leaves wolf-i in
  its starting state (existing failed openclaw agent untouched).
- E2E run captured under `.itx/760/02_E2E_openclaw_wolf-i.md`.

*Process:*
- ATX review on the implementation PR rated > 3/5, all `B#` resolved.

**Dependencies**: None.

**Files Affected** (Phase 1 only):
- `src/clawrium/core/workspace_sync.py` — NEW
- `src/clawrium/platform/manifest.py` — extend (verify exact filename)
- `src/clawrium/core/lifecycle_canonical.py` — extend sync_agent_canonical
- `src/clawrium/core/lifecycle.py` — wire workspace push in configure_agent
- `src/clawrium/core/install.py` — mkdir scaffold (openclaw)
- `src/clawrium/cli/clawctl/agent/sync.py` — flags
- `src/clawrium/cli/clawctl/agent/configure.py` — presentation-only
- `src/clawrium/cli/clawctl/agent/__init__.py` — short-help string
- `src/clawrium/platform/registry/openclaw/manifest.yaml` — add block
- `src/clawrium/platform/registry/openclaw/playbooks/workspace.yaml` — NEW
- `src/clawrium/platform/registry/openclaw/playbooks/workspace_macos.yaml` — NEW (stub)
- `tests/unit/core/test_workspace_sync.py` — NEW (openclaw subset)
- `tests/unit/platform/test_manifest_workspace_overlay.py` — NEW
- `tests/unit/platform/test_workspace_playbook_structure.py` — NEW (openclaw row)
- `tests/integration/test_workspace_overlay_ubuntu.py` — NEW (openclaw subset)
- `.itx/760/02_E2E_openclaw_wolf-i.md` — NEW (E2E run log)

**Complexity**: complex (foundation + first-agent slice).

**Risk callouts**:
- This phase carries 80% of the cross-cutting risk. Every subsequent
  phase rides on the shared infra contracts landing here. Do NOT
  shortcut the U13 AST-grep test or the U22 no-`ansible_user_dir`
  invariant — those are the regression backstops for B1 iter-3 and
  S4 iter-3.
- Workspace-phase failure MUST short-circuit before restart (I8 +
  W19 frozen-enum payload check). The dual-path canonical-render-vs-
  workspace short-circuit is the regression class iter 2 protected.

---

## Phase 2 — zeroclaw end-to-end on Ubuntu

Adds the **bearer-rotation invariant** (#437) on top of Phase 1.

**Entry Criteria**:
- Phase 1 merged. `wolf-i` E2E for openclaw green.
- Branch `feat/760-phase-2-zeroclaw` from main.

**Exit Criteria**:

*Code:*
- `src/clawrium/platform/registry/zeroclaw/manifest.yaml` adds
  `features.workspace_overlay: {destination_root: "~/.zeroclaw/workspace",
  excludes: []}`.
- `src/clawrium/platform/registry/zeroclaw/playbooks/workspace.yaml`
  + `workspace_macos.yaml` (stub) present, same structural shape as
  openclaw's.
- `sync_agent_canonical` and `configure_agent` correctly route
  zeroclaw through the existing `_zeroclaw_repair_after_start` call.
  Phase-6a (bearer repair) unconditional across default / `--no-restart`
  / `--workspace-only`. Phase-6b (state→READY) only on 6a success.
  `--workspace-only` does NOT transition state (W5 iter-3).
- Dry-run skips bearer rotation via `--check` mode on the pair
  playbook (W6 iter-3).
- Stale-bearer banner: `gateway_auth_stale` NDJSON event + yellow
  stderr banner when phase 4 succeeds and phase 5 fails (W11 iter-3).
- `install.py:create_agent` extended to mkdir zeroclaw workspace
  scaffold.

*Tests:*
- Unit: U2 (zeroclaw destination pinned), U4 (zeroclaw empty
  excludes), U5 (zeroclaw renderer invariant), U17 (zeroclaw scaffold),
  U22 (zeroclaw playbook structural), U23 (zeroclaw `follow: no`),
  U28 (workspace-only preserves zeroclaw bearer rotation).
- Integration: I2 (zeroclaw operator-overrides-seed), I-pair-A (full-
  flow rotation), I-pair-B (workspace-only rotation), I-pair-C (no-
  restart rotation), I-pair-D negative case parametrized over
  `{openclaw, hermes}` (Phase 2 lands the openclaw cell; hermes cell
  is a TODO marker until Phase 3), I-pair-state (state-transition
  skipped on repair failure), I13 (zeroclaw configure path with bearer
  rotation), I17 (workspace-only does not transition state), I18
  (stale-bearer banner on verify failure).
- All pair-related assertions include S1 iter-3: pair playbook
  invoked with expected inventory, not just "any new UUID".
- `make test` + `make lint` clean.

*E2E on `wolf-i`:*
- §3.3.1 provisioning for `ws-zeroclaw` clean.
- §3.3.2 E2 matrix passes:
  - Operator-overridden `SOUL.md` wins;
  - pre/post `hosts.json.gateway.auth` sha256 hashes differ (S5 iter-3
    — never materialize raw bearer);
  - exactly one `gateway_token_rotated` event per sync;
  - `--workspace-only` re-sync also rotates bearer;
  - `agent doctor` healthy after each sync.
- §3.3.3 negative pin: `--workspace-only` against the Phase-1
  `ws-openclaw` (re-provisioned) emits zero `gateway_token_rotated`
  events.
- `clawctl agent delete --yes ws-zeroclaw` cleanup.
- E2E run captured under `.itx/760/03_E2E_zeroclaw_wolf-i.md`.

*Process:*
- ATX review on the implementation PR rated > 3/5; bearer-rotation
  tests under particular scrutiny per #437 history.

**Dependencies**: Phase 1.

**Files Affected** (Phase 2 only):
- `src/clawrium/platform/registry/zeroclaw/manifest.yaml`
- `src/clawrium/platform/registry/zeroclaw/playbooks/workspace.yaml` — NEW
- `src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml` — NEW (stub)
- `src/clawrium/core/lifecycle_canonical.py` — extend zeroclaw
  phase-6 branch (stale-bearer banner + dry-run pair-check)
- `src/clawrium/core/install.py` — extend scaffold map to include
  zeroclaw
- `tests/unit/core/test_workspace_sync.py` — extend (zeroclaw rows)
- `tests/integration/test_workspace_overlay_ubuntu.py` — extend
  (zeroclaw + pair tests)
- `.itx/760/03_E2E_zeroclaw_wolf-i.md` — NEW

**Complexity**: complex (bearer rotation is the project's hottest
invariant).

**Risk callouts**:
- Bearer-hash comparison ONLY; never `set -x` raw values (S5 iter-3).
- `--workspace-only --dry-run` MUST NOT mint a bearer or emit
  `gateway_token_rotated` (W6 iter-3). I11 already covers this; verify
  against `wolf-i` once with `clawctl agent sync ws-zeroclaw
  --workspace-only --dry-run -o json` and assert the event count is
  zero.
- Stale-bearer banner (I18) is operator-visible — without it, verify
  failure leaves operators chasing 401s with no signal.

---

## Phase 3 — hermes end-to-end on Ubuntu

Adds the **exclude list** (no native workspace dir; shares destination
root with canonical-render output).

**Entry Criteria**:
- Phase 2 merged. `wolf-i` E2E for openclaw + zeroclaw green.
- Branch `feat/760-phase-3-hermes` from main.

**Exit Criteria**:

*Code:*
- `src/clawrium/platform/registry/hermes/manifest.yaml` adds
  `features.workspace_overlay` with the full exclude list:
  `config.yaml`, `.env`, `auth.json`, `state.db`, `state.db-journal`,
  `state.db-wal`, `state.db-shm`, `sessions/`, `logs/`,
  `skills/clawrium/`.
- `src/clawrium/platform/registry/hermes/playbooks/workspace.yaml`
  + `workspace_macos.yaml` (stub) present.
- `install.py:create_agent` extended to mkdir hermes workspace
  scaffold.
- `docs/operations/sync.md` + `website/docs/operations/sync.md`
  mirror document the overlay model end-to-end now that all three
  agents are present. Stop→sync→start workflow recommendation for
  hermes `memories/` and `cron/` overlays (W14 iter-2).
- `CHANGELOG.md` `[Unreleased]` finalized with `### Added` +
  `### BREAKING` entries.
- `AGENTS.md` "Workspace Overlay" section landed — destination +
  excludes from manifest; per-agent `playbooks/workspace.yaml` is the
  only host-write path; `--workspace-only` syncs + rotates bearer;
  `become_user` does NOT re-run `setup` so `ansible_user_dir` MUST
  NOT be used in workspace-related playbooks (the B1 iter-3 lesson
  hoisted to project conventions).

*Tests:*
- Unit: U2 (hermes destination pinned), U3 (hermes excludes pinned —
  full set), U5 (hermes renderer-output-vs-exclude invariant —
  parametrized per S8), U16 (hermes excluded events), U17 (hermes
  scaffold), U22 (hermes playbook structural), U23 (hermes
  `follow: no`), U33 (skills_apply targets ⊆ hermes excludes —
  W10 iter-3).
- Integration: I3 (hermes excludes enforced, including SQLite WAL
  companions + `skills/clawrium/`), I14 (hermes configure path with
  excludes enforced), I-pair-D (hermes cell — completes the negative
  parametrization started in Phase 2).
- `make test` + `make lint` clean.

*E2E on `wolf-i`:*
- §3.3.1 provisioning for `ws-hermes` clean.
- §3.3.2 E3 matrix passes:
  - Good files (`profiles/coder/SOUL.md`, `memories/NOTES.md`) land
    correctly;
  - All hostile files (`config.yaml`, `.env`, `auth.json`, `state.db`,
    `state.db-{journal,wal,shm}`, `sessions/123.json`,
    `logs/gateway.log`, `skills/clawrium/x/SKILL.md`) surface as
    `WorkspaceExcluded` events;
  - Canonical-managed bytes on host unchanged (diff empty);
  - `agent doctor` healthy.
- §3.3.3 negative pin: `--workspace-only` against `ws-hermes` emits
  zero `gateway_token_rotated` events.
- `clawctl agent delete --yes ws-hermes` cleanup.
- E2E run captured under `.itx/760/04_E2E_hermes_wolf-i.md`.

*Process:*
- ATX review on the implementation PR rated > 3/5.
- Plan section §3.4 Definition of Done can be checked off in full.

**Dependencies**: Phase 1 + Phase 2.

**Files Affected** (Phase 3 only):
- `src/clawrium/platform/registry/hermes/manifest.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/workspace.yaml` — NEW
- `src/clawrium/platform/registry/hermes/playbooks/workspace_macos.yaml` — NEW (stub)
- `src/clawrium/core/install.py` — extend scaffold map to include hermes
- `tests/unit/core/test_workspace_sync.py` — extend (hermes rows)
- `tests/integration/test_workspace_overlay_ubuntu.py` — extend
  (hermes tests)
- `docs/operations/sync.md` — full document
- `website/docs/operations/sync.md` — mirror
- `CHANGELOG.md` — finalize entries
- `AGENTS.md` — Workspace Overlay section
- `.itx/760/04_E2E_hermes_wolf-i.md` — NEW

**Complexity**: moderate (exclude semantics are the trickiest piece;
the bulk of the docs landing here is straightforward).

**Risk callouts**:
- Hermes `skills/clawrium/` exclude (W10 iter-3) — operator dropping
  `workspace/skills/clawrium/tdd/SKILL.md` MUST be rejected. U33 +
  I3 cover this.
- SQLite WAL companion files (`state.db-{journal,wal,shm}` — W13
  iter-2) — overlaying these while the daemon holds an open
  transaction corrupts the WAL silently. Hermes E2E must include
  all three in the hostile-file fixture.
- `BREAKING` changelog entry must include explicit migration text;
  AGENTS.md release rules treat undocumented breaks as release
  blockers.

---

## Phase 4 — openclaw end-to-end on macOS (deferred)

**Entry Criteria**:
- Phase 3 merged (Ubuntu slices complete).
- `mac-test` host reachable (per AGENTS.md memory `mac_test_host`).
- Branch `feat/760-phase-4-openclaw-macos` from main.

**Exit Criteria**:
- `src/clawrium/platform/registry/openclaw/playbooks/workspace_macos.yaml`
  fleshed out (no longer the `fail:` stub).
- `playbook_resolver` routing tested for `os_family="darwin"` —
  unit test asserts macOS playbook path returned.
- Integration test: `os_family="darwin"` path through
  `sync_agent_canonical` lands files at `/Users/<name>/.openclaw/workspace/`
  with correct mode + owner.
- E2E on `mac-test` for `ws-openclaw-mac` (analogous to §3.3.2 E1
  but at `/Users/...` instead of `/home/...`).
- AGENTS.md updated to note macOS workspace overlay is GA.

**Dependencies**: Phase 3.

**Complexity**: simple (Linux playbook is the template; main delta
is the home-dir root path).

---

## Phase 5 — zeroclaw end-to-end on macOS (deferred)

**Entry Criteria**: Phase 4 merged.

**Exit Criteria**: as Phase 2's exit criteria, on `mac-test` with
`/Users/<name>/.zeroclaw/workspace/` destination. Bearer-rotation
invariant must hold identically.

**Dependencies**: Phase 4.

---

## Phase 6 — hermes end-to-end on macOS (deferred)

**Entry Criteria**: Phase 5 merged.

**Exit Criteria**: as Phase 3's exit criteria, on `mac-test` with
`/Users/<name>/.hermes/` destination and the full exclude list.

**Dependencies**: Phase 5.

---

## Out of scope (explicit non-goals)

- Workspace-overlay GUI relay (S6 iter-3): out of scope. NDJSON
  events are CLI-only this iteration.
- Hermes config-augment via YAML merge (the original issue text's
  `agent.personalities` use case): out of scope; hermes' workspace
  destination is `~/.hermes/` with `config.yaml` in the exclude list,
  so file-drop cannot reach the `config.yaml` shape needed.
- Ethos (4th registry entry): no canonical renderer in
  `lifecycle_canonical._RENDERERS`, intentionally excluded per W15
  iter-2.
- `nemoclaw` referenced in some upstream search results: not a real
  registry entry in this codebase.

## Definition of Done (aggregate)

1. Phases 1–3 merged. Each shipped one agent end-to-end on `wolf-i`
   before moving on.
2. All 35 unit tests + 18 integration tests green.
3. `make lint` + `make test` clean.
4. Three E2E run logs captured under `.itx/760/0[234]_E2E_*.md`.
5. `docs/operations/sync.md` + website mirror + `AGENTS.md` + CHANGELOG
   landed (Phase 3 finalizes these).
6. ATX review on each phase PR rated > 3/5 with all `B#` blockers
   Fixed.
7. macOS Phases 4–6 tracked as follow-ups; not blocking the Ubuntu ship.

## Prompt Log

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-06-20T00:00:00Z
**Model**: claude-opus-4-7

```prompt
760. give me plan only. dont execute or create any issues yet
```

Followup re-scaffold:

```prompt
no. wrong order. i need one agent on one os to work end to end and then move to next one
```

**Output**: 6-phase vertical-slice execution scaffold for #760 with
per-phase entry / exit criteria, dependency graph, and per-phase risk
callouts. Each phase ships one agent type on one OS end-to-end before
the next begins. Shared foundation (workspace_sync module, manifest
loader, CLI flags, install scaffold) lands in Phase 1 alongside
openclaw — the simplest agent — so the cross-cutting contracts get
stress-tested on `wolf-i` before zeroclaw's bearer-rotation invariant
and hermes' exclude semantics are layered on top. No subtask issues
created; no labels touched; no execution started.

## Prompt Log

**Stage**: scaffolding (re-invocation — workflow completion)
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-06-20T18:45:00Z
**Model**: claude-opus-4-7

```prompt
/itx:plan-scaffold 760
```

**Output**: Existing scaffold (committed in #766) re-used as-is. Posted
scaffold summary as comment on #760
([comment-4760561028](https://github.com/ric03uec/clawrium/issues/760#issuecomment-4760561028)),
added `ready` label, and created three subtask issues linked as
sub-issues of #760:

- #767 — Phase 1: openclaw workspace overlay end-to-end on Ubuntu
- #768 — Phase 2: zeroclaw workspace overlay end-to-end on Ubuntu
- #769 — Phase 3: hermes workspace overlay end-to-end on Ubuntu
- #770 — Phase 4: openclaw workspace overlay end-to-end on macOS (deferred)
- #771 — Phase 5: zeroclaw workspace overlay end-to-end on macOS (deferred)
- #772 — Phase 6: hermes workspace overlay end-to-end on macOS (deferred)

macOS Phases 4–6 filed as deferred tracking issues per user request
(will be closed if `mac-test` capacity does not materialize).

## Execute (orchestrate)

**Stage**: execution (orchestrate mode)
**Skill**: /itx:execute
**Timestamp**: 2026-06-20T18:55:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 760 orchestrate all the ubuntu tasks. run in worktrees and tell subtasks to use atx cli for reviews. go
```

**Output**: Orchestrator session `clawrium-issue-760` (tmux) spawning
Ubuntu subtasks (#767 → #768 → #769) in stacked-PR layout. macOS
subtasks (#770–#772) intentionally skipped — out of orchestrate scope.

- Worktrees: `~/workspace/ric03uec/clawrium-issue-<N>/`
- Branches: `issue-<N>-<agent>-workspace-overlay`
- PR base chain: #767 → main, #768 → issue-767-…, #769 → issue-768-…
- Children directed to use ATX **via CLI** (not MCP) per user
  directive — `atx review` invoked from inside each worktree.
- Polling cadence: 10 min (per memory `orchestrate_auto_advance`).
- Orchestrator does not touch source, does not merge, does not block.
