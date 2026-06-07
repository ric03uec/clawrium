# Skills Catalog

<!--
  Repo-rooted docs live in docs/skills/. The user-facing site mirror
  lives at website/docs/skills/ and is kept semantically in sync.
  Update both when changing catalog rules.
-->

Clawrium ships a curated catalog of **skills** that any agent in your
fleet can install with one command. A skill is a directory containing
a single `SKILL.md` file (YAML frontmatter + markdown body in the
[agentskills.io](https://agentskills.io) standard format) that the
underlying claw discovers at runtime — Test-Driven Development
discipline, blog drafting, issue triage, and so on.

Skills come from one of two **sources**:

- **vetted** — shipped in the clawrium repo at `skills/vetted/<name>/`.
  Read-only at runtime. Changes go through PR review.
- **local** — user-owned, stored at `~/.config/clawrium/skills/<name>/`.
  Created/edited/deleted via `clawctl skill add|edit|remove` or the
  GUI catalog page.

Skill names are **globally unique** across both sources — you cannot
have both `vetted/tdd` and `local/tdd`. Name is also immutable; rename
= delete + re-create.

## Quick start

```bash
# Browse the unified catalog
clawctl skill list

# Inspect a skill before installing
clawctl skill show vetted/tdd

# Create a local skill
clawctl skill add local/my-skill --description "..." --body-file ./body.md

# Edit a local skill (name cannot change)
clawctl skill edit local/my-skill --description "new desc"

# Delete a local skill
clawctl skill remove local/my-skill

# Attach to an agent
clawctl agent skill attach vetted/tdd --agent my-agent
clawctl agent skill attach local/my-skill --agent my-agent

# List skills attached to an agent
clawctl agent skill get --agent my-agent

# Detach
clawctl agent skill detach vetted/tdd --agent my-agent
```

The GUI mirrors the same surface under `Skills` (flat list with a
`+ Create Skill` button) and `Agents → <agent> → Skills` (install
picker).

## Per-claw support (v1)

Skill attach is gated on a hardcoded per-claw support table:

| Claw type | Supported in v1 |
|-----------|-----------------|
| `hermes`   | yes |
| `openclaw` | no (re-enabled in a follow-up issue) |
| `zeroclaw` | no (re-enabled in a follow-up issue) |

Attempting `clawctl agent skill attach <ref> --agent <agent>` against
an unsupported claw raises `ClawNotSupported`. The GUI install picker
disables agents whose claw type is off in this table with a
"Not yet supported on this agent type" tooltip.

This table lives at `SUPPORTED_CLAWS_BY_DEFAULT` in
`src/clawrium/core/skills.py` and is gated by PR review.

## Reference grammar

Every skill is referenced as `<source>/<name>`:

- `source` is one of `vetted`, `local`.
- `name` matches `^[a-z0-9][a-z0-9_-]*$`.

Bare names (e.g. `tdd`) are rejected with `MissingSourcePrefix`.
URLs and arbitrary paths are rejected with `ExternalSourceBlocked`.

## On-disk layout

```
skills/                                 # repo root (vetted source)
  _schema/
    agent-skill.schema.json             # agentskills.io standard
  vetted/
    tdd/
      SKILL.md                          # YAML frontmatter + markdown
    blog-author/
      SKILL.md
    ...

~/.config/clawrium/skills/              # local source
  my-skill/
    SKILL.md
```

## Authoring

- **Vetted skills** — see [Authoring vetted skills](./authoring-clawrium.md).
- **Local skills** — author with `clawctl skill add local/<name>` or
  the GUI **+ Create Skill** modal. No PR needed.
- The native per-claw authoring guide (`authoring-native.md`) is
  obsolete in the unified model — all skills now share one format and
  are translated at install time by `materialize_for_claw`.

## Desired-state migration

Existing agents whose desired-state file at
`~/.config/clawrium/agents/<agent>/skills.json` references old
`<registry>/<name>` refs (e.g. `clawrium/tdd`, `hermes/blog-author`)
get a **one-shot migration** on first read after upgrade:

- `clawrium/<name>` is rewritten to `vetted/<name>` if the name exists.
- `hermes/<name>` is rewritten to `vetted/<name>` (same lookup).
- Anything else (or missing from the catalog) is dropped with a
  WARNING log line.

Migrations happen automatically; no user action required.
