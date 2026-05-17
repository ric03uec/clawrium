# Skills Catalog

<!--
  Repo-rooted docs live in docs/skills/. The user-facing site mirror
  lives at website/docs/skills/ and is a condensed variant: the two
  trees are kept semantically in sync but are not structurally
  identical (this file → intro.md; authoring-clawrium.md +
  authoring-native.md → authoring.md). Update both when changing
  catalog rules.
-->

Clawrium ships a curated catalog of **skills** that any agent in your
fleet can install with one command. A skill is a directory of
behaviour-shaping prompts and metadata that the underlying claw
discovers at runtime — Test-Driven Development discipline, code-review
guardrails, security-audit playbooks, and so on.

Skills are sourced **only** from the in-repo `skills/` tree. There is no
URL install, no arbitrary path install, no third-party registry. The
catalog is the source of truth, and CI gates every change against a
dual-schema validator (see [Authoring guides](#authoring) below).

## Quick start

```bash
# Browse the catalog
clm skill list

# Inspect a skill before installing
clm skill show clawrium/tdd

# Install onto an agent
clm agent skill install my-agent clawrium/tdd

# List skills installed on an agent
clm agent skill list my-agent

# Remove a skill
clm agent skill remove my-agent clawrium/tdd
```

The GUI mirrors the same surface under `Agents → <agent> → Skills`
and a top-level `Skills` catalog page.

## Registries

The catalog is split into four **registries** (namespaces). The split
determines which agents can install a given skill and which JSON schema
its descriptor is validated against.

| Registry   | Install target          | Schema                            |
|------------|-------------------------|-----------------------------------|
| `clawrium` | any agent type          | `_schema/clawrium.schema.json`    |
| `openclaw` | only `openclaw` agents  | `_schema/native/openclaw.schema.json` |
| `hermes`   | only `hermes` agents    | `_schema/native/hermes.schema.json`   |
| `zeroclaw` | only `zeroclaw` agents  | `_schema/native/zeroclaw.schema.json` |

Skills are referenced everywhere as `<registry>/<name>` — CLI args, GUI
URLs, and desired-state files. Bare names (`tdd`) are rejected with a
hint that suggests the matching `<registry>/<name>`.

### When to use `clawrium/`

Use the `clawrium/` registry when the skill is behaviour you want
available on **every** kind of claw. The normalized `_meta.yaml` shape
is materialized into each native frontmatter format on install — a
single source file ends up on disk as openclaw-shaped SKILL.md on an
openclaw agent, hermes-shaped on a hermes agent, and zeroclaw-shaped
(via `zeroclaw skills install`) on a zeroclaw agent.

### When to use a native registry

Use `openclaw/`, `hermes/`, or `zeroclaw/` when the skill depends on
that claw's specific frontmatter fields (e.g. hermes-only `metadata`
keys, openclaw allowed-tools lists). Native skills are installable
**only** on agents of the matching type. Attempting to install a
`hermes/<name>` skill on an openclaw agent fails with
`IncompatibleSkillRegistry`.

## Authoring

| Guide | Use when |
|-------|----------|
| [Authoring clawrium skills](authoring-clawrium.md) | Cross-agent skill — works on every claw |
| [Authoring native skills](authoring-native.md)     | Skill specific to one claw's frontmatter |

Every PR that touches `skills/` runs `scripts/validate_skills.py` in CI
([skills-validate.yml](https://github.com/ric03uec/clawrium/blob/main/.github/workflows/skills-validate.yml))
to catch:

- Slug-rule violations (path-traversal guard).
- Symlinks inside the catalog.
- Schema mismatches (a clawrium `_meta.yaml` mis-placed under a native
  registry, or clawrium-only frontmatter keys in a native SKILL.md).
- Missing required fields on `_meta.yaml` or SKILL.md frontmatter.
- The clawrium "directory name == `_meta.yaml.name`" invariant
  (required for zeroclaw's source-dirname install/remove semantics —
  see `.itx/364/02_PHASE0_FINDINGS.md`).

Run the same checks locally before pushing:

```bash
python scripts/validate_skills.py
```

## On-host materialization

| Claw     | Install location                              | Mechanism                                  |
|----------|-----------------------------------------------|--------------------------------------------|
| openclaw | `~/.openclaw/skills/<name>/SKILL.md`          | file copy (auto-scan)                      |
| hermes   | `~/.hermes/skills/clawrium/<name>/SKILL.md`   | file copy (auto-scan)                      |
| zeroclaw | `~/.zeroclaw/workspace/skills/<name>/`        | staged + `zeroclaw skills install` (audit) |

Re-running `clm agent skill install` is the recovery for drift. There
is no separate `reconcile` command — the local desired-state file at
`~/.config/clawrium/agents/<agent>/skills.json` is truth, and every
install/remove re-applies it end-to-end.
