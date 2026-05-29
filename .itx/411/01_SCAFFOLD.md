# Issue #411 — Execution Scaffolding

**Mode**: multi-phase (7 phases), single PR

The plan in [`00_PLAN.md`](./00_PLAN.md) calls for a single bundled PR
(grammar → loader → materializer → CLI → GUI are tightly coupled and any
split forces broken intermediate states). Within that single PR, work is
sequenced into 7 phases. Each phase has an entry/exit gate so we can
verify incrementally without forcing intermediate commits to be
shippable on their own.

Phase ordering follows the foundation-first rule from the skill guide:
schemas/data → core logic → CLI → backend → frontend → tests/E2E.

---

## Phase 1: Catalog migration + schema

**Entry Criteria**
- Branch `issue-411-skill-creation` (or successor) created off latest `main`.
- Plan `.itx/411/00_PLAN.md` reviewed and merged (done).

**Exit Criteria**
- `skills/_schema/agent-skill.schema.json` exists and validates a sample
  `SKILL.md` frontmatter.
- 6 vetted skills present at `skills/vetted/<name>/SKILL.md`:
  `tdd`, `blog-author`, `daily-digest`, `docs-sync`, `issue-triage`,
  `release-watcher`.
- `skills/clawrium/`, `skills/openclaw/`, `skills/hermes/`,
  `skills/zeroclaw/`, `skills/_schema/clawrium.schema.json`,
  `skills/_schema/native/` are deleted.
- `skills/README.md` rewritten to describe the two-source model.
- `pyproject.toml` `force-include` updated to bundle
  `skills/vetted/` → `clawrium/_skills/vetted/`.
- `make lint` passes (no test changes required yet — Phase 7 owns that).

**Dependencies**: None.

**Files Affected**
- delete `skills/clawrium/`, `skills/openclaw/`, `skills/hermes/`,
  `skills/zeroclaw/`, `skills/_schema/clawrium.schema.json`,
  `skills/_schema/native/`
- create `skills/_schema/agent-skill.schema.json`
- create 6 × `skills/vetted/<name>/SKILL.md`
- modify `skills/README.md`
- modify `pyproject.toml`

**Complexity**: moderate (mechanical migration; re-authoring 6 SKILL.md
files is the main effort).

---

## Phase 2: Core refactor (loader, grammar, materializer)

**Entry Criteria**
- Phase 1 exit criteria met.

**Exit Criteria**
- `core/skills.py`:
  - `SOURCES = ("vetted", "local")`, `MissingSourcePrefix`,
    `SkillNameConflict`, `SkillNameImmutable`, `ReadOnlySource`,
    `ClawNotSupported` defined.
  - `NATIVE_REGISTRIES`, `IncompatibleSkillRegistry`,
    `MissingRegistryPrefix` removed.
  - `SUPPORTED_CLAWS_BY_DEFAULT = {"hermes": True, "openclaw": False,
    "zeroclaw": False}` defined.
  - `parse_skill_ref` accepts `<source>/<name>` only.
  - `_local_catalog_root()` returns
    `${XDG_CONFIG_HOME:-~/.config}/clawrium/skills/`.
  - `list_skills` / `load_skill` union both sources; duplicate names
    across sources raise `SkillNameConflict` at load time.
  - `materialize_for_claw(skill, claw)` consumes the new flat schema and
    raises `ClawNotSupported` for any claw where the table is `False`.
- `core/skills_apply.py` gates dispatch on `SUPPORTED_CLAWS_BY_DEFAULT`
  and skill `prerequisites`. Registry compat plumbing removed.
- `core/skills_local.py` exists with
  `create_local_skill`, `update_local_skill`, `delete_local_skill`. All
  three perform schema validation, conflict detection, atomic writes,
  and reject `name` mutation on update.
- `core/skills_state.py` `read_state` performs one-shot legacy ref
  rewrite (`clawrium/<n>` → `vetted/<n>`, `hermes/<n>` → `vetted/<n>`,
  drops unknowns with warn-log).
- `make lint` passes. Existing unit tests under
  `tests/core/test_skills*.py` may be temporarily skipped or marked
  xfail with a TODO referencing Phase 7 — do not delete.

**Dependencies**: Phase 1.

**Files Affected**
- modify `src/clawrium/core/skills.py`
- modify `src/clawrium/core/skills_apply.py`
- modify `src/clawrium/core/skills_state.py`
- create `src/clawrium/core/skills_local.py`

**Complexity**: complex (touches the chokepoint module; every other
phase depends on this shape being right).

---

## Phase 3: CLI surface

**Entry Criteria**
- Phase 2 exit criteria met.

**Exit Criteria**
- `cli/skill.py`:
  - New verbs: `add`, `edit`, `remove`.
  - `list` shows `Source` and `Supported on` columns; no `--registry`.
  - `show` renders source badge + supported-claws line.
- `cli/agent_skill.py`:
  - Parses new refs.
  - Drops `IncompatibleSkillRegistry` branches.
  - Surfaces `ClawNotSupported` cleanly on `attach`.
- `clm --help`, `clm skill --help`, `clm skill add --help`,
  `clm skill edit --help`, `clm skill remove --help`,
  `clm agent skill --help` all render without errors.
- `make lint` passes.

**Dependencies**: Phase 2.

**Files Affected**
- modify `src/clawrium/cli/skill.py`
- modify `src/clawrium/cli/agent_skill.py`

**Complexity**: moderate.

---

## Phase 4: GUI backend

**Entry Criteria**
- Phase 3 exit criteria met.

**Exit Criteria**
- `gui/routes/skills.py`:
  - `GET /api/skills` returns unioned list with `source` and
    `supported_on` per skill; no per-registry grouping.
  - `POST /api/skills` creates a local skill; 422 on schema error,
    409 on name conflict, 403 if `source != "local"`.
  - `PUT /api/skills/{name}` updates a local skill; rejects `name`
    mutation with 422; rejects vetted skills with 403.
  - `DELETE /api/skills/{name}` removes a local skill; rejects vetted
    with 403.
- All endpoints exercised via FastAPI test client in
  `tests/gui/routes/test_skills.py` (or equivalent).
- `make test` passes for new GUI route tests.

**Dependencies**: Phase 2 (uses `skills_local.py`); does not require
Phase 3.

**Files Affected**
- modify `src/clawrium/gui/routes/skills.py`
- modify/create `tests/gui/routes/test_skills.py`

**Complexity**: moderate.

---

## Phase 5: GUI frontend

**Entry Criteria**
- Phase 4 exit criteria met.

**Exit Criteria**
- `gui/src/app/skills/page.tsx`:
  - Tab bar and `REGISTRY_LABELS` removed.
  - `activeRegistry` state removed.
  - Single flat list rendered.
  - **+ Create Skill** button opens the create modal.
- `gui/src/components/skills/skill-create-form.tsx` exists; required
  fields (`name`, `description`) and optional fields render; client-side
  validation surfaces server 422s.
- `gui/src/components/skills/skill-card.tsx`: source badge +
  per-claw support badges (`hermes ✓ · openclaw ✗ · zeroclaw ✗`);
  edit/delete actions only render for `source === "local"`.
- `gui/src/components/skills/skill-detail.tsx`: supported-claws line;
  `name` field read-only in edit mode.
- `gui/src/lib/types.ts`: `SkillRegistry` removed; `SkillSource` added;
  `supported_on` added to `SkillSummary`.
- `gui/src/hooks/use-create-skill.ts`, `use-update-skill.ts`,
  `use-delete-skill.ts` exist.
- `gui` builds (`cd gui && pnpm build` or equivalent passes).
- Existing `skill-card.test.tsx` / `skill-detail.test.tsx` rewritten so
  the test suite passes; do not skip.

**Dependencies**: Phase 4.

**Files Affected**
- modify `gui/src/app/skills/page.tsx`
- create `gui/src/components/skills/skill-create-form.tsx`
- modify `gui/src/components/skills/skill-card.tsx`,
  `skill-detail.tsx`, `index.ts`
- modify `gui/src/lib/types.ts`
- create `gui/src/hooks/use-create-skill.ts`,
  `use-update-skill.ts`, `use-delete-skill.ts`
- modify `gui/src/components/skills/*.test.tsx`

**Complexity**: complex (large surface; tests + UI both move).

---

## Phase 6: Slash command + docs

**Entry Criteria**
- Phase 3 exit criteria met (depends on `clm skill add` shape only).

**Exit Criteria**
- `.claude/commands/skill-create.md` exists, asks the user for required
  fields, drafts an agentskills-format `SKILL.md` in a tmpfile, and
  shells out to `clm skill add local/<name> --from <tmpfile>`.
- Running `/skill-create test-skill` in a dev session writes a valid
  local skill (manual smoke test, not gated by `make test`).
- `docs/skills/` updated if any author-facing doc references the old
  registry model (spot-check; rewrite only what's stale).

**Dependencies**: Phase 3.

**Files Affected**
- create `.claude/commands/skill-create.md`
- modify `docs/skills/*.md` (only stale references)

**Complexity**: simple.

---

## Phase 7: Test rewrite + E2E

**Entry Criteria**
- Phases 1–6 exit criteria met.
- A real Hermes agent is reachable on the user's network (e.g. via
  `clawctl agent get`).

**Exit Criteria**
- `tests/core/test_skills*.py` rewritten; covers:
  - new ref grammar (positive + every reject path)
  - union loader + global name uniqueness
  - vetted read-only / name immutability
  - one-shot legacy ref migration in `read_state`
  - materializer per claw + `ClawNotSupported` gate
- `tests/cli/test_skill*.py` rewritten; covers:
  - `add` / `edit` / `remove` round-trip
  - `attach` against an openclaw/zeroclaw mock returns
    `ClawNotSupported`
- `tests/gui/routes/test_skills.py` covers all four CRUD endpoints.
- `gui/src/components/skills/*.test.tsx` updated for new card +
  detail shape.
- `make test` and `make lint` pass with **no** xfail / skip markers
  related to this issue.
- **AC-1 (CLI E2E)** executed against a Hermes agent:
  ```bash
  clm skill add local/e2e-cli-demo --description "E2E test skill via CLI" \
      --body-file /tmp/skill.md
  clm skill list | grep -q "local/e2e-cli-demo"
  clm skill show local/e2e-cli-demo
  clm agent skill attach local/e2e-cli-demo --agent <hermes-agent>
  clm agent skill get --agent <hermes-agent> | grep -q "local/e2e-cli-demo"
  clm agent exec <hermes-agent> -- ls ~/.hermes/skills/clawrium/ \
      | grep -q "e2e-cli-demo"
  clm agent exec <hermes-agent> -- cat \
      ~/.hermes/skills/clawrium/e2e-cli-demo/SKILL.md \
      | grep -q "E2E test skill via CLI"
  ```
  All commands exit 0. Output captured into the PR body.
- **AC-2 (GUI E2E)** executed against a Hermes agent:
  - Create `local/e2e-gui-demo` via the GUI **+ Create Skill** form.
  - Install on the Hermes agent via the agent's Skills tab.
  - `clm agent exec <hermes-agent> -- test -f
    ~/.hermes/skills/clawrium/e2e-gui-demo/SKILL.md` exits 0.
  - Screenshots or a short recording attached to the PR.
- **Negative AC**: `clm agent skill attach local/e2e-cli-demo --agent
  <openclaw-or-zeroclaw>` exits non-zero with `ClawNotSupported`; GUI
  install button disabled with tooltip on those agent types. Captured
  in PR body.

**Dependencies**: Phases 1–6.

**Files Affected**
- rewrite `tests/core/test_skills*.py`, `tests/cli/test_skill*.py`,
  `tests/gui/routes/test_skills.py`
- modify `gui/src/components/skills/*.test.tsx`

**Complexity**: complex (rewriting the most-touched test surface in the
repo + two real-host e2e runs).

---

## Cross-phase notes

- Single PR, multiple commits per phase. Each commit message names the
  phase (e.g. `phase 1: migrate vetted catalog`).
- No phase ships independently — intermediate states will have broken
  refs (e.g. after Phase 1, old `_meta.yaml`-based loaders fail).
- CI lint is the gate between phases inside the working branch.
- `make test` runs only at Phase 4 (GUI routes), Phase 5 (frontend),
  and Phase 7 (full suite). Phases 1–3 are lint-only gates.

---

## Scaffolding

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-29T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 411
```

**Output**: `.itx/411/01_SCAFFOLD.md` (this file).
