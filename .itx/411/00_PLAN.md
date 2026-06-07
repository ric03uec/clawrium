# Plan — #411 Allow adding ad-hoc skills to agents

**Issue**: https://github.com/ric03uec/clawrium/issues/411
**Complexity**: M
**Status**: planned (this file supersedes the prior planning draft in
this directory; see git history for the earlier vetted/local model that
was discarded in favor of the current per-agent + user-registry-overlay
design)

## Overview

Users today can only install skills onto an agent by referencing the bundled
in-repo catalog (`clm agent skill attach clawrium/tdd --agent <name>`). This
plan adds two new capabilities while keeping the catalog as-is:

1. **Per-agent ad-hoc skills.** A user can add a skill to a specific agent
   from any of three sources — interactively, from a local file, or from a
   local directory — and edit it afterwards. The skill is copied into the
   agent's own config directory and becomes part of the agent.
2. **Registry-level `clm skill add`.** A user can author a new skill and
   publish it to the skill registry, picking which agent type (registry
   namespace) it applies to. This is a separate command with no agent
   context.

The bundled `skills/` catalog stops being a live reference for on-agent
installs. It becomes a **template source**: when an agent skill is added
from a template, the bytes are copied into the agent's local skill dir,
and from that point on the agent's copy is the source of truth and is
fully editable.

## Conceptual model

| Concept | Where it lives | Mutable by user? |
|---|---|---|
| Bundled registry skill (seed catalog) | repo `skills/<registry>/<name>/` (also bundled into the wheel as `clawrium/_skills/`) | No (read-only) |
| User registry skill (added via `clm skill add`) | `~/.config/clawrium/skills/<registry>/<name>/` | Yes |
| Per-agent local skill (added via `clm agent skill add`) | `~/.config/clawrium/agents/<agent>/skills/<name>/` | Yes |

Decision locked in this plan: `clm skill add` writes to the **user
registry overlay** at `~/.config/clawrium/skills/<registry>/<name>/`. The
bundled `skills/` directory stays read-only because installed wheels
cannot be written to. Listing/loading code unions bundled + overlay;
overlay wins on name collision (with a warning).

Stage / flush model: every command in this plan only mutates local
state. The single host-side flush is the existing `clm agent sync
<name>` command, which already calls `apply_state`.

## CLI surface (Option 1 — agent as required positional)

New / changed commands under `clm agent skill`:

```
clm agent skill add    <agent-name> [PATH | --from-template <registry>/<name>]
clm agent skill edit   <agent-name> <skill-name>
clm agent skill list   <agent-name>
clm agent skill remove <agent-name> <skill-name>
```

The existing `attach` / `detach` verbs are **removed** and folded into
`add` / `remove`:

- `attach <ref>` becomes `add <agent> --from-template <ref>` — bytes are
  copied, not referenced.
- `detach <ref>` becomes `remove <agent> <skill-name>`.

The existing `--agent` flag is removed from every command in the
`clm agent skill` sub-app. Agent name becomes a required positional
everywhere, matching `clm agent configure <name>` and `clm agent sync <name>`.

New top-level command:

```
clm skill add [PATH | --interactive] \
              [--registry clawrium|openclaw|hermes|zeroclaw] \
              [--name <slug>]
```

Writes to `~/.config/clawrium/skills/<registry>/<name>/`. Prompts for
registry namespace if not supplied. Validates frontmatter / `_meta.yaml`
against the existing `skills/_schema/` definitions.

## Files to modify

### Core
- `src/clawrium/core/skills.py`
  - Extend `_catalog_root()` / `list_skills()` / `load_skill()` to union
    bundled catalog + user overlay (`~/.config/clawrium/skills/`).
  - Treat per-agent local skills as a separate axis; add
    `load_agent_skill(agent, name)` and `list_agent_skills(agent)`.
  - Per-agent local skills are universally compatible unless their
    authored `_meta.yaml.compatibility` says otherwise.
- `src/clawrium/core/skills_state.py`
  - Add `agent_skills_root(agent)` helper next to `state_file_path`.
  - State file shape unchanged — still a list of skill identifiers. For
    per-agent ad-hoc skills, identifier is the bare skill name (no
    registry prefix), since the namespace is implicitly `agent-local`.
- `src/clawrium/core/skills_apply.py`
  - On apply, ship per-agent local skill bytes from
    `~/.config/clawrium/agents/<agent>/skills/<name>/` instead of the
    bundled catalog.
  - Registry-overlay skills go through the same code path as bundled
    skills once they exist on disk — the catalog union handles it.

### CLI
- `src/clawrium/cli/agent_skill.py`
  - Remove `attach` / `detach` verbs and the `--agent` flag.
  - Add `add` / `edit` / `list` / `remove` with agent as required
    positional.
  - `add` rollback: if writing the local dir succeeds but state mutation
    fails, delete the freshly-written dir. Symmetric to the existing
    preflight → mutate → apply pattern.
- `src/clawrium/cli/skill.py`
  - Add top-level `add` command. Prompts (or accepts as flags) for
    registry namespace and name. Validates against schema before writing.

### GUI
- `src/clawrium/gui/routes/skills.py` + `gui/routes/agents.py`
  - Per-agent payload tags each skill with `origin: "local" | "<registry>"`.
  - New POST endpoints for agent-skill `add` / `edit` / `remove`.
  - New POST endpoint for registry `add` (top-level).
- `src/clawrium/gui/frontend/...`
  - Local-skills section in the per-agent view with Add / Edit / Remove
    controls mirroring the CLI.
  - "Add Skill" modal: three input modes (template picker, file upload,
    raw editor).
  - Registry browser gains an "Add to registry" entry point that maps
    to the top-level `clm skill add` semantics.

### Docs
- `README.md` — replace `clawctl agent skill attach clawrium/tdd --agent
  <agent-name>` example with `clm agent skill add <agent-name>
  --from-template clawrium/tdd`. Add a one-liner for the new top-level
  `clm skill add`.
- `AGENTS.md` — update the "Skill Registry" Key Concepts section to
  describe copy-on-add semantics and the user-overlay path. Update CLI
  examples.
- `CONTRIBUTING.md` — if it references skill workflow, update to new
  grammar.
- `docs/skills.md` — canonical skill guide. Sections:
  - Mental model: bundled vs user overlay vs agent-local
  - Three ways to add a skill to an agent
  - Editing an on-agent skill
  - Adding a skill to the registry with `clm skill add`
  - Flushing changes via `clm agent sync <agent>`
- `website/docs/skills.md` — verbatim mirror of `docs/skills.md` with
  Docusaurus frontmatter + mirror-warning HTML comment at top.
- `CHANGELOG.md` under `[Unreleased]`:
  - `### Added` — `clm agent skill add/edit/list/remove`, `clm skill add`,
    GUI "Add Skill" flow.
  - `### BREAKING` — `clm agent skill attach/detach` and the `--agent`
    flag are removed. Concrete before/after invocations. Note that
    existing `skills.json` state files remain readable; only invocations
    change.

## Test strategy

- **Unit (core)**: catalog union (bundled + overlay), `load_agent_skill`,
  `list_agent_skills`, collision rejection, overlay-wins behavior,
  apply-state routing for per-agent bytes, rollback on add failure.
- **CLI (Typer `CliRunner`)**: each `add` input mode against a tmp
  `~/.config/clawrium/`; `edit` opens editor and rewrites file; `remove`
  removes from state and keeps the local dir; `list` shows the
  expected origin tags; `clm skill add` writes to the overlay and shows
  up in subsequent `clm skill list` calls.
- **GUI**: per-agent route shape with `origin` tag; POST endpoints
  round-trip; rejects malformed payloads.
- **Real host**: add a local skill, run `clm agent sync <agent>`, verify
  it lands on the agent host alongside registry skills. Verify edit ->
  sync propagates changes. Verify remove -> sync removes from host but
  keeps the local dir.

## Subtasks

- **A. Core + apply** — catalog union, per-agent loader, apply-state
  routing, schema reuse, rollback. Unit tests.
- **B. CLI** — `clm agent skill add/edit/list/remove` (with breaking
  removal of `attach/detach/--agent`), `clm skill add` top-level command,
  docs updates (README, AGENTS.md, docs/skills.md, website mirror,
  CHANGELOG `[Unreleased]` `### Added` + `### BREAKING`).
- **C. GUI** — backend routes for agent-skill add/edit/remove and
  registry add; frontend local-skills section, Add Skill modal,
  Edit/Remove controls.

Dependencies: B and C both depend on A. B and C can land in parallel
once A is merged.

## Deferred (separate issues)

- **Promote / clone** an agent-local skill back into the registry
  (`clm skill add --from-agent <agent>/<name>`-style).
- **AI-assisted skill authoring** (Claude Code slash command or
  `clm skill draft --prompt`).
- **Multiple named user registries** (per-team, etc.).

## Risks / known unknowns

- **Apply playbook source path.** The current playbook in
  `skills_apply.py` assumes a single catalog root. Per-agent dirs and the
  user overlay need to be wired in without making the playbook
  source-aware. Likely approach: stage all skills for the agent into a
  temporary mirror dir that matches the bundled catalog shape, then
  invoke the playbook against the temp dir. Pinned down in Subtask A.
- **Name collisions across origins.** `clawrium/tdd` (bundled),
  `clawrium/tdd` (user overlay), and `tdd` (agent-local) can all
  coexist. State file only contains the agent-local list; the UI must
  show origin clearly so users don't think one shadows another.
- **`skills.json` schema.** Today entries look like `clawrium/tdd`. For
  per-agent ad-hoc skills, do we use the bare name (`tdd`) or a
  reserved namespace (`local/tdd`)? Default in this plan: bare name,
  because the namespace is implicit and the state file is already
  per-agent. Subtask A locks this in.

---

<details>
<summary>Prompt Log</summary>

## Planning

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-07T06:15:24Z
**Model**: claude-opus-4-7

```prompt
411 ask me any clarifying questions. dont create any files, just plan first.
```

**Output**: `.itx/411/00_PLAN.md` and `.itx/411/01_SCAFFOLD.md` capturing per-agent ad-hoc skills, copy-on-add semantics from registry templates, agent-as-positional CLI grammar (Option 1), new top-level `clm skill add` writing to a user overlay, stage-then-`clm agent sync` flush model, GUI scope, docs deliverables, three subtasks (A core+apply / B CLI / C GUI), and deferred follow-ups.

</details>
