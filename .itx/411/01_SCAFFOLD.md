# Issue #411 — Execution Scaffolding

**Mode**: 3 subtasks (A core+apply, B CLI, C GUI), each its own PR.
**Supersedes**: the prior 7-phase single-PR scaffold previously committed
in this directory (see git history); replaced because the locked plan
splits work into 3 surfaces with clean handoffs.

Subtask B and Subtask C both depend on Subtask A merging first. B and C
can land in parallel afterward.

---

## Subtask A — Core + Apply

**Goal**: extend the skills catalog and apply pipeline to support a user
registry overlay and per-agent ad-hoc skills, without changing the CLI
surface.

**Entry criteria**
- `00_PLAN.md` merged on `main`.
- No open PR touching `src/clawrium/core/skills*.py`.

**Deliverables**
- `src/clawrium/core/skills.py`
  - `_catalog_root()` returns a list of roots (bundled + user overlay
    `~/.config/clawrium/skills/`).
  - `list_skills()` / `load_skill()` union both roots; overlay wins on
    collision and emits a warning log.
  - New `load_agent_skill(agent, name)` and `list_agent_skills(agent)`
    reading from `~/.config/clawrium/agents/<agent>/skills/<name>/`.
  - Per-agent local skills validated as `clawrium`-flavored (universally
    compatible) unless their `_meta.yaml.compatibility` overrides.
- `src/clawrium/core/skills_state.py`
  - `agent_skills_root(agent)` helper.
  - Decide and document the on-disk shape of agent-local entries in
    `skills.json` (default: bare name, no registry prefix).
- `src/clawrium/core/skills_apply.py`
  - Stage all skills (bundled, overlay, agent-local) into a temporary
    mirror dir that matches the existing catalog shape; invoke the
    existing playbook against the temp dir so the playbook itself
    stays source-agnostic.
- Unit tests for every new public function and every union/precedence
  path; mock the home dir via `tmp_path`.

**Exit criteria**
- `make test` and `make lint` green.
- Catalog union path covered by tests for: bundled-only, overlay-only,
  both-present (overlay wins + warning), neither (error class
  unchanged).
- `load_agent_skill` covered for: present, missing, malformed
  `_meta.yaml`.
- No public CLI or GUI behavior change yet (verified by running the
  existing `clm agent skill attach/detach` flows manually against a
  test host — must still work since this subtask doesn't remove them).
- PR description spells out the on-disk shape decision for agent-local
  entries in `skills.json`.

**Out of scope for A**
- Any CLI verb changes.
- Any GUI changes.
- Docs (covered by B).

---

## Subtask B — CLI

**Goal**: ship the new `clm agent skill add/edit/list/remove` verbs,
remove the old `attach/detach` verbs and `--agent` flag, add the
top-level `clm skill add` command, and update all user-facing docs.

**Entry criteria**
- Subtask A merged on `main`.
- `make test` green on `main`.

**Deliverables**
- `src/clawrium/cli/agent_skill.py`
  - Remove `attach`, `detach`, and the `--agent` option.
  - Add `add`, `edit`, `list`, `remove` with agent name as a required
    positional.
  - `add` input modes: `--from-template <registry>/<name>`, positional
    `PATH` (file or directory), and interactive prompt when neither is
    supplied. All three paths converge on writing
    `~/.config/clawrium/agents/<agent>/skills/<name>/`, mutating
    `skills.json`, and stopping (no host push — that's `clm agent sync`).
  - Rollback on add failure: if state mutation fails after the local
    dir is written, delete the dir before returning the error.
  - `edit` opens `$EDITOR` (or `EDITOR` env var with a sensible
    default) on the local `SKILL.md`; rewrites in place; no host push.
  - `remove` mutates state to drop the entry; keeps the on-disk dir so
    the user can `add` it back without re-authoring.
- `src/clawrium/cli/skill.py`
  - New top-level `add` command writing to
    `~/.config/clawrium/skills/<registry>/<name>/`. Accepts a positional
    `PATH` (file or dir) or runs an interactive prompt. Requires
    `--registry <clawrium|openclaw|hermes|zeroclaw>` (or prompts).
    Validates against the existing `skills/_schema/` definitions before
    writing.
- Tests: Typer `CliRunner` covering each input mode against a tmp
  `~/.config/clawrium/`; rejects schema-invalid input; rejects existing
  name without `--force`; `remove` preserves the dir; `edit` round-trips.
- Docs (all in the same PR as the CLI change):
  - `README.md` — replace the existing skill quickstart example with the
    new grammar.
  - `AGENTS.md` — update the "Skill Registry" Key Concepts section to
    describe copy-on-add semantics and the user-overlay path.
  - `CONTRIBUTING.md` — sweep for `--agent` references; update.
  - `docs/skills.md` — full guide (mental model, three input modes,
    edit, registry-level `clm skill add`, flushing via `clm agent
    sync`).
  - `website/docs/skills.md` — verbatim mirror with Docusaurus
    frontmatter + mirror-warning HTML comment.
  - `CHANGELOG.md` `[Unreleased]`:
    - `### Added` — every new verb (one bullet each), and the GUI hook
      that Subtask C will fill in.
    - `### BREAKING` — `attach`/`detach`/`--agent` removed; concrete
      before/after invocation examples; note `skills.json` state files
      remain readable.

**Exit criteria**
- `make test`, `make lint`, `make format` clean.
- `--help` output for `clm agent skill` and `clm skill` matches the
  documented surface verbatim.
- Real-host smoke test on the `mac-test` host (per memory: standing
  real-host verification target): add an agent-local skill, run `clm
  agent sync`, verify the file lands; edit + sync; remove + sync.
- Docs/website mirror invariant verified (`diff` between
  `docs/skills.md` body and `website/docs/skills.md` body is empty
  modulo the Docusaurus header).
- CHANGELOG entries reviewed for accuracy.

**Out of scope for B**
- Any GUI changes (covered by C).
- The deferred follow-ups (promote/clone, AI authoring, multi-registry).

---

## Subtask C — GUI

**Goal**: expose the same lifecycle in the web UI — list, add (three
modes), edit, remove for agent-local skills; add to user registry for
registry-level skills.

**Entry criteria**
- Subtask A merged on `main`.
- (B is not a hard dependency; C can land before or after B. If C lands
  first, GUI users get the feature before CLI breaking change ships.
  Prefer B-then-C for consistency.)

**Deliverables**
- `src/clawrium/gui/routes/skills.py` and `src/clawrium/gui/routes/agents.py`
  - Per-agent skill payload tags every entry with
    `origin: "local" | "bundled" | "overlay"`.
  - POST `/api/agents/{agent}/skills` — add. Accepts JSON describing
    the input mode (template ref / inline body / uploaded file).
  - PUT `/api/agents/{agent}/skills/{name}` — edit (replace body).
  - DELETE `/api/agents/{agent}/skills/{name}` — remove (state-only;
    keep the dir).
  - POST `/api/skills` — add to user registry overlay. Accepts JSON
    with `{registry, name, body}` or multipart for file uploads.
  - All four reject schema-invalid input with a 422 + structured error;
    rely on the same `skills/_schema/` validators the CLI uses.
- `src/clawrium/gui/frontend/...`
  - Per-agent view: new "Local skills" section listing entries with
    origin chips, Edit and Remove buttons.
  - "Add skill" modal: tabs for Template / File / Inline editor.
    Template tab pulls from `list_skills()` so users can pick from
    bundled + overlay.
  - Registry browser gains an "Add skill" entry point that calls
    `POST /api/skills`.
  - Reuse the existing whole-agent Sync control to flush; no
    skill-specific sync button.
- Tests:
  - Route-level tests with a tmp config dir (FastAPI `TestClient`).
  - Frontend smoke tests (Playwright if already in the repo, else
    component-level) for the Add Skill modal happy path.
- Docs:
  - Append a "Using the web UI" section to `docs/skills.md` covering
    the same operations.
  - Mirror update.

**Exit criteria**
- `make test`, `make lint`, `make format` clean.
- All four new HTTP endpoints have route-level tests with at least one
  happy-path and one rejection path.
- Manual GUI walkthrough on `mac-test` host: add a skill via Template,
  via File, via Inline editor; edit; remove; flush via Sync. Each step
  verified against the running agent.
- `docs/skills.md` "Using the web UI" section landed and mirrored.

**Out of scope for C**
- Any further GUI redesign of the existing skill browser beyond what
  this issue needs.

---

## Cross-cutting

- **Branching**: each subtask gets its own branch `issue-411-A-core`,
  `issue-411-B-cli`, `issue-411-C-gui`, each its own PR.
- **CHANGELOG ownership**: B owns the `### Added` and `### BREAKING`
  entries for the CLI surface. C appends a line for the GUI surface
  under `### Added`.
- **Real-host verification**: every subtask exits with a documented
  manual run against the `mac-test` host. No subtask is marked exit
  on unit tests alone.
- **Merge order**: A → B → C is the safe path. A → C → B is acceptable
  if C lands without removing the old CLI verbs first (so users have
  both surfaces during the gap).

---

<details>
<summary>Prompt Log</summary>

## Scaffolding

**Stage**: scaffold
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-06-07T06:15:24Z
**Model**: claude-opus-4-7

```prompt
wrte the plan file and stages and send pr
```

**Output**: `.itx/411/01_SCAFFOLD.md` with 3 subtask phases (A core+apply, B CLI, C GUI), entry/exit criteria for each, branching and merge-order guidance, and cross-cutting CHANGELOG ownership notes.

</details>
