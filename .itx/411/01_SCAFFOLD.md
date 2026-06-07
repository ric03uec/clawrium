# Issue #411 — Execution Scaffolding

**Mode**: 3 subtasks (A safe core helpers, B semantic switch + CLI,
C GUI), each its own PR.

**Merge order**: A → B → C **strict**. B and C cannot run in parallel
— C's frontend strings reference the new CLI verbs in help text and
would document removed verbs otherwise.

---

## Subtask A — Core Helpers + Format Validation

**Goal**: add safe catalog overlay helpers and reusable per-agent
format validation/materialization helpers without changing the current
desired-state semantics or any CLI/GUI surface.

**Entry criteria**
- `.itx/411/00_PLAN.md` merged on `main`.
- No open PR touching `src/clawrium/core/skills*.py`.

**Deliverables**
- `src/clawrium/core/skills.py`
  - Add `_overlay_root() -> Path` returning
    `${XDG_CONFIG_HOME:-~/.config}/clawrium/skills/`. Use the same
    `get_config_dir()` helper `skills_apply.py` already uses for
    `staging/` and `logs/`.
  - Add `_catalog_roots() -> list[tuple[str, Path]]` returning
    `[("bundled", bundled)]` plus `("overlay", overlay)` when the
    overlay dir exists.
  - Keep `_catalog_root() -> Path` unchanged (bundled only). Used
    by `_load_schema` and `_bare_name_hint`. **Do not change its
    signature** — that would fan out to schema resolution and the
    bare-name hint path with no benefit.
  - Rewrite `list_skills` to iterate `_catalog_roots()` and dedupe
    on `<registry>/<name>`. Overlay wins on collision; emit a
    `logger.warning` (once per `(registry, name)` per process).
  - Rewrite `load_skill` to try overlay first, fall back to bundled.
  - Add `load_agent_skill(agent: str, name: str, agent_type: str) -> Skill`.
    Per-agent skills are already materialized for their target agent,
    so the returned `Skill.ref.registry` is the concrete agent type
    (`hermes`, `openclaw`, or `zeroclaw`) and validation uses
    `_schema/native/<agent_type>.schema.json`.
  - Add `list_agent_skills(agent: str) -> list[str]` returning
    sorted bare names; empty list if dir absent.
  - Expose reusable add-time materialization helper if needed, but do
    not leave materialization in the sync/apply path.
  - **Do not change** `parse_skill_ref`. Agent-local lookups go
    through `load_agent_skill(agent, name, agent_type)` directly; they never
    flow through `parse_skill_ref`.

- `src/clawrium/core/skills_state.py`
  - Add `agent_skills_dir(agent: str) -> Path` returning
    `~/.config/clawrium/agents/<agent>/skills/`. This is the on-disk
    bytes dir, distinct from `state_file_path` (which points at
    `skills.json`).
  - Do **not** change `skills.json` parsing semantics in A. The current
    registry-ref state file format must continue working until B lands
    the new CLI and the semantic switch together.

- Tests:
  - Catalog union and overlay precedence.
  - Agent-native schema validation for hermes/openclaw/zeroclaw sample
    `SKILL.md` files.
  - Add-time materialization helper converts `clawrium/tdd` into valid
    native frontmatter for each supported agent type.

**Exit criteria**
- `make test` and `make lint` green.
- Catalog union path covered for: bundled-only, overlay-only,
  both-present (overlay wins + warning), neither (existing
  `SkillNotFound` raised — error class unchanged).
- Materialization helper covered for `hermes`, `openclaw`, and
  `zeroclaw`; each result validates against that agent's native schema.
- **No public CLI or GUI behavior change yet** — existing
  `clawctl agent skill attach/detach/get` flows continue to work.

**Out of scope for A**
- Changing `skills.json` to bare-name-only desired state.
- Changing `apply_state` staging behavior.
- Any CLI verb changes.
- Any GUI route or frontend changes.
- Docs (covered by B).

---

## Subtask B — Desired State Switch + CLI + Docs

**Goal**: switch desired state to bare per-agent local names, make
sync/apply copy already-native local files as-is, ship the new
`clawctl agent skill add/edit/list/remove` verbs, remove old verbs,
add top-level `clawctl skill add`, and update docs.

**Entry criteria**
- Subtask A merged on `main`.
- `make test` green on `main`.

**Deliverables**
- `src/clawrium/core/skills_state.py`
  - `skills.json` shape stays a flat list of strings, but every entry
    is a bare per-agent local skill name (e.g. `"tdd"`). Registry refs
    (`"<registry>/<name>"`) are invalid desired state. Document this
    in the module docstring.
  - `read_state` / `write_state` / `add_skill` / `remove_skill`
    validate safe bare names and reject any value containing `/`.
  - Old state files containing registry refs fail with a clear
    operator message to re-add those skills from template. Do not
    silently copy templates during sync.

- `src/clawrium/core/skills_apply.py`
  - In `apply_state`'s read loop (currently lines 169–176), treat
    every `raw_ref` as a bare local skill name and call
    `load_agent_skill(agent_name, raw_ref, agent_type)`. Do not parse
    registry refs and do not load bundled/overlay catalog skills.
  - `_stage_skills` keeps the current `<staging>/<name>/SKILL.md`
    shape, but it copies the local already-agent-native `SKILL.md`
    bytes unchanged. Remove the sync-time `materialize_for_claw` call.
  - Playbooks remain unchanged because they already consume a staging
    dir plus `desired_skill_names` as bare names.

- Unit tests for every new function and every union/precedence
  path; mock the home dir via `tmp_path` + `monkeypatch.setenv` on
  `XDG_CONFIG_HOME`.
  Add explicit tests that sync stages exactly the local `SKILL.md`
  bytes and does not perform materialization.
- `src/clawrium/cli/clawctl/agent/skill.py` (REPLACE existing
  verbs; do **not** edit `src/clawrium/cli/agent_skill.py` — that's
  the `clm` legacy surface and is out of scope)
  - Remove `attach`, `detach`, `get`, and every `--agent` option.
  - Add `list`, `add`, `edit`, `remove`. Agent name is a required
    positional first arg.
  - `add` input modes (mutually exclusive):
    - `--from-template <registry>/<name>` — copy bytes from
      bundled-or-overlay catalog, materialized for the target agent
      type, into the agent's local dir.
    - Positional `PATH` — file (a single `SKILL.md`) or directory
      (full skill tree). Validate the input, materialize it for the
      target agent type if needed, then persist native `SKILL.md`.
    - Neither — open `$EDITOR` (or `EDITOR` env var; fall back to
      `vi`) on a stub native `SKILL.md`, persist on save.
  - `add` resolves the agent first to determine `agent_type`. It
    validates the input and the final materialized local `SKILL.md`
    against `_schema/native/<agent_type>.schema.json` before touching
    `skills.json`. On failure: nothing is written.
  - `add` has no `--force`. If `skills/<name>/` already exists or
    `skills.json` already contains `<name>`, fail and tell the user to
    remove or rename the existing skill first.
  - `add` rollback: if `add_skill` fails after the local dir is
    written, delete the dir before returning the error. Symmetric
    to the existing preflight → mutate → apply pattern at lines
    97–121 of the pre-change file.
  - `add` does **not** call `apply_state`. CLI exits after the
    state file is mutated. Use `clawctl agent sync <agent>` to
    flush.
  - `edit` opens `$EDITOR` on the already-agent-native local
    `SKILL.md`; re-validates against the target agent's native schema
    on save; rejects schema-invalid writes (restoring prior bytes).
  - `remove` accepts only a bare local name; drops the matching
    `skills.json` entry and deletes the local dir.

- `src/clawrium/cli/clawctl/skill.py` (ADD top-level command; do
  **not** edit `src/clawrium/cli/skill.py` — that's `clm` legacy)
  - New `add` command writing to
    `~/.config/clawrium/skills/<registry>/<name>/`. Accepts
    positional `PATH` (file or dir) or `--interactive` to launch
    `$EDITOR`. Requires
    `--registry <clawrium|hermes|openclaw|zeroclaw>` (or prompts
    in interactive mode).
  - Validates against existing per-registry schemas before writing
    (`validate_skill` after loading the staged copy).
  - No `--force`: existing overlay registry/name fails; user must
    remove or rename first.
  - Mount `add` directly on `skill_app`, not under `registry`,
    mirroring issue #411's "add to local registry" framing.
  - `skill_app.add_typer(skill_registry_app, name="registry")`
    wiring (current line 178) is unchanged; the existing
    `skill registry get`/`describe` verbs automatically include
    overlay entries via the changed `list_skills`/`load_skill`
    from Subtask A.

- Tests (Typer `CliRunner`, tmp `$XDG_CONFIG_HOME` via
  `monkeypatch`):
  - Each `add` input mode against the tmp overlay/local dirs.
  - `agent skill add --from-template clawrium/tdd` covered for each
    supported agent type (`hermes`, `openclaw`, `zeroclaw`). Each test
    asserts the persisted local `SKILL.md` validates against that
    agent's native schema before the state file is written.
  - Sync/apply test confirms staged bytes equal the already-native
    local bytes for each supported agent type; no sync-time
    materialization.
  - Rejects schema-invalid input with a non-zero exit.
  - Rejects existing agent-local names and existing overlay
    registry/name collisions; there is no `--force` path.
  - `remove` drops state and deletes the local dir (only for bare
    names).
  - `edit` round-trips (use `EDITOR=true` plus a pre-written stub
    file the editor "saves").
  - Removed verbs (`attach`/`detach`/`get`, `--agent` flag) exit
    non-zero with a clear "removed — use `…` instead" message.

- Docs (all in the same PR as the CLI change):
  - `docs/skills/index.md` — replace the existing skill quickstart
    example on line 33 and the troubleshooting examples on lines
    148/182/191/195/198 with the new grammar.
  - `docs/skills/authoring-clawrium.md` — update the
    `attach <openclaw|hermes|zeroclaw>-agent` examples on lines
    136–138.
  - `docs/skills/local.md` (NEW) — canonical guide for per-agent
    local skills and the user overlay. Sections:
    - Mental model (the three-source table from `00_PLAN.md`).
    - Three input modes for `clawctl agent skill add`.
    - Editing an on-agent skill (`clawctl agent skill edit`).
    - Adding to the user overlay (`clawctl skill add`).
    - Flushing via `clawctl agent sync <agent>`.
    - Note that schemas live in the bundled tree only — the
      overlay cannot redefine schemas.
  - `website/docs/skills/local.md` (NEW) — verbatim mirror with
    Docusaurus frontmatter + mirror-warning HTML comment, matching
    the per-file pattern in `website/docs/skills/`.
  - `README.md` — only update if the quickstart skill example
    changes (it does — current line referencing `attach`).
  - `AGENTS.md` — update the "Skill Registry" Key Concepts section
    (currently the `Skill Registry` paragraph + the line-50 example
    `clawctl agent skill attach clawrium/tdd --agent <agent-name>`).
  - `CONTRIBUTING.md` — sweep for `--agent` references and the old
    verb names.
  - `CHANGELOG.md` `[Unreleased]`:
    - `### Added` — `clawctl agent skill add/edit/list/remove`,
      `clawctl skill add`, GUI Add Skill flow (C will fill in
      detail when it lands).
    - `### BREAKING` — `clawctl agent skill attach/detach/get`
      removed; `--agent` flag removed across `clawctl agent skill`.
      Concrete before/after invocations. Note old `skills.json`
      entries containing registry refs are no longer valid desired
      state; re-add from template to create per-agent native local
      copies.

**Exit criteria**
- `make test`, `make lint`, `make format` clean.
- `--help` output for `clawctl agent skill` and `clawctl skill`
  matches the documented surface verbatim.
- Real-host smoke test on `mac-test`:
  1. `clawctl agent skill add <agent> --from-template clawrium/tdd`
  2. `clawctl agent sync <agent>` → verify file lands on host.
  3. `clawctl agent skill edit <agent> tdd` → small edit →
     `sync` → verify host content changes.
  4. `clawctl agent skill remove <agent> tdd` → `sync` → verify
     host removes the file.
  5. `clawctl skill add ./tmpdir --registry clawrium` → verify
     `clawctl skill registry get` lists it with overlay origin.
- Docs/website mirror invariant: `diff` between
  `docs/skills/local.md` body and `website/docs/skills/local.md`
  body is empty modulo the Docusaurus header.
- CHANGELOG `### BREAKING` entry contains the explicit
  before/after invocations table.

**Out of scope for B**
- Any GUI changes (covered by C).
- The deferred follow-ups (AI authoring, promote/clone,
  multi-registry).
- The `clm` legacy CLI surface (`src/clawrium/cli/skill.py`,
  `src/clawrium/cli/agent_skill.py`) — untouched.

---

## Subtask C — GUI

**Goal**: expose the same lifecycle in the web UI — list, add
(three modes), edit, remove for per-agent local skills; add to user
overlay for registry-level skills.

**Entry criteria**
- Subtask B merged on `main` (strict — frontend strings reference
  the new CLI verbs).
- `make test` green on `main`.

**Deliverables**
- `src/clawrium/gui/routes/agents.py` (per-agent skill routes
  already live here at lines 401/530/543; this file owns per-agent
  skill routes — **not** `routes/skills.py`)
  - Extend `GET /{agent_key}/skills` (line 401) to tag each entry
    with `origin: "local" | "bundled" | "overlay"`.
  - Existing `POST /{agent_key}/skills/{registry}/{skill}` (line
    530) and `DELETE /{agent_key}/skills/{registry}/{skill}` (line
    543) continue only as compatibility routes. Template add must
    materialize/copy into the agent-local dir and write a bare name to
    `skills.json`; it must not persist `<registry>/<skill>` as
    installed state. Registry-ref delete should be deprecated or routed
    to local bare-name removal.
  - **New** `POST /{agent_key}/skills` (no path segments after
    `/skills`). Body: `{input_mode: "template"|"file"|"inline",
    ...payload}`. Writes a per-agent local skill.
  - **New** `PUT /{agent_key}/skills/local/{name}` — replace the
    body of a per-agent local skill. Validate against the target
    agent's native schema; do not run normalized materialization on
    edit. The `local/` prefix disambiguates from the
    `{registry}/{skill}` route (FastAPI dispatches more-specific routes
    first, but the explicit `local/` makes the dispatch unambiguous).
  - **New** `DELETE /{agent_key}/skills/local/{name}` — remove a
    per-agent local skill (state + dir).

- `src/clawrium/gui/routes/skills.py` (catalog-level routes; the
  read-only routes already live here)
  - `GET /api/skills` continues to enumerate the catalog; overlay
    entries appear automatically via the changed `list_skills`.
  - **New** `POST /api/skills` — write to user overlay. Accepts
    JSON `{registry, name, body, meta}` or multipart for file
    uploads. Validates against the per-registry schema; rejects
    422 on schema failure.

- `src/clawrium/gui/frontend/...`
  - Per-agent view: new "Local skills" section listing entries
    with origin chips. Edit / Remove buttons per row.
  - Add Skill modal: tabs for Template / File / Inline editor.
    Template tab pulls from `GET /api/skills` (bundled + overlay).
  - Registry browser gains an "Add skill" entry point that calls
    `POST /api/skills`.
  - Reuse the existing whole-agent Sync control; no new
    skill-specific sync button.

- Tests:
  - Route-level (FastAPI `TestClient`) for all five new endpoints
    above. Each has at least one happy-path and one rejection-path
    test.
  - Routes-test asserting `registry == "local"` always dispatches
    to the local handler (the disambiguation guard).
  - Frontend: Playwright happy-path for the Add Skill modal if
    Playwright is already in the repo; otherwise component-level
    tests for the modal's three tabs.

- Docs:
  - Append a "Using the web UI" section to `docs/skills/local.md`.
  - Mirror to `website/docs/skills/local.md`.
  - `CHANGELOG.md` `[Unreleased]` `### Added` — append the GUI
    surface (one bullet).

**Exit criteria**
- `make test`, `make lint`, `make format` clean.
- All five new HTTP endpoints covered by happy-path + rejection
  tests.
- Manual GUI walkthrough on `mac-test`:
  1. Add a per-agent local skill via Template tab.
  2. Add another via File tab.
  3. Add a third via Inline editor.
  4. Edit one of them in place.
  5. Remove one of them.
  6. Flush via the agent's Sync control; verify each step on the
     running agent.
  7. Add an overlay skill via the registry browser's "Add skill";
     verify it appears in `GET /api/skills` with origin
     `"overlay"`.
- `docs/skills/local.md` "Using the web UI" section landed and
  mirrored.

**Out of scope for C**
- Any further GUI redesign of the existing skill browser beyond
  what this issue needs.
- The deferred follow-ups (AI authoring, promote/clone,
  multi-registry).

---

## Cross-cutting

- **Branching**: each subtask gets its own branch
  `issue-411-A-core`, `issue-411-B-cli`, `issue-411-C-gui`. One PR
  per branch.
- **CHANGELOG ownership**: B owns the initial `### Added` and
  `### BREAKING` entries for the CLI surface. C appends a line
  under `### Added` for the GUI surface.
- **Real-host verification**: every subtask exits with a documented
  manual run against `mac-test`. No subtask is marked exit on unit
  tests alone.
- **Merge order**: A → B → C strict.
- **Legacy `clm` surface untouched**: `src/clawrium/cli/skill.py`
  and `src/clawrium/cli/agent_skill.py` are part of the `clm`
  legacy CLI. Do not edit them in any subtask.

---

<details>
<summary>Prompt Log</summary>

## Scaffolding

**Stage**: scaffold
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-06-07T17:43:41Z
**Model**: claude-opus-4-7

```prompt
ive closed the pr now. redo the plan end to end
```

**Output**: `.itx/411/01_SCAFFOLD.md` rewritten from scratch into 3 subtask phases (A core+apply, B CLI, C GUI), entry/exit criteria for each, branching and merge-order guidance, cross-cutting CHANGELOG ownership notes.

## Scaffolding (review-driven rewrite)

**Stage**: scaffold
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-06-07T18:30:00Z
**Model**: claude-opus-4-7

```prompt
redo the full plan with this feedback. get rid of all old instruciotns
```

**Output**: `.itx/411/01_SCAFFOLD.md` rewritten end-to-end alongside `00_PLAN.md`. Subtask A pinned to additive helper (`_catalog_roots()`) instead of changing `_catalog_root` signature; staging shape change confirmed unnecessary (existing `_stage_skills` already bare-name). Subtask B targets `cli/clawctl/agent/skill.py` and `cli/clawctl/skill.py` explicitly (legacy `cli/agent_skill.py` / `cli/skill.py` called out as out of scope). Subtask C targets `gui/routes/agents.py` (which owns per-agent skill routes) plus catalog-level `gui/routes/skills.py`; route shape `/{agent_key}/skills/local/{name}` introduced to disambiguate from existing `/{agent_key}/skills/{registry}/{skill}`. Merge order tightened from "B then C preferred" to "A → B → C strict."

## Scaffolding (add-time materialization rewrite)

**Stage**: scaffold
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-06-07T21:20:27Z
**Model**: openai/gpt-5.5

```prompt
update the plan. also update the /add explicit tests to validate the skills format for each supported agent first and then copy the  akikks in right format. do a research and create a plan for each agent type thats supported

materiillzation should ahappen at the add time, not at the sync time. sync should movest apply the skillss as -is without any changes to the agent specific converntions
```

**Output**: Updated scaffold so Subtask A is safe core helper/format validation work only, while Subtask B lands the desired-state semantic switch with the new CLI in the same PR. Added explicit per-agent add tests for hermes/openclaw/zeroclaw, sync-time byte-preservation tests, bare-name-only `skills.json`, and no-force collision handling.

</details>
