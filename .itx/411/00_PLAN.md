# Plan — #411 Allow adding ad-hoc skills to agents

**Issue**: https://github.com/ric03uec/clawrium/issues/411
**Complexity**: M
**Status**: planned

## Overview

Today a user can only install a skill onto a clawrium-managed agent by
referencing the bundled in-repo catalog
(`clawctl agent skill attach clawrium/tdd --agent <name>`). This plan
adds two new capabilities while leaving the existing bundled catalog
exactly as it is on `main`:

1. **Per-agent ad-hoc skills.** A user can add a skill to a specific
   agent from any of three sources — interactively, from a local file,
   or from a local directory — and edit it afterwards. The skill is
   copied into the agent's own config directory and becomes part of
   that agent.
2. **Registry-level `clawctl skill add`.** A user can author a new
   skill and publish it to a user-owned registry overlay, picking
   which registry namespace (`clawrium` / `hermes` / `openclaw` /
   `zeroclaw`) it applies to. This is a separate command with no
   agent context.

The bundled `skills/` catalog stops being a live reference for
on-agent installs. It becomes a **template source**: when an agent
skill is added from a template, the bytes are copied into the agent's
local skill directory, and from that point the agent's copy is the
source of truth and is fully editable.

The four bundled registries (`clawrium/`, `hermes/`, `openclaw/`,
`zeroclaw/`) and the `_schema/` directory under `skills/` stay
exactly as they are on `main`. No restructuring.

## Conceptual model

| Concept | Where it lives | Mutable by user? |
|---|---|---|
| Bundled registry skill (seed catalog) | repo `skills/<registry>/<name>/` (also bundled into the wheel as `clawrium/_skills/`) | No (read-only) |
| User registry overlay skill (added via `clawctl skill add`) | `~/.config/clawrium/skills/<registry>/<name>/` | Yes |
| Per-agent local skill (added via `clawctl agent skill add`) | `~/.config/clawrium/agents/<agent>/skills/<name>/` | Yes |

`<registry>` is one of `clawrium`, `hermes`, `openclaw`, `zeroclaw` —
the existing four-registry namespace. The user overlay is just a
second, writeable root that mirrors the bundled tree's shape.
Listing/loading code unions bundled + overlay; on a name collision
the overlay wins and a warning is logged.

Per-agent local skills live under the agent's own config directory.
They are not addressable by a `<registry>/<name>` ref because the
namespace is implicit — they belong to exactly one agent. State
file entries are bare names.

Stage / flush model: every command in this plan only mutates local
state. The single host-side flush is the existing
`clawctl agent sync <name>` command, which already calls
`apply_state`. There is no new skill-specific sync verb.

## CLI surface (Option 1 — agent as required positional)

New commands under `clawctl agent skill`:

```
clawctl agent skill add    <agent-name> [PATH | --from-template <registry>/<name>]
clawctl agent skill edit   <agent-name> <skill-name>
clawctl agent skill list   <agent-name>
clawctl agent skill remove <agent-name> <skill-name>
```

The existing `attach` / `detach` verbs are **removed** and folded into
`add` / `remove`:

- `attach <ref>` becomes `add <agent> --from-template <ref>` — bytes
  are copied from the bundled (or overlay) catalog into the agent's
  local directory.
- `detach <ref>` becomes `remove <agent> <skill-name>` — drops the
  entry from the agent's `skills.json` and deletes the local dir.

The existing `--agent` flag is removed from every command in the
`clawctl agent skill` sub-app. Agent name becomes a required
positional everywhere, matching `clawctl agent configure <name>` and
`clawctl agent sync <name>`.

New top-level command (no agent context):

```
clawctl skill add [PATH | --interactive] \
                  [--registry clawrium|hermes|openclaw|zeroclaw] \
                  [--name <slug>]
```

Writes to `~/.config/clawrium/skills/<registry>/<name>/`. Prompts for
the registry namespace if not supplied. Validates frontmatter /
`_meta.yaml` against the existing per-registry schemas under
`skills/_schema/`.

## Files to modify

### Core
- `src/clawrium/core/skills.py`
  - Extend `_catalog_root()` to return a list of roots: bundled plus
    user overlay (`~/.config/clawrium/skills/`).
  - Update `list_skills()` / `load_skill()` to union both roots;
    overlay wins on `<registry>/<name>` collision and emits a
    warning log.
  - Add `load_agent_skill(agent, name)` and `list_agent_skills(agent)`
    reading from `~/.config/clawrium/agents/<agent>/skills/<name>/`.
  - Per-agent local skills validate as `clawrium`-flavored
    (universally compatible) unless their `_meta.yaml.compatibility`
    overrides.
- `src/clawrium/core/skills_state.py`
  - Add `agent_skills_root(agent)` helper next to `state_file_path`.
  - State file shape unchanged. Per-agent ad-hoc skill entries are
    bare names (no `<registry>/` prefix); the namespace is implicit.
- `src/clawrium/core/skills_apply.py`
  - On apply, stage all skills (bundled, overlay, agent-local) into a
    temporary mirror dir that matches the existing catalog shape,
    then invoke the existing playbook against the temp dir. Keeps
    the playbook source-agnostic.

### CLI
- `src/clawrium/cli/agent_skill.py`
  - Remove `attach` / `detach` verbs and the `--agent` flag.
  - Add `add` / `edit` / `list` / `remove` with agent as required
    positional.
  - `add` input modes: `--from-template <registry>/<name>`,
    positional `PATH` (file or directory), interactive prompt.
  - `add` rollback: if state mutation fails after the local dir is
    written, delete the dir before returning the error. Symmetric
    to the existing preflight → mutate → apply pattern.
  - `edit` opens `$EDITOR` on the local `SKILL.md`.
  - `remove` drops the state entry and deletes the local dir.
- `src/clawrium/cli/skill.py`
  - Add top-level `add` command writing to
    `~/.config/clawrium/skills/<registry>/<name>/`. Accepts a
    positional `PATH` (file or dir) or runs an interactive prompt.
    Requires `--registry <clawrium|hermes|openclaw|zeroclaw>` (or
    prompts). Validates against the existing per-registry schemas
    before writing.

### GUI
- `src/clawrium/gui/routes/skills.py` + `src/clawrium/gui/routes/agents.py`
  - Per-agent payload tags each skill with `origin: "local" | "<registry>"`.
  - New `POST /api/agents/{agent}/skills` for `add`.
  - New `PUT /api/agents/{agent}/skills/{name}` for `edit`.
  - New `DELETE /api/agents/{agent}/skills/{name}` for `remove`.
  - New `POST /api/skills` for the top-level user-overlay `add`.
- `src/clawrium/gui/frontend/...`
  - Local-skills section in the per-agent view with Add / Edit /
    Remove controls mirroring the CLI.
  - Add Skill modal: three input modes (template picker, file upload,
    raw editor). Template picker pulls from `list_skills()` so users
    can pick bundled + overlay.
  - Registry browser gains an "Add to registry" entry point that
    maps to the top-level `clawctl skill add` semantics.
  - Reuse the existing whole-agent Sync control to flush; no
    skill-specific sync button.

### Docs
- `README.md` — replace the
  `clawctl agent skill attach clawrium/tdd --agent <agent-name>`
  example with `clawctl agent skill add <agent-name> --from-template clawrium/tdd`.
  Add a one-liner for the new top-level `clawctl skill add`.
- `AGENTS.md` — update the "Skill Registry" Key Concepts section to
  describe copy-on-add semantics and the user-overlay path. Update
  CLI examples.
- `CONTRIBUTING.md` — sweep for `--agent` references; update.
- `docs/skills.md` (new or updated) — canonical skill guide:
  - Mental model: bundled vs user overlay vs agent-local
  - Three ways to add a skill to an agent
  - Editing an on-agent skill
  - Adding a skill to the registry with `clawctl skill add`
  - Flushing changes via `clawctl agent sync <agent>`
- `website/docs/skills.md` — verbatim mirror of `docs/skills.md` with
  Docusaurus frontmatter + mirror-warning HTML comment at top.
- `CHANGELOG.md` under `[Unreleased]`:
  - `### Added` — `clawctl agent skill add/edit/list/remove`,
    `clawctl skill add`, GUI Add Skill flow.
  - `### BREAKING` — `clawctl agent skill attach/detach` and the
    `--agent` flag are removed. Concrete before/after invocations.
    `skills.json` state files on disk remain readable; only
    invocations change.

## Test strategy

- **Unit (core)**: catalog union (bundled + overlay), `load_agent_skill`,
  `list_agent_skills`, collision rejection, overlay-wins behavior,
  apply-state routing for per-agent bytes, rollback on `add` failure.
- **CLI (Typer `CliRunner`)**: each `add` input mode against a tmp
  `~/.config/clawrium/`; `edit` opens editor and rewrites file;
  `remove` drops state and deletes the local dir; `list` shows the
  expected origin tags; `clawctl skill add` writes to the overlay
  and shows up in subsequent `clawctl skill list` calls.
- **GUI**: per-agent route shape with `origin` tag; new POST/PUT/
  DELETE endpoints round-trip; rejects malformed payloads.
- **Real host**: add a local skill, run `clawctl agent sync <agent>`,
  verify it lands on the agent host alongside bundled-template skills.
  Verify `edit` → `sync` propagates changes. Verify `remove` → `sync`
  removes from host.

## Subtasks

- **A. Core + apply** — catalog union, per-agent loader, apply-state
  routing, unit tests. Hard prereq for B and C.
- **B. CLI** — `clawctl agent skill add/edit/list/remove` (with
  breaking removal of `attach/detach/--agent`), `clawctl skill add`
  top-level command, docs updates (README, AGENTS.md, docs/skills.md,
  website mirror, CHANGELOG `[Unreleased]` `### Added` +
  `### BREAKING`).
- **C. GUI** — backend routes for agent-skill add/edit/remove and
  registry add; frontend local-skills section, Add Skill modal,
  Edit/Remove controls.

Dependencies: B and C both depend on A. B and C can land in parallel
once A is merged.

## Deferred (separate issues)

- **Promote / clone** an agent-local skill back into the overlay
  registry (`clawctl skill add --from-agent <agent>/<name>`-style).
- **AI-assisted skill authoring** (Claude Code slash command or
  `clawctl skill draft --prompt`).
- **Multiple named user registries** (per-team, etc.).

## Risks / known unknowns

- **Apply playbook source path.** The current playbook in
  `skills_apply.py` reads from a single catalog root. Per-agent dirs
  and the user overlay need to be wired in without making the
  playbook source-aware. The plan stages all sources into a
  temporary mirror dir matching the bundled catalog shape. Pin
  down in Subtask A.
- **Name collisions across origins.** `clawrium/tdd` (bundled),
  `clawrium/tdd` (overlay), and `tdd` (agent-local on a specific
  agent) can all coexist. State file only contains the agent-local
  list; the UI must show origin clearly so users don't think one
  shadows another.
- **`skills.json` shape for agent-local entries.** Plan defaults to
  bare names (`tdd`) rather than a reserved namespace (`local/tdd`).
  Locked in Subtask A's exit criteria.

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

</details>
