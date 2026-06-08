# Local Agent Skills

Local agent skills are the editable, per-agent copies that Clawrium
actually syncs to hosts. Catalog skills are templates; adding one to an
agent copies and materializes it into that agent's native format.

## Control-Plane Layout

```text
~/.config/clawrium/agents/<agent>/skills/<name>/SKILL.md
~/.config/clawrium/agents/<agent>/skills.json
```

`skills.json` stores only bare local names:

```json
{"skills": ["tdd", "incident-review"]}
```

Registry refs such as `"clawrium/tdd"` are invalid in `skills.json`.
Re-add old registry refs from their template instead:

```bash
clawctl agent skill add <agent> --from-template clawrium/tdd
clawctl agent sync <agent>
```

## Add From A Catalog Template

```bash
clawctl agent skill add my-agent --from-template clawrium/tdd
```

This command resolves `my-agent`'s type, loads `clawrium/tdd`, converts it
to the target native format, validates the final native frontmatter, and
writes:

```text
~/.config/clawrium/agents/my-agent/skills/tdd/SKILL.md
```

The copied skill has no lifecycle link to the catalog template. Editing
the catalog later does not mutate the agent-local copy.

## Add From A Path

```bash
clawctl agent skill add my-agent ./skills/hermes/my-skill
clawctl agent skill add my-agent ./SKILL.md --name incident-review
```

Path input can be either:

- A normalized `clawrium/`-style directory with `_meta.yaml` and
  `SKILL.md`. Clawrium materializes it for the target agent type.
- A native `SKILL.md` file or directory. Clawrium validates it against
  the target agent type's native schema and copies the bytes into the
  local skill directory.

If `--name` is omitted, Clawrium derives the local name from the validated
frontmatter `name:` field, not from the input path.

## Apply To Host

`add`, `edit`, and `remove` mutate local control-plane state only. Push
the state to the host explicitly:

```bash
clawctl agent sync my-agent
```

Sync does not convert formats. It reads the bare names in `skills.json`,
copies each already-agent-native local `SKILL.md` into staging unchanged,
and runs the agent type's apply playbook.

## Edit And Remove

```bash
clawctl agent skill list my-agent
clawctl agent skill edit my-agent tdd
clawctl agent skill remove my-agent tdd
clawctl agent sync my-agent
```

`edit` opens the local native `SKILL.md`, validates it against the
agent's native schema, and restores the prior bytes if validation fails.

## No Force Overwrites

Skill names are unique per agent. If
`~/.config/clawrium/agents/<agent>/skills/<name>/` exists or `skills.json`
already contains `<name>`, `add` fails. There is no `--force`; remove or
rename the existing skill first.

## User Overlay Catalog

Use `clawctl skill add` when you want a reusable template available to
multiple agents:

```bash
clawctl skill add ./my-hermes-skill --registry hermes
clawctl skill registry get
clawctl agent skill add my-hermes-agent --from-template hermes/my-hermes-skill
```

Overlay entries are stored under:

```text
~/.config/clawrium/skills/<registry>/<name>/
```

They appear in `clawctl skill registry get` and `describe` alongside the
bundled catalog. If an overlay entry has the same `<registry>/<name>` as
a bundled skill, the overlay wins.

## Using the web UI

The Clawrium GUI surfaces the same per-agent skill lifecycle on the
**Agent Detail → Skills** tab.

### Adding a skill

Click **Add skill** on the Skills tab to open the add-skill modal. Three
input modes are available as tabs:

| Tab | What it does |
|---|---|
| **From catalog** | Pick any bundled or overlay catalog skill by name and click **Install**. |
| **From file** | Paste the full contents of a `SKILL.md` file. The skill name is read from the `name:` frontmatter field. |
| **Inline** | Type a name, description, and optional markdown body directly. |

All three modes write a per-agent local skill immediately, without touching
the agent host. Click **Sync** (the existing agent Sync control) to flush
the change to the host.

### Editing an on-agent skill

Only **LOCAL** skills (created via File or Inline mode) show an **Edit**
button. Click it to open an in-browser editor with the raw `SKILL.md`
text. Save to update the local copy; Sync to apply on the host.

Catalog-sourced skills (**BUNDLED** or **OVERLAY**) are read-only in the
editor — remove and re-add them from the catalog picker to update.

### Removing a skill

Click **Remove** on any installed skill row. A confirmation step prevents
accidental removal. After confirming:
- The skill is removed from local desired state immediately.
- The on-host file is pruned on the next **Sync**.

### Adding to the user overlay

To make a skill available across all your agents, click **Add to catalog**
(top-right of the Skills page) and fill in the registry, name, and
`SKILL.md` content. The skill appears in the catalog picker with an
**OVERLAY** origin chip.

### Origin chips

Each installed skill row shows an origin chip:

| Chip | Meaning |
|---|---|
| **LOCAL** | Created via File or Inline mode; no source template. |
| **BUNDLED** | Copied from the bundled in-repo catalog. |
| **OVERLAY** | Copied from your user overlay catalog. |

### Flushing via Sync

After any add, edit, or remove in the GUI, use the agent's existing
**Sync** control to apply the changes on the host. The skill endpoints
do not call `apply_state` automatically — this is by design so you can
stage multiple changes before a single flush.
