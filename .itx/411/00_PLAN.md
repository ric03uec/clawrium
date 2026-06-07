# Plan — #411 Allow adding ad-hoc skills to agents

**Issue**: https://github.com/ric03uec/clawrium/issues/411
**Complexity**: M
**Status**: planned

## Overview

Today the only way to add a skill to a clawrium-managed agent is to
reference the bundled in-repo catalog under `skills/<registry>/<name>/`
via `clawctl agent skill attach`. This plan adds two new write paths
while leaving the bundled catalog exactly as it is on `main`:

1. **Per-agent local skills.** A user can add a skill to a specific
   agent — interactively, from a local file, from a local directory,
   or by copying from the bundled (or user-overlay) catalog. The skill
   is copied into the agent's own clawrium config directory, and from
   that point that copy is the source of truth and is fully editable.
2. **User registry overlay.** A user can publish a new skill into a
   user-owned overlay that mirrors the four bundled registries
   (`clawrium` / `hermes` / `openclaw` / `zeroclaw`). The overlay is a
   second writable root that appears alongside the bundled catalog in
   `list_skills`/`load_skill`.

The bundled `skills/` tree stops being the only on-agent source.
When an agent skill is added from a template, the bytes are copied
into the agent's local skill directory; that copy is then independent.

The four bundled registries (`clawrium/`, `hermes/`, `openclaw/`,
`zeroclaw/`) and `_schema/` under `skills/` stay exactly as they are
on `main`. No restructuring.

This plan targets the `clawctl` CLI surface only. The legacy `clm`
CLI (`src/clawrium/cli/skill.py`, `src/clawrium/cli/agent_skill.py`)
is **out of scope** and is left untouched.

## Conceptual model

| Concept | Where it lives | Mutable by user? |
|---|---|---|
| Bundled registry skill | repo `skills/<registry>/<name>/`; bundled into the wheel as `clawrium/_skills/<registry>/<name>/` (see `core/skills.py:_catalog_root`) | No (read-only) |
| User registry overlay skill (`clawctl skill add`) | `~/.config/clawrium/skills/<registry>/<name>/` | Yes |
| Per-agent local skill (`clawctl agent skill add`) | `~/.config/clawrium/agents/<agent>/skills/<name>/` | Yes |

`<registry>` is one of `clawrium`, `hermes`, `openclaw`, `zeroclaw`
(the existing four-registry namespace; see `core/skills.py:REGISTRIES`).
The user overlay is a second writeable root with the same shape as
the bundled tree.

Per-agent local skills live under the agent's own config directory.
They are not addressable by a `<registry>/<name>` ref because the
namespace is implicit — they belong to exactly one agent. State file
entries are bare names only (no `/` separator). A registry skill is
only a template source during `clawctl agent skill add`; after the
copy, the per-agent skill has no lifecycle connection to the registry
entry. Optional source metadata is informational only.

**Materialization boundary (locked):** `clawctl agent skill add` is
the only place that converts a template or user-provided skill into
the target agent's native skill format. `clawctl agent sync <agent>`
does not transform skill formats; it applies the already-materialized
per-agent `SKILL.md` files as-is according to that agent type's host
conventions.

The `skills/_schema/` schemas (bundled only, never overlaid) gate all
sources. `_schema/clawrium.schema.json` validates normalized template
sources. `_schema/native/<claw>.schema.json` validates native overlay
sources and every per-agent local skill after add-time materialization.

Stage / flush model: add/edit/remove commands only mutate local
control-plane state. The single host-side flush is the existing
`clawctl agent sync <name>` command (which calls `apply_state`).
There is no new skill-specific sync verb. Sync copies/prunes the
already-agent-native local skill files; it does not re-render them.

## Supported Agent Format Plan

Research source of truth:

| Agent type | Existing schema | Host convention | Add-time plan | Sync-time plan |
|---|---|---|---|---|
| `hermes` | `skills/_schema/native/hermes.schema.json`; native `SKILL.md` frontmatter requires `name` + `description`, allows extra metadata | Playbook installs to `/home/<agent>/.hermes/skills/clawrium/<name>/SKILL.md` | Resolve target agent type, load template/input, materialize to hermes-native `SKILL.md`, validate against hermes schema, write `~/.config/clawrium/agents/<agent>/skills/<name>/SKILL.md` | Copy that exact local `SKILL.md` into staging unchanged; playbook installs it under hermes' `clawrium` skill category |
| `openclaw` | `skills/_schema/native/openclaw.schema.json`; native `SKILL.md` frontmatter requires `name` + `description` | Playbook installs to `/home/<agent>/.openclaw/skills/<name>/SKILL.md` | Materialize/validate to openclaw-native `SKILL.md` at add time, then store only the native local file | Copy staged local bytes unchanged; playbook syncs into openclaw skill dir |
| `zeroclaw` | `skills/_schema/native/zeroclaw.schema.json`; native `SKILL.md` frontmatter requires `name` + `description` | Playbook stages `<name>/SKILL.md` and invokes `zeroclaw skills install` | Materialize/validate to zeroclaw-native `SKILL.md` at add time, then store only the native local file | Copy staged local dir unchanged; playbook runs zeroclaw's installer against the staged native skill dir |

Unsupported agent types fail before add because Clawrium cannot know
which native format to persist.

## CLI surface

Active surface — `src/clawrium/cli/clawctl/agent/skill.py`:

```
clawctl agent skill list   <agent>
clawctl agent skill add    <agent> [PATH | --from-template <registry>/<name>] [--name <slug>]
clawctl agent skill edit   <agent> <skill-name>
clawctl agent skill remove <agent> <skill-name>
```

The existing verbs in that file are **removed** as a BREAKING change:

| Old | New |
|---|---|
| `clawctl agent skill attach <ref> --agent <a>` | `clawctl agent skill add <a> --from-template <ref>` |
| `clawctl agent skill detach <ref> --agent <a>` | `clawctl agent skill remove <a> <skill-name>` |
| `clawctl agent skill get --agent <a>` | `clawctl agent skill list <a>` |

Agent name becomes a required positional everywhere, matching
`clawctl agent configure <name>` / `clawctl agent sync <name>`. The
`--agent` flag is removed.

New top-level command — `src/clawrium/cli/clawctl/skill.py`:

```
clawctl skill add [PATH | --interactive] \
                  --registry <clawrium|hermes|openclaw|zeroclaw> \
                  [--name <slug>]
```

Writes to `~/.config/clawrium/skills/<registry>/<name>/`. Validates
against the per-registry schema before writing. There is no `--force`;
if an overlay skill already exists at that registry/name, the user must
remove or rename it first. Existing `clawctl skill registry get` /
`describe` verbs are extended to include overlay entries (they share
`list_skills`/`load_skill` below).

`clawctl skill list` (in `cli/clawctl/skill.py` if present, else
introduced) unions bundled + overlay and tags origin.

## Files to modify

### Core
- `src/clawrium/core/skills.py`
  - Add `_overlay_root() -> Path` returning
    `${XDG_CONFIG_HOME:-~/.config}/clawrium/skills/`.
  - Add `_catalog_roots() -> list[tuple[str, Path]]` returning
    `[("bundled", bundled), ("overlay", overlay)]`, where `overlay`
    is only included if it `is_dir()`.
  - Keep `_catalog_root() -> Path` (bundled only) — used by
    `_load_schema` and `_bare_name_hint`. **Do not change its
    signature.** Adding a sibling helper is cheaper than fanning out
    a return-type change through every existing caller.
  - Rewrite `list_skills` to iterate `_catalog_roots()` and dedupe
    on `<registry>/<name>`. Overlay wins on collision; emit a
    `logger.warning` once per collision per process.
  - Rewrite `load_skill` to try overlay first, then bundled.
  - Add `load_agent_skill(agent: str, name: str, agent_type: str) -> Skill`
    and `list_agent_skills(agent: str) -> list[str]`, reading from
    `~/.config/clawrium/agents/<agent>/skills/<name>/`. Agent-local
    skills are already materialized for the target `agent_type`, so
    they validate against `_schema/native/<agent_type>.schema.json`.
    The returned `Skill.ref.registry` should be the concrete agent type
    (`hermes`, `openclaw`, or `zeroclaw`), not a synthetic `local`
    registry, so existing native schema validation can be reused.
  - Add `materialize_skill_for_agent(skill: Skill, agent_type: str) -> tuple[dict, str]`
    only if needed as a public wrapper around the current
    `materialize_for_claw` logic. The important invariant is call-site
    placement: CLI/GUI add paths call it before persisting the
    per-agent skill; sync/apply does not call it.
  - `parse_skill_ref` is **unchanged**. Bare names continue to raise
    `MissingRegistryPrefix`. Agent-local lookups go through the new
    `load_agent_skill(agent, name, agent_type)` API; they never flow through
    `parse_skill_ref`.

- `src/clawrium/core/skills_state.py`
  - Add `agent_skills_dir(agent: str) -> Path` returning
    `~/.config/clawrium/agents/<agent>/skills/` (the on-disk dir for
    per-agent skill bytes — distinct from the existing
    `state_file_path` which points at `skills.json`).
  - `skills.json` shape stays a flat list of strings, but the
    semantics change. **Decision (locked here, not deferred):** every
    entry is a per-agent local skill name (e.g. `"tdd"`). Registry refs
    (`"clawrium/tdd"`) are not valid desired state after this change.
    Document this in the file's module docstring.
  - `read_state` / `write_state` / `add_skill` / `remove_skill`
    validate names with the existing slug regex and reject any value
    containing `/`.
  - Add an explicit migration or one-time error strategy for old
    `skills.json` files containing registry refs. Preferred behavior:
    `clawctl agent skill add <agent> --from-template clawrium/tdd`
    creates the local `skills/tdd/` copy and writes `"tdd"`; old refs
    are rejected with a clear message telling the operator to re-add
    from template. Do not silently infer/copy templates during sync.

- `src/clawrium/core/skills_apply.py`
  - Change `apply_state` to load only per-agent local skills listed as
    bare names in `skills.json`. It no longer parses registry refs and
    no longer loads bundled/overlay catalog skills.
  - `_stage_skills` still produces `<staging>/<name>/SKILL.md`, but it
    must copy the already-materialized local `SKILL.md` bytes as-is.
    Remove the `materialize_for_claw(skill, agent_type)` call from the
    sync/apply path.
  - The playbook surface needs **no change**: it already receives a
    staging dir containing one `<name>/SKILL.md` per desired skill and
    `desired_skill_names` as bare names.

### CLI
- `src/clawrium/cli/clawctl/agent/skill.py` (REPLACE existing verbs)
  - Remove `attach`, `detach`, `get`, and the `--agent` option from
    all of them.
  - Add `list`, `add`, `edit`, `remove`. Agent name is a required
    positional first arg in every verb.
  - `add` input modes (mutually exclusive):
    1. `--from-template <registry>/<name>` — copy bytes from
       bundled-or-overlay catalog, materialized for the target
       agent's type, into the agent's local dir.
    2. Positional `PATH` — file (a single `SKILL.md`) or directory
       (a full skill tree). Validate the input shape, materialize it
       for the target agent type if it is a normalized `clawrium`
       shape, then persist the target-agent-native `SKILL.md` into the
       agent's local dir.
    3. No path and no template — open `$EDITOR` (or `EDITOR` env
       var; fall back to `vi`) on a stub `SKILL.md` in the target
       agent's native format, then persist on save.
  - `add` resolves the target agent first to determine `agent_type`.
    It validates the input and the final materialized `SKILL.md`
    against `_schema/native/<agent_type>.schema.json` before touching
    `skills.json`. On failure: nothing is written.
  - `add` has no `--force`. If `skills/<name>/` already exists or
    `skills.json` already contains `<name>`, fail with a clear message:
    remove or rename the existing skill first.
  - `add` rollback: if `skills_state.add_skill` fails after the
    local dir is written, delete the dir before returning the
    error. Symmetric to the existing preflight → mutate → apply
    pattern in `attach` (line 86–130 of the current file).
  - `add` does NOT call `apply_state`. The CLI exits after the
    state file is mutated. Use `clawctl agent sync <agent>` to
    flush. (Same model as `clawctl agent configure`/`sync`.)
  - `edit` opens `$EDITOR` on the already-agent-native local
    `SKILL.md`; re-validates against the agent's native schema on
    save; rejects schema-invalid writes (restoring the prior bytes in
    place). It does not run normalized-to-native materialization.
  - `remove` accepts only a bare local name; drops the matching
    `skills.json` entry and deletes the local dir.

- `src/clawrium/cli/clawctl/skill.py` (ADD top-level command)
  - New `add` command writing to
    `~/.config/clawrium/skills/<registry>/<name>/`. Accepts a
    positional `PATH` (file or dir) or `--interactive` to launch
    `$EDITOR`. Requires `--registry <clawrium|hermes|openclaw|zeroclaw>`
    (or prompts in interactive mode).
  - Validates against the existing per-registry schemas before
    writing (`validate_skill` after loading the staged copy).
  - Existing `skill_app.add_typer(skill_registry_app, name="registry")`
    wiring is unchanged. `add` is mounted directly on `skill_app`,
    not under `registry`, mirroring the issue's "add to local
    registry" framing.
  - `skill_registry_app.get` / `describe` automatically include
    overlay entries via the changed `list_skills` / `load_skill`.

### GUI
- `src/clawrium/gui/routes/agents.py` (per-agent endpoints already
  live here at lines 401/530/543; this file owns per-agent skill
  routes — NOT `routes/skills.py`)
  - Extend `GET /{agent_key}/skills` to show local installed skills
    from `skills.json` / `skills/<name>/`, plus catalog templates the
    user can add from. Installed entries are always agent-local.
  - The existing `POST /{agent_key}/skills/{registry}/{skill}` may be
    retained as a compatibility route for template add, but it must
    copy/materialize into the agent-local dir and write only the bare
    name to `skills.json`. It must not persist `<registry>/<name>`.
    The matching DELETE route should be deprecated or changed to local
    bare-name removal; registry refs are not installed state anymore.
  - **New** `POST /{agent_key}/skills` (no registry/skill path
    segments) — body carries an `input_mode` of `template`, `file`,
    or `inline` and the corresponding payload. Writes a per-agent
    local skill.
  - **New** `PUT /{agent_key}/skills/local/{name}` — replace the
    body of a per-agent local skill. Validate the final body against
    the agent's native schema; do not run normalized materialization
    during edit.
  - **New** `DELETE /{agent_key}/skills/local/{name}` — delete a
    per-agent local skill.

- `src/clawrium/gui/routes/skills.py` (catalog/read-only routes)
  - `GET /api/skills` continues to enumerate the catalog; the
    underlying `list_skills` change above means overlay entries
    appear automatically.
  - **New** `POST /api/skills` — add to user overlay. Accepts JSON
    `{registry, name, body, meta}` or multipart for a file upload.

- `src/clawrium/gui/frontend/...`
  - Per-agent view gains a "Local skills" section showing each
    entry with an origin chip, plus Edit and Remove controls.
  - "Add Skill" modal with three tabs (Template / File / Inline).
    Template tab pulls from `list_skills()` so users see bundled +
    overlay together.
  - Registry browser gains an "Add skill" entry point that calls
    `POST /api/skills`.
  - Reuse the existing whole-agent Sync control to flush. No
    skill-specific sync button.

### Docs
- `docs/skills/index.md` — replace the existing
  `clawctl agent skill attach <agent> clawrium/tdd` example with
  the new grammar. Update troubleshooting examples on lines
  148/182/191/195/198 of the current file.
- `docs/skills/authoring-clawrium.md` — update the
  `attach <openclaw/hermes/zeroclaw-agent>` examples at lines
  136–138.
- `docs/skills/local.md` (NEW) — canonical guide for per-agent
  local skills and the user overlay:
  - Mental model: bundled vs overlay vs agent-local (the table
    from this plan's "Conceptual model").
  - Three input modes for `clawctl agent skill add`.
  - Editing an on-agent skill via `clawctl agent skill edit`.
  - Adding a skill to the user overlay via `clawctl skill add`.
  - Flushing changes via `clawctl agent sync <agent>`.
- `website/docs/skills/local.md` (NEW) — verbatim mirror of
  `docs/skills/local.md` with Docusaurus frontmatter +
  mirror-warning HTML comment at top. The existing
  `website/docs/skills/` mirrors keep the same per-file pattern.
- `README.md` — replace the `clawctl agent skill attach
  clawrium/tdd --agent <agent-name>` example (line 50 of
  `AGENTS.md`, mirrored briefly in README) with the new grammar.
- `AGENTS.md` — update the "Skill Registry" Key Concepts section
  (line ~50) to describe copy-on-add semantics and the user-overlay
  path.
- `CONTRIBUTING.md` — sweep for `--agent` references; update.
- `CHANGELOG.md` `[Unreleased]`:
  - `### Added` — `clawctl agent skill add/edit/list/remove`,
    `clawctl skill add`, GUI Add Skill flow.
  - `### BREAKING` — `clawctl agent skill attach/detach/get`
    removed; `--agent` flag removed across `clawctl agent skill`.
    Include concrete before/after invocations in the entry body.
    Note that old `skills.json` entries containing registry refs such
    as `"clawrium/tdd"` are no longer valid desired state; operators
    must re-add those skills from template so Clawrium creates the
    per-agent native local copy.

## Test strategy

- **Unit (core)**
  - `_catalog_roots()` returns just bundled when overlay dir
    absent; returns both when present.
  - `list_skills` unions both roots; overlay wins on
    `<registry>/<name>` collision and emits one warning.
  - `load_skill` prefers overlay over bundled when both exist.
  - `load_agent_skill(agent, name, agent_type)` returns a native
    `Skill` for `hermes`, `openclaw`, and `zeroclaw`; raises
    `SkillNotFound` for missing; raises `SchemaValidationError` for
    malformed native `SKILL.md` frontmatter.
  - `list_agent_skills` returns sorted bare names; empty list if
    dir absent.
  - `skills_state` rejects any desired-state entry containing `/` and
    accepts only safe bare names.
  - `apply_state` stages only agent-local bare-name entries and copies
    their already-materialized `SKILL.md` bytes unchanged.

- **Per-agent format research locked into tests**
  - `hermes`: add from `clawrium/tdd` materializes to native
    `SKILL.md` frontmatter accepted by
    `skills/_schema/native/hermes.schema.json` and stores it under
    `~/.config/clawrium/agents/<agent>/skills/tdd/SKILL.md`. Sync
    stages that exact file unchanged for the hermes playbook, which
    installs to `~/.hermes/skills/clawrium/tdd/SKILL.md`.
  - `openclaw`: add from `clawrium/tdd` materializes to native
    `SKILL.md` frontmatter accepted by
    `skills/_schema/native/openclaw.schema.json` and stores it under
    the same control-plane local path. Sync stages that exact file
    unchanged for installation to `~/.openclaw/skills/tdd/SKILL.md`.
  - `zeroclaw`: add from `clawrium/tdd` materializes to native
    `SKILL.md` frontmatter accepted by
    `skills/_schema/native/zeroclaw.schema.json`. Sync stages that
    exact `<name>/SKILL.md` dir unchanged; the playbook invokes
    `zeroclaw skills install` on that staged dir.
  - For each supported agent type, tests must assert add-time
    materialization and sync-time non-mutation by comparing the local
    `SKILL.md` bytes with the staged bytes.

- **CLI (Typer `CliRunner`, tmp `$XDG_CONFIG_HOME`)**
  - `clawctl agent skill add <a> --from-template clawrium/tdd`
    materializes for the resolved agent type; state file gains bare
    entry `"tdd"`; rerun fails because duplicate names are not
    allowed.
  - `clawctl agent skill add <a> ./mydir/` copies dir; validates;
    rollback on schema failure leaves nothing behind.
  - `clawctl agent skill add <a>` (no path) launches
    `$EDITOR=true` (test stub) and persists the stub bytes.
  - `clawctl agent skill edit <a> <name>` round-trips; rejects
    invalid edits and restores prior bytes.
  - `clawctl agent skill remove <a> <name>` drops state and
    deletes dir. `remove <a> clawrium/tdd` is rejected because
    installed skills are addressed by bare per-agent names only.
  - `clawctl skill add ./mydir/ --registry clawrium` writes to
    overlay; subsequent `clawctl skill registry get` shows it.
  - Removed verbs (`attach`/`detach`/`get`) exit non-zero with a
    clear "removed in vNN.N — use `…` instead" message. (Typer
    natively reports "no such command" — augment with a hint via
    a `no_args_is_help` + custom error.)

- **GUI**
  - `GET /api/agents/{agent}/skills` returns origin tags.
  - `POST /api/agents/{agent}/skills` (no path segments) accepts
    each of the three input modes; rejects schema-invalid bodies
    with 422.
  - `PUT /api/agents/{agent}/skills/local/{name}` round-trips.
  - `DELETE /api/agents/{agent}/skills/local/{name}` removes
    state + dir.
  - `POST /api/skills` writes overlay; appears in subsequent
    `GET /api/skills`.

- **Real host (mac-test)**
  - Add a per-agent local skill via `--from-template`, run
    `clawctl agent sync <agent>`, verify the file lands on host
    in the target agent's native location and format.
  - Edit the local skill, sync, verify host content changes.
  - Remove the local skill, sync, verify host removes it.

## Subtasks

- **A. Core helpers + format validation** — catalog overlay helpers,
  per-agent local directory helpers, reusable add-time materialization
  helper, and hermes/openclaw/zeroclaw native-schema tests. No
  desired-state or apply behavior switch yet.
- **B. Desired-state switch + CLI + docs** — bare-name-only
  `skills.json`, sync/apply copies local native files as-is,
  `clawctl agent skill add/edit/list/remove`, BREAKING removal of
  `attach/detach/get/--agent`, top-level `clawctl skill add`,
  README/AGENTS.md/CONTRIBUTING.md/docs/skills/website mirror/CHANGELOG.
- **C. GUI** — backend routes (`POST /api/agents/{a}/skills`,
  `PUT|DELETE /api/agents/{a}/skills/local/{name}`,
  `POST /api/skills`); frontend "Local skills" section + Add Skill
  modal.

Dependency graph: B and C both depend on A. **B must merge before
C** — C's frontend strings reference the new CLI verbs in help
text and would document removed verbs otherwise.

## Deferred (separate issues)

- **AI-assisted skill authoring** (Claude Code slash command /
  `clawctl skill draft --prompt`). Issue #411's "utility functions
  and slash commands as well in case users want to create skills
  using an ai agent" explicitly asks for this. Scoped out of this
  plan because the three input modes (template / file / interactive
  editor) cover the core ad-hoc-skill ask without depending on AI
  tooling. File as a follow-up before this plan merges.
- **Promote / clone** a per-agent local skill back into the
  overlay registry (`clawctl skill add --from-agent <agent>/<name>`).
- **Multiple named user overlays** (per-team, etc.).

## Risks / known unknowns

- **`_catalog_root` callers.** `_load_schema` (line 510) and
  `_bare_name_hint` (line 232) still use the single-root helper.
  Schemas live in the bundled tree only — keeping the single-root
  helper for those uses is correct. The `_bare_name_hint` is
  unioning-eligible but the cost of touching it is real-error-path
  noise; defer to a follow-up unless tests force it.
- **GUI route shape.** Existing routes use
  `/{agent_key}/skills/{registry}/{skill}`. Adding
  `/{agent_key}/skills/local/{name}` works because `local` is not
  in `REGISTRIES`, so it cannot collide with a registry-template
  add. Lock this in by adding a routes-test asserting that
  `registry == "local"` always dispatches to the local handler.
- **Editor stub for `clawctl agent skill add` and `edit`.** Tests
  must inject `EDITOR=true` (or a script that writes deterministic
  bytes) so CI doesn't try to spawn vi. Document in the test file.
- **Overlay schema authority.** Schemas are loaded from the bundled
  tree only. Users cannot override schemas via the overlay. Worth
  one line in `docs/skills/local.md`.
- **Add-time materialization drift.** Moving materialization out of
  sync means `agent skill edit` edits native `SKILL.md` directly.
  That is intentional, but tests must lock that sync copies local
  bytes unchanged so future refactors do not reintroduce sync-time
  conversion.

---

<details>
<summary>Prompt Log</summary>

## Planning

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-07T17:43:41Z
**Model**: claude-opus-4-7

```prompt
ive closed the pr now. redo the plan end to end
```

**Output**: `.itx/411/00_PLAN.md` and `.itx/411/01_SCAFFOLD.md` rewritten from scratch after PR #634 (wrong-model implementation) was closed. Per-agent local skills + user registry overlay + bundled `skills/<registry>/` unchanged. `clawctl` throughout. Three subtasks (A core+apply / B CLI / C GUI).

## Planning (review-driven rewrite)

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-07T18:30:00Z
**Model**: claude-opus-4-7

```prompt
redo the full plan with this feedback. get rid of all old instruciotns
```

**Output**: `.itx/411/00_PLAN.md` and `.itx/411/01_SCAFFOLD.md` rewritten end-to-end after the prior version misnamed CLI file paths (`cli/agent_skill.py` vs the active `cli/clawctl/agent/skill.py`; `cli/skill.py` vs active `cli/clawctl/skill.py`), underspecified apply-pipeline staging shape, and hand-waved the `_catalog_root` signature change. This rewrite: pins file paths to the active `clawctl` surface, keeps `_catalog_root` returning a single `Path` and adds a sibling `_catalog_roots()`, locks `skills.json` bare-name decision in-plan (not at exit), aligns staging shape with the existing `_stage_skills` bare-name layout, and explicitly defers AI-authoring as a follow-up issue. Legacy `clm` modules called out as out of scope.

## Planning (add-time materialization rewrite)

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-07T21:20:27Z
**Model**: openai/gpt-5.5

```prompt
update the plan. also update the /add explicit tests to validate the skills format for each supported agent first and then copy the  akikks in right format. do a research and create a plan for each agent type thats supported

materiillzation should ahappen at the add time, not at the sync time. sync should movest apply the skillss as -is without any changes to the agent specific converntions
```

**Output**: Updated the plan to make `clawctl agent skill add` the materialization boundary. Per-agent skills are stored as already-native `SKILL.md` files under `~/.config/clawrium/agents/<agent>/skills/<name>/`; `skills.json` stores bare names only; `clawctl agent sync` stages and applies those files as-is without calling `materialize_for_claw`. Added per-agent format plan and tests for hermes, openclaw, and zeroclaw; removed force/collision semantics.

</details>
