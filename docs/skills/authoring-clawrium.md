# Authoring a `clawrium/` skill

Use the `clawrium/` registry when the same behaviour should be available
on every kind of claw (openclaw, hermes, zeroclaw). The skill is
authored once in a normalized `_meta.yaml` shape; the per-claw apply
playbooks materialize the right native frontmatter at install time.

This guide walks through adding a new `clawrium/<name>/` skill end to
end. The CI validator (`scripts/validate_skills.py`) is the contract —
if your skill passes validation locally, it will pass in CI.

## 1. Pick a name

The `<name>` is a lowercase slug (hyphens and underscores both
allowed). Slug rule (enforced by the validator and by
`parse_skill_ref`):

```
^[a-z0-9][a-z0-9_-]*$
```

The directory name and `_meta.yaml`'s `name:` field MUST be identical.
This invariant is required for zeroclaw's `skills install`/`remove`
semantics (the source-dirname is what the native CLI uses on disk —
see `.itx/364/02_PHASE0_FINDINGS.md`).

## 2. Create the directory

```
skills/clawrium/<name>/
├── _meta.yaml      # required — validated against clawrium.schema.json
├── SKILL.md        # required — canonical content shipped to every claw
└── README.md       # optional — human-facing rationale, links
```

## 3. Author `_meta.yaml`

The normalized shape:

```yaml
# skills/clawrium/<name>/_meta.yaml
name: <name>              # MUST equal the directory name
description: >-
  One-line elevator pitch. Surfaces in `clawctl skill registry get` and the GUI.
version: 0.1.0            # semver (jsonschema-enforced)
license: MIT              # optional, surfaces in hermes metadata
author: clawrium          # optional
platforms: [linux, macos] # optional; informational

# Required. Maps each claw type to whether this skill can run there.
# `false` makes the install fail closed on that claw, even though
# clawrium/* is otherwise installable on any agent type.
compatibility:
  openclaw: true
  hermes: true
  zeroclaw: true

# Optional. Per-claw frontmatter overrides merged verbatim into the
# native SKILL.md on install. Use this for claw-specific metadata
# that doesn't belong in the cross-agent normalized shape.
native:
  hermes:
    metadata:
      hermes:
        tags: [tdd, testing, discipline]
  openclaw: {}
  zeroclaw: {}

# Optional. Surfaced to each claw's runtime so it can warn the user
# about a missing executable or env var before the skill runs.
prerequisites:
  commands: []
  env: []
```

Validated against `skills/_schema/clawrium.schema.json`. Unknown
top-level keys are rejected (`additionalProperties: false`).

## 4. Author `SKILL.md`

The SKILL.md is the canonical content the agent sees. The frontmatter
at the top of this file is **not** the source of truth — the apply
playbook re-renders frontmatter from `_meta.yaml` for each claw, and
the validator does not enforce SKILL.md frontmatter under `clawrium/`.
By convention, include `name:` and `description:` so the file is
readable standalone, but the body is what matters:

```markdown
---
name: <name>
description: One-line elevator pitch.
---

# Skill body

Markdown prose, examples, and any inline tool-use hints the claw should
read at runtime.
```

## 5. Validate locally

```bash
python scripts/validate_skills.py
```

Expected output on success:

```
ok: skills catalog at .../skills validates
```

If the validator reports a failure, it prints the file path and the
specific rule violated. Common ones:

| Failure message                          | Fix                                       |
|------------------------------------------|-------------------------------------------|
| `must equal directory name`              | Make `_meta.yaml.name` match the dirname  |
| `missing required _meta.yaml`            | Add the file (clawrium skills require it) |
| `missing required SKILL.md`              | Add the file alongside `_meta.yaml`       |
| `failed Clawrium normalized skill (_meta.yaml) validation` | Read the per-field message; usually a typo or wrong type |
| `violates the slug rule`                 | Rename the directory to lowercase letters, digits, `-`, `_` |

Then run the test suite:

```bash
make test
```

## 6. Smoke-test against a real claw

A clawrium-authored skill is only "done" when it installs and runs on
every claw it claims compatibility with. From a checkout pointing at
your dev fleet:

```bash
clawctl agent skill attach <openclaw-agent> clawrium/<name>
clawctl agent skill attach <hermes-agent>   clawrium/<name>
clawctl agent skill attach <zeroclaw-agent> clawrium/<name>
```

Confirm each agent's native `skills list` shows the new skill.

## 7. Open the PR

CI runs the same validator and the fixture-based unit tests. If both
pass and a maintainer reviews, the skill ships in the next release.
