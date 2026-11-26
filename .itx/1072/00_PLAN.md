# Plan — Issue #1072: Skills complete removal from CLI / core / GUI / docs

## Overview

Rip out every skills surface from Clawrium. Skills become an operator concern
on the host, outside Clawrium's control plane. Deliberately **no migration**:
leftover state on disk is ignored on next `clawctl` invocation. A single
`### BREAKING` CHANGELOG entry documents the removal.

Scope touches five areas — CLI, GUI (frontend + backend), core library +
Ansible registries, catalog + scripts + CI, and docs — so it splits into
five subtasks. They are mostly independent (each lives in its own area)
but MUST land in the listed order so the GUI frontend never ships pointing
at deleted backend routes, and so core surfaces still work when CLI/GUI
callers vanish.

## Affected Inventory (grep-verified)

### CLI (subtask 1)

- `src/clawrium/cli/clawctl/skill.py` — the `clawctl skill` Typer app
- `src/clawrium/cli/clawctl/agent/skill.py` — `clawctl agent skill`
- `src/clawrium/cli/agent_skill.py` — legacy `cli/agent.py` subgroup
- Registration call sites:
  - `src/clawrium/cli/clawctl/agent/__init__.py:125` —
    `agent_app.add_typer(_skill.skill_app, name="skill")`
  - `src/clawrium/cli/clawctl/__init__.py` docstring line 4 (noun-group list)
  - `src/clawrium/cli/__init__.py:93` — `app.add_typer(skill_app, name="skill")`
  - `src/clawrium/cli/agent.py:20,2660` — legacy `agent_skill_app` wiring
- Tests:
  - `tests/test_cli_agent_skill.py`
  - `tests/cli/clawctl/agent/test_skill.py`
  - `tests/cli/clawctl/skill/test_add.py` (and any `tests/cli/clawctl/skill/`
    siblings)

### GUI frontend (subtask 2)

- Directories to delete whole:
  - `gui/src/app/skills/` (page.tsx + test)
  - `gui/src/components/skills/` (card + detail + tests + index.ts)
- Files to delete whole:
  - `gui/src/components/agent-detail/skills-tab.tsx` + `.test.tsx`
  - `gui/src/hooks/use-skills.ts`
- Edits:
  - `gui/src/components/agent-detail/tab-nav.tsx:10` — remove
    `{ id: "skills", label: "Skills" }`
  - `gui/src/components/agent-detail/index.ts:9` — drop `SkillsTab` export
  - `gui/src/components/agent-detail/overview-tab.tsx:5,17,22,70-98` — remove
    `useAgentSkills` import, `skillsData`, `installedSkills`, and the
    entire "Installed skills" card
  - `gui/src/components/agent-detail/overview-tab.test.tsx:14` — drop the
    `useAgentSkills` mock
  - `gui/src/app/agents/page.tsx:156` — remove
    `{activeTab === "skills" && <SkillsTab …/>}` branch
  - `gui/src/hooks/index.ts:26-35` — drop the `use-skills` re-exports
  - `gui/src/lib/api.ts:276-342` — delete `getSkills`, `getSkill`,
    `getAgentSkills`, `installAgentSkill`, `removeAgentSkill`,
    `getLocalAgentSkill`, `addAgentSkill`, `editLocalAgentSkill`,
    `deleteLocalAgentSkill`, `addOverlaySkill`
  - `gui/src/lib/types.ts:411-468` — drop `SkillSummary`, `SkillsCatalog`,
    `SkillDetailData`, `AgentSkills`, `AddSkillBody`, `AddOverlaySkill*`
  - `gui/src/design-system/consumer-migration.test.ts:139` — drop the
    `src/app/skills/page.tsx` entry from the expected consumer list
  - `gui/src/components/layout/sidebar.test.tsx:78` — this already asserts
    Skills is **not** in the sidebar (the Skills tab was never added to
    the new design-system sidebar). Keep this assertion; strengthen the
    wording if the test was previously a "future-proof" placeholder.
    Also verify no live sidebar entry snuck in (`sidebar.tsx`).

### GUI backend (subtask 3)

- Delete whole: `src/clawrium/gui/routes/skills.py`
- Edits:
  - `src/clawrium/gui/server.py:25,115` — drop the `skills` import and
    `app.include_router(skills.router)`
  - `src/clawrium/gui/routes/agents.py` — strip every skills-touching
    symbol and route handler. Confirmed grep hits:
    - L64, L82 — `load_agent_skill`, `agent_skills_dir` imports from
      `clawrium.core.skills*`
    - L787, L802, L917, L949, L1096, L1155, L1194, L1277 — in-handler
      filesystem touches
    - Handlers: `list_agent_skills` (L816), `install_agent_skill`
      (L972), `remove_agent_skill` (L984), `add_agent_skill` (L1013),
      `get_local_agent_skill` (L1134), `edit_agent_skill` (L1173),
      `delete_local_agent_skill` (L1235)
    - Any Pydantic models for skill payloads defined in this file
- Tests to delete:
  - `tests/test_gui_skills_routes.py`
  - `tests/test_gui_agent_skills_routes.py`

### Core library + Ansible registries (subtask 4)

- Delete whole:
  - `src/clawrium/core/skills.py`
  - `src/clawrium/core/skills_apply.py`
  - `src/clawrium/core/skills_state.py`
  - `src/clawrium/platform/registry/hermes/playbooks/skills_apply.yaml`
  - `src/clawrium/platform/registry/openclaw/playbooks/skills_apply.yaml`
  - `src/clawrium/platform/registry/zeroclaw/playbooks/skills_apply.yaml`
  - `src/clawrium/platform/registry/ethos/playbooks/skills_apply.yaml`
- Edit call sites listed in the issue:
  - `src/clawrium/core/install.py` — L639, L793, L808 (`"skills":
    _existing_record.get("skills")`), L1596, L1801. Drop the "skills"
    key from the preserve/restore attachment capture, and the
    comment-only mentions.
  - `src/clawrium/core/lifecycle.py` — L40 (`from clawrium.core.skills_state
    import cleanup_agent_state`), L3199 (comment), L3880
    (`from clawrium.core.skills_state import state_file_path`), L4039
    (comment). Delete the `cleanup_agent_state(...)` call sites and the
    `state_file_path(...)` lookup, together with any branches gated on
    them. Agent state directory cleanup that remains (identity,
    exec-approvals, etc.) stays; only the skills-specific stanzas go.
  - `src/clawrium/core/manifest/differ.py:21` — drop `skill` from the
    `resource_kind` comment and from any dispatch/union that produces
    skill rows.
  - `src/clawrium/core/web_ui.py:127` — rewrite the docstring/comment to
    name only the modules that survive.
- Other registry refs to re-check:
  - `src/clawrium/platform/registry/openclaw/playbooks/workspace.yaml:26` —
    comment that points at `hermes/playbooks/skills_apply.yaml:27`.
    Rewrite the comment to reference a surviving file.
  - `src/clawrium/platform/registry/ethos/README.md` — strip the two
    skills paragraphs flagged by grep.
- Tests to delete:
  - `tests/test_core_skills.py`
  - `tests/test_core_skills_apply.py`
  - `tests/test_core_skills_state.py`
  - `tests/test_registry_skills_apply.py`
  - `tests/test_lifecycle.py` — not delete, but remove any assertions
    that exercise the skills branch in `cleanup_agent_state` /
    `state_file_path`. Keep the rest.

### Catalog + scripts + CI (subtask 5, part A)

- `skills/` (repo-root catalog) — delete entirely:
  `skills/_schema`, `skills/clawrium`, `skills/hermes`, `skills/openclaw`,
  `skills/zeroclaw`.
- `scripts/validate_skills.py` — delete.
- `scripts/install-skill-clawctl.sh` — this installs the **`/clawctl`
  assistant skill** (the Claude/OpenCode slash-command skill at
  `.claude/skills/clawctl/`), not an operator-facing agent skill.
  **Open question — confirm before delete:** the file name is confusing
  because of the shared "skill" word, but this is the user-adoption
  entry point for the `/clawctl` assistant command, which is unrelated
  to agent-skill management. Default recommendation: **keep**, because
  the acceptance criteria scope removal to "skills catalog, skills
  attachment, skills state, or skills documentation" — all operator-
  facing. The assistant-skill install script is out of scope. The scaffold
  phase will confirm with the operator before taking action.
- `.github/workflows/skills-validate.yml` — delete; drop any reference
  from `Makefile` if present (grep showed none in a quick pass but the
  scaffold must re-verify).
- `tests/test_validate_skills_script.py` — delete.
- `tests/test_itx_skill_harnesses.py` — this tests `/itx-*` slash-command
  skills, not agent skills. **Keep**; same reasoning as
  `install-skill-clawctl.sh`.
- `tests/test_lmwork_skill.py` — tests the `/lmstack` family skill
  (assistant-side), not agent skills. **Keep**.

### Docs (subtask 5, part B)

- Delete whole:
  - `docs/skills/` (`authoring-clawrium.md`, `authoring-native.md`,
    `index.md`, `local.md`)
  - `docs/local-skills.md`
  - `website/docs/skills/` (`intro.md`, `local.md`, `authoring.md`)
  - `website/docs/guides/local-skills.md`
- Edits:
  - `website/sidebars.ts:44-49` — drop the `Skills` section and its
    three entries
  - `README.md:96-101` — rewrite the `clawctl gui` tab list to omit
    "Skills" and remove the two sentences about the Skills catalog
  - `docs/installation.md:89,263` — remove the `skill` row from the
    help-text box and the hermes "skills_hub" aside
  - `website/docs/installation.md` — mirror the docs/installation.md
    edit verbatim per the AGENTS.md mirroring contract
  - `docs/agent-onboarding.md`, `docs/index.md` — strip any skills
    references (grep passes in scaffold phase)
- `CHANGELOG.md [Unreleased]` — add under `### BREAKING`:

  > Removed the Clawrium skills subsystem — `clawctl skill`,
  > `clawctl agent skill`, the GUI **Skills** tab, every `src/clawrium/core/skills*.py`
  > module, every per-claw `skills_apply.yaml` playbook, the `skills/`
  > catalog, the `docs/skills/` documentation tree, and the related
  > tests. No migration runs — any skills state left under
  > `~/.config/clawrium/agents/<name>/skills*` is ignored by the
  > upgraded `clawctl` and can be manually removed at the operator's
  > discretion. Operators who relied on managed skills reapply them
  > directly on the host.

## Steps

Execute subtasks 1 → 5 in order. Within each subtask:

1. Delete the whole-delete files.
2. Apply the per-file edits.
3. Delete the matching tests (or trim them where listed).
4. Run `make lint && make test` — must pass before marking the
   subtask done.
5. Commit on the subtask branch.

After subtask 5 lands, run the DoD grep sweep (next section) on `main`.

## Definition of Done (grep gates)

The scaffold phase MUST end with these greps returning **zero hits**:

```bash
# Python surface
rg -n '\bskills_apply\b|\bskills_state\b|\bagent_skills_dir\b|\bload_agent_skill\b|\bcleanup_agent_state\b' src/ tests/ --iglob '!**/__pycache__/**'

# CLI command surface
rg -n '\bclawctl skill\b|\bagent skill\b|\bagent_skill_app\b|\bskill_app\b' src/ tests/ docs/ website/

# GUI frontend surface
rg -n 'use-?[Ss]kill|SkillsTab|SkillCatalog|SkillSummary|SkillDetailData' gui/src/

# Catalog + ansible
rg -n 'skills_apply' src/clawrium/platform/registry/
test ! -d skills/
```

Allowed residual hits: the assistant-skill script and its tests
(`scripts/install-skill-clawctl.sh`, `tests/test_itx_skill_harnesses.py`,
`tests/test_lmwork_skill.py`), release archives under
`docs/releases/` (frozen history), and the CHANGELOG BREAKING entry
itself. Everything else is a planning bug.

## Test Strategy

- Unit — delete the skills-dedicated test files. For `test_lifecycle.py`
  and the GUI route test suites that have **mixed** coverage, trim only
  the skills assertions. Every affected test file must still exit 0.
- Lint — `make lint` must pass end-to-end. Dead imports are an easy
  miss; ruff will catch them.
- GUI build — `cd gui && npm run build && npm run test` must pass.
  The `consumer-migration.test.ts` snapshot and the agent-detail tab
  tests are the two most likely breakage points.
- Real-host UAT (per memory `feedback_no_pr_without_real_host_uat.md`):
  on a single host, upgrade the controller to the branch build,
  run `clawctl agent sync <name>` on an agent that previously had
  skills attached (e.g. an openclaw with `clawrium/tdd`), confirm the
  sync succeeds, confirm no crash on the stale `agents/<name>/skills.json`,
  confirm the GUI loads without a Skills tab, confirm
  `clawctl skill --help` and `clawctl agent skill --help` both exit
  with a "No such command" error. Record host + evidence in the final
  PR body.

## Risks

- **Core call-site drift**: `lifecycle.py` and `install.py` both
  reference skills in attachment-restore paths (issue #816 memory).
  The CLAUDE.md note on #816 warns explicitly that
  attachment-restoration code is load-bearing — dropping the `"skills"`
  key from `_existing_record.get(...)` is safe, but the surrounding
  loop MUST stay intact. Verify by running the issue-#816 regression
  path on a real host.
- **Ethos registry**: the `ethos` claw ships a `skills_apply.yaml`.
  Grep hits in its README confirm skills are a documented surface
  there. Check whether `ethos` is in the active agent-type matrix
  before deletion — if yes, delete the playbook AND the matching
  dispatch entry in whatever module wires ethos' sync.
- **Stacked-PR merge timing** (per memory
  `feedback_stacked_pr_merge_timing.md`): five subtasks landing in
  order may strand bases on GitHub. Prefer landing each subtask
  directly to `main` with a rebase between, rather than stacking
  five PRs against each other.
- **Assistant-skill name overlap**: the Clawrium `/clawctl` assistant
  skill is NOT in scope but shares the word. Confirm with operator at
  scaffold time (scope note is already captured in subtask 5, part A).

## Subtasks

Five subtasks, ordered. Each is sized to one working session and ends
on a passing `make lint && make test`.

- Subtask A — CLI removal (`clawctl skill`, `clawctl agent skill`,
  legacy `cli/agent_skill.py`, registrations, 3 test files)
- Subtask B — GUI frontend removal (Skills tab, Skills page,
  components/skills, hooks, api.ts/types.ts entries, agent-detail
  overview card, consumer-migration snapshot, tab-nav entry,
  sidebar assertion)
- Subtask C — GUI backend removal (`gui/routes/skills.py`,
  `gui/server.py` registration, all skill handlers in
  `gui/routes/agents.py`, 2 test files)
- Subtask D — Core + Ansible removal (3 core modules, 4 registry
  `skills_apply.yaml` playbooks, call-site edits in `install.py`,
  `lifecycle.py`, `manifest/differ.py`, `web_ui.py`, ethos README,
  trim `test_lifecycle.py`, delete 4 core test files)
- Subtask E — Catalog, scripts, CI, and docs (delete `skills/`,
  `scripts/validate_skills.py`, `tests/test_validate_skills_script.py`,
  `.github/workflows/skills-validate.yml`, all doc dirs, update
  README/installation/sidebars, add BREAKING entry; confirm
  `install-skill-clawctl.sh` stays)

---

## Prompt Log

### Stage: planning

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-11-26T08:58:00Z
**Model**: claude-opus-4-7

```prompt
plan 1072
```

**Output**: `.itx/1072/00_PLAN.md` + GitHub comment on issue #1072 + five
sub-issue links.
