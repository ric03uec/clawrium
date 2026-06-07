---
sidebar_position: 2
description: Add a new skill to the Clawrium catalog with the dual-schema validator and CI safety net.
keywords: [skills, authoring, schema, validator, ci, clawrium, openclaw, hermes, zeroclaw]
---

# Authoring Skills

Bundled skills are added by dropping a directory into the in-repo
`skills/<registry>/<name>/` tree, opening a PR, and letting the CI
validator gate the schema. For private reusable templates, use
`clawctl skill add <path> --registry <registry>` to write a user overlay
under `~/.config/clawrium/skills/`. This page covers bundled catalog
authoring; the same schema rules apply to overlay entries. The repository
[`docs/skills/`](https://github.com/ric03uec/clawrium/tree/main/docs/skills)
guides go deeper on each.

## Choose a registry

| You're adding…                                  | Registry         |
|-------------------------------------------------|------------------|
| Behaviour that should run on every claw         | `clawrium/`      |
| openclaw-specific frontmatter (e.g. allowed-tools) | `openclaw/`   |
| hermes-specific metadata (tags, homepage)       | `hermes/`        |
| zeroclaw-specific frontmatter                   | `zeroclaw/`      |

A native skill (`<claw>/<name>`) is installable **only** on agents of
the matching type. A `clawrium/<name>` skill is installable on any
agent whose entry in the skill's `compatibility:` map is truthy.

## Slug rule

The skill directory name (and `name:` field in `_meta.yaml` /
frontmatter) must match:

```
^[a-z0-9][a-z0-9_-]*$
```

The directory name and the `name:` field MUST be identical. This is
the source-dirname == registry-slug invariant required for zeroclaw's
`skills install`/`remove` CLI to round-trip cleanly (see Phase 0
findings in `.itx/364/02_PHASE0_FINDINGS.md`).

## `clawrium/<name>/` — cross-agent

Layout:

```
skills/clawrium/<name>/
├── _meta.yaml      # required — validated against clawrium.schema.json
├── SKILL.md        # required — canonical content
└── README.md       # optional
```

Minimum `_meta.yaml`:

```yaml
name: <name>
description: One-line elevator pitch.
version: 0.1.0
compatibility:
  openclaw: true
  hermes: true
  zeroclaw: true
```

Minimum `SKILL.md`:

```markdown
---
name: <name>
description: One-line elevator pitch.
---

# Skill body...
```

## `<claw>/<name>/` — native

Layout:

```
skills/<claw>/<name>/
├── SKILL.md        # required — frontmatter is the source of truth
└── README.md       # optional
```

**No `_meta.yaml`.** A `_meta.yaml` under a native registry is a hard
failure in the validator (almost always a misplaced clawrium skill).

Minimum `SKILL.md`:

```markdown
---
name: <name>
description: One-line elevator pitch.
---

# Skill body...
```

Forbidden in native frontmatter:

- `compatibility:` — clawrium-only.
- `native:` — clawrium-only (per-claw override map for the cross-agent
  shape).

The native schemas are otherwise lenient (`additionalProperties: true`)
so a claw can add new frontmatter fields upstream without breaking CI.

## Validate locally

```bash
python scripts/validate_skills.py
```

Expected output on success:

```
ok: skills catalog at .../skills validates
```

Failures print the offending file path and the specific rule violated.
Common ones:

| Failure message                          | Fix                                        |
|------------------------------------------|--------------------------------------------|
| `must equal directory name`              | Make `name:` match the dirname             |
| `missing required _meta.yaml`            | clawrium skill is missing the file         |
| `missing required SKILL.md`              | Add the file alongside `_meta.yaml`        |
| `failed Clawrium normalized skill (_meta.yaml) validation` | Read the per-field message; usually a typo or wrong type in `_meta.yaml` |
| `_meta.yaml is only valid under skills/clawrium/` | Move the skill or delete the file |
| `clawrium-only keys`                     | Remove `compatibility:`/`native:` keys     |
| `violates the slug rule`                 | Rename the directory to lowercase letters, digits, `-`, `_` |
| `symlinks are not allowed`               | Inline the file, no symlinks               |

Run the test suite too:

```bash
make test
```

## Smoke-test against a real claw

Before merging, exercise the add/sync/list/remove round-trip against a
real agent. For a `clawrium/<name>` skill, this means three agents
(one per claw); for a `<claw>/<name>` native skill, one agent of the
matching type.

```bash
clawctl agent skill add <agent> --from-template <registry>/<name>
clawctl agent sync <agent>
clawctl agent skill list <agent>
clawctl agent skill remove <agent> <name>
clawctl agent sync <agent>
```

The web dashboard's **Agents → `<agent>` → Skills** tab covers the
same flow.

## CI

[`skills-validate.yml`](https://github.com/ric03uec/clawrium/blob/main/.github/workflows/skills-validate.yml)
runs `scripts/validate_skills.py` plus the fixture-based unit tests on
every PR that touches the catalog. The full test suite still runs in
the main `test.yml` workflow.
