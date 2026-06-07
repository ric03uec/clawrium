---
sidebar_position: 2
description: Add a new skill to the Clawrium catalog with the dual-schema validator and CI safety net.
keywords: [skills, authoring, schema, validator, ci, clawrium, openclaw, hermes, zeroclaw]
---

# Authoring Skills

A **vetted** skill ships in the clawrium repo at
`skills/vetted/<name>/SKILL.md` and gets bundled into the wheel. Every
agent in the fleet can attach it.

Vetted skills follow the same on-disk format as **local** skills (see
`docs/skills/index.md`). The only difference is location and
governance: vetted lives in-repo and goes through PR review.

The CI validator (`scripts/validate_skills.py`) is the contract — if
your skill passes locally, it passes in CI.

## 1. Pick a name

The `<name>` is a lowercase slug:

```
^[a-z0-9][a-z0-9_-]*$
```

The directory name and the SKILL.md frontmatter `name:` field MUST be
identical. Names are also **globally unique** across `vetted/` and
`local/` — a vetted skill cannot share a name with any user's local
skill.

## 2. Create the directory

```
skills/vetted/<name>/
  SKILL.md
```

That's the entire layout. No separate metadata file, no per-claw
subdirectories. The skill is one self-contained markdown file.

## 3. Write SKILL.md

`SKILL.md` is a markdown file with YAML frontmatter in the
[agentskills.io](https://agentskills.io) standard format:

```markdown
---
name: my-skill
description: One-line description shown in `clawctl skill list`.
version: 0.1.0
author: clawrium
license: MIT
tags: [example, docs]
---

# My Skill

The body is whatever instructions the agent needs at runtime.
Be concrete: list the steps, the inputs, the expected outputs.

## When to use

…

## Procedure

1. …
2. …
```

### Required frontmatter fields

- `name` — must equal the directory slug.
- `description` — one short line.

### Optional frontmatter fields

- `version` (semver-like string)
- `license`
- `author`
- `tags` (list of strings)
- `platforms` (list of strings, e.g. `["linux", "darwin"]`)
- `prerequisites` (free-form mapping)
- `metadata` (free-form mapping for skill-specific extras)

## 4. Per-claw materialization

At install time, `materialize_for_claw` (in
`src/clawrium/core/skills.py`) passes the frontmatter through verbatim
and dispatches to the per-claw apply playbook. There is currently no
per-claw shape translation — the agentskills format is what lands on
disk on the agent host.

Per-claw support is gated by the hardcoded
`SUPPORTED_CLAWS_BY_DEFAULT` table:

```python
SUPPORTED_CLAWS_BY_DEFAULT = {
    "hermes":   True,
    "openclaw": False,  # follow-up issue
    "zeroclaw": False,  # follow-up issue
}
```

A skill attached to an unsupported claw type raises
`ClawNotSupported`. You don't declare compatibility per-skill — the
table is global.

## 5. Validate locally

```bash
make lint
uv run pytest tests/test_vetted_skills_schema.py tests/test_validate_skills_script.py
```

The validator checks:

- Schema compliance (`skills/_schema/agent-skill.schema.json`).
- `name` matches the directory slug.
- No name collision with another vetted skill.

## 6. Open a PR

Open a PR with the new `skills/vetted/<name>/SKILL.md`. CI runs the
same validator. Once merged, the next clawrium release bundles your
skill in the wheel and every user gets it on `uv tool upgrade`.

## Editing an existing vetted skill

- The `name` is immutable. To rename, delete the directory in one PR
  and add the new name in a separate (or same) PR. There is no
  `git mv` shortcut at the catalog layer — the desired-state file on
  every agent references the old name and will be invalidated.
- Any field other than `name` can be edited freely.

## Local-source authoring (no PR)

If your skill is one-off or experimental, author it as a **local**
skill instead — no PR required:

```bash
clawctl skill add local/my-skill --description "..." --body-file ./body.md
```

See `docs/skills/index.md` for the local-source workflow.
