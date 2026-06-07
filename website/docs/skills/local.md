---
sidebar_position: 2
description: Manage editable per-agent skill copies and sync them to hosts.
keywords: [skills, local skills, sync, agent skills, clawctl]
---

# Local Agent Skills

Local agent skills are the editable, per-agent copies that Clawrium syncs
to hosts. Catalog skills are templates. Adding one to an agent copies and
materializes it into that agent's native format.

## Layout

```text
~/.config/clawrium/agents/<agent>/skills/<name>/SKILL.md
~/.config/clawrium/agents/<agent>/skills.json
```

`skills.json` stores only bare local names:

```json
{"skills": ["tdd", "incident-review"]}
```

Registry refs such as `"clawrium/tdd"` are invalid in `skills.json`.
Re-add old refs from their template:

```bash
clawctl agent skill add <agent> --from-template clawrium/tdd
clawctl agent sync <agent>
```

## Add Skills

```bash
# Copy and materialize a catalog template
clawctl agent skill add my-agent --from-template clawrium/tdd

# Copy a local native SKILL.md or normalized clawrium directory
clawctl agent skill add my-agent ./SKILL.md
clawctl agent skill add my-agent ./my-skill --name incident-review
```

If `--name` is omitted, Clawrium derives the local name from the validated
frontmatter `name:` field.

## Sync Skills

`add`, `edit`, and `remove` only change local control-plane state. Push
that state to the host explicitly:

```bash
clawctl agent sync my-agent
```

Sync does not convert formats. It copies each already-agent-native local
`SKILL.md` into staging unchanged, then runs the agent type's apply
playbook.

## Edit And Remove

```bash
clawctl agent skill list my-agent
clawctl agent skill edit my-agent tdd
clawctl agent skill remove my-agent tdd
clawctl agent sync my-agent
```

`edit` validates the local native `SKILL.md` and restores the prior bytes
if validation fails. `add` never overwrites an existing local skill; there
is no `--force`.

## User Overlay Catalog

Use `clawctl skill add` for reusable templates:

```bash
clawctl skill add ./my-hermes-skill --registry hermes
clawctl skill registry get
clawctl agent skill add my-hermes-agent --from-template hermes/my-hermes-skill
```

Overlay entries live under `~/.config/clawrium/skills/<registry>/<name>/`
and appear in `skill registry get` / `describe`. An overlay entry wins
over a bundled catalog entry with the same `<registry>/<name>`.
