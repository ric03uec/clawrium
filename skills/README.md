# Clawrium Skills Catalog

Skills are markdown documents (`SKILL.md`) with YAML frontmatter that get
materialized onto agent hosts when you run `clawctl agent skill attach`.

## Two sources

```
vetted/<name>/SKILL.md          ← in-repo, ships in the wheel (this directory)
~/.config/clawrium/skills/<name>/SKILL.md   ← user-owned, created via `clawctl skill add`
```

Both sources use the same flat [agentskills.io](https://agentskills.io)
format. Skill names are globally unique across both sources — you cannot
have `vetted/tdd` and `local/tdd` at the same time.

References use the form `<source>/<name>` (e.g. `vetted/tdd`,
`local/my-skill`). Bare names are rejected.

## Editing rules

- **Vetted** skills are read-only at runtime. Changes go through PR review.
- **Local** skills are created/edited/deleted via `clawctl skill add|edit|remove`
  or the GUI.
- The `name` field is immutable — renaming requires delete + re-create.

## File format

```yaml
---
name: my-skill
description: One-line description.
version: 0.1.0          # optional
license: MIT            # optional
author: you             # optional
platforms: [linux]      # optional
tags: [example]         # optional
prerequisites: {}       # optional
---

# My Skill

Markdown body of the skill instructions.
```

Required fields: `name`, `description`. Everything else is optional.

## Per-claw support

Skills install on agents whose `agent_type` is listed in
`SUPPORTED_CLAWS_BY_DEFAULT` in `src/clawrium/core/skills.py`. Currently:

| Claw      | Supported |
|-----------|-----------|
| hermes    | yes       |
| openclaw  | no        |
| zeroclaw  | no        |

Openclaw and zeroclaw will be re-enabled once their materializers and
end-to-end tests are wired in follow-up issues.
