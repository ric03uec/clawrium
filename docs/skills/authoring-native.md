# Authoring a native skill

Use a native registry (`openclaw/`, `hermes/`, `zeroclaw/`) when the
skill depends on that claw's specific frontmatter fields and can't be
expressed in the cross-agent `clawrium/` normalized shape.

A native skill is installable **only** on agents of the matching type.
Attempting to install a `hermes/<name>` skill onto an openclaw agent
fails with `IncompatibleSkillRegistry` at the CLI/API boundary — no
silent skip, no partial install.

## When to choose native over clawrium

Choose **native** when:

- The skill needs hermes-only `metadata` keys (e.g. `tags`,
  `homepage`, `upstream_skill`).
- The skill needs openclaw-only frontmatter (e.g. `allowed-tools`).
- The skill needs zeroclaw-only fields not part of the normalized
  shape.
- The behaviour is fundamentally claw-specific (e.g. wraps a native
  CLI flag that no other claw has).

Choose **clawrium** when the behaviour is portable and you'd write the
same prose for every claw.

## Layout

```
skills/<claw>/<name>/
├── SKILL.md      # required — frontmatter is the source of truth
└── README.md     # optional
```

**No `_meta.yaml`.** A `_meta.yaml` under a native registry is a hard
failure in the CI validator — it almost always means a contributor
copy-pasted a clawrium skill into the wrong namespace.

## SKILL.md frontmatter

The frontmatter is whatever the underlying claw expects. The catalog
schemas are intentionally lenient (`additionalProperties: true`) so a
forward-compatible field added by a claw upstream doesn't immediately
break CI — but the validator still requires:

| Field         | Required | Notes                                |
|---------------|:--------:|--------------------------------------|
| `name`        | ✅       | MUST equal the directory name        |
| `description` | ✅       | One-line elevator pitch              |
| `version`     | optional | Surfaces in the claw's `skills list` |

Plus: clawrium-only keys (`compatibility`, `native`) are **rejected**
in native frontmatter. They have no meaning outside the cross-agent
shape and their presence usually signals a misplaced clawrium skill.

### openclaw example

```markdown
---
name: code-review
description: Walk a pull request and flag style issues.
version: 0.2.0
---

# Code Review

When the user pastes a diff, walk it hunk by hunk and surface…
```

### hermes example

```markdown
---
name: code-review
description: Walk a pull request and flag style issues.
version: 0.2.0
license: MIT
metadata:
  hermes:
    tags: [review, code-quality]
    homepage: https://example.com/code-review
---

# Code Review

...
```

### zeroclaw example

```markdown
---
name: code-review
description: Walk a pull request and flag style issues.
version: 0.2.0
---

# Code Review

...
```

Note: zeroclaw uses the **source directory name** as the install key
on disk. The directory name and `name:` field MUST match — the
validator enforces this.

## Validate locally

```bash
python scripts/validate_skills.py
```

The validator checks:

- Slug rule on the directory name.
- No symlinks in the skill tree.
- Frontmatter validates against the per-claw native schema.
- Frontmatter does NOT contain clawrium-only keys.
- `name:` field equals the directory name.
- No `_meta.yaml` in the skill directory.

Then run the test suite — the validator fixture tests run alongside
the rest of the suite:

```bash
make test
```

## Smoke-test against the real claw

A native skill must be installed and exercised on a real agent of the
matching type. The clawrium GUI's `Skills` tab on the agent detail
filters the installable list to `clawrium/*` + the matching `<claw>/*`,
so you can confirm the install/list/remove round-trip there as well.

## Open the PR

CI runs `scripts/validate_skills.py` plus the fixture tests in
`tests/test_validate_skills_script.py`. Both must pass.
