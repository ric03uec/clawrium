---
sidebar_position: 1
description: Browse and install vetted skills onto any agent in your Clawrium fleet.
keywords: [skills, registry, clawrium, openclaw, hermes, zeroclaw, install]
---

# Skills

Clawrium ships a curated **skills catalog** that any agent in your
fleet can install with one command. A skill is a directory of
behaviour-shaping prompts and metadata that the underlying claw
discovers at runtime — Test-Driven Development discipline, code-review
guardrails, security-audit playbooks.

Skills are sourced **only** from the in-repo `skills/` tree. There is no
URL install, no arbitrary-path install, no third-party registry. The
catalog is the source of truth, and every PR runs a dual-schema
validator in CI.

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

The web dashboard mirrors the same surface under **Agents → `<agent>`
→ Skills**, plus a top-level **Skills** catalog page for browse.

## Registries

The catalog is split into four **registries** (namespaces). The split
determines which agents can install a given skill and which JSON
schema its descriptor validates against.

| Registry   | Install target          | Schema                              |
|------------|-------------------------|-------------------------------------|
| `clawrium` | any agent type          | `clawrium.schema.json`              |
| `openclaw` | only `openclaw` agents  | `native/openclaw.schema.json`       |
| `hermes`   | only `hermes` agents    | `native/hermes.schema.json`         |
| `zeroclaw` | only `zeroclaw` agents  | `native/zeroclaw.schema.json`       |

Skills are referenced as `<registry>/<name>` everywhere — CLI args,
GUI URLs, desired-state files. Bare names (`tdd`) are rejected with a
hint that suggests the matching `<registry>/<name>`.

### `clawrium/` — cross-agent

Use the `clawrium/` registry when the skill is behaviour you want
available on **every** kind of claw. The normalized `_meta.yaml` shape
is materialized into each native frontmatter format at install time —
a single source file ends up on disk as openclaw-shaped SKILL.md on an
openclaw agent, hermes-shaped on a hermes agent, and zeroclaw-shaped
(via `zeroclaw skills install`) on a zeroclaw agent.

### `openclaw/`, `hermes/`, `zeroclaw/` — native

Use a native registry when the skill needs that claw's specific
frontmatter fields. Native skills are installable **only** on agents
of the matching type — `clm agent skill install` fails fast if you try
to mix them.

## On-host install path

| Claw     | On-host location                              | Mechanism                                  |
|----------|-----------------------------------------------|--------------------------------------------|
| openclaw | `~/.openclaw/skills/<name>/SKILL.md`          | file copy (auto-scan)                      |
| hermes   | `~/.hermes/skills/clawrium/<name>/SKILL.md`   | file copy (auto-scan)                      |
| zeroclaw | `~/.zeroclaw/workspace/skills/<name>/`        | staged + `zeroclaw skills install` (audit) |

:::note
The `~` above is the **agent unix user's** home, not the operator's.
Each agent installed via `clm agent install` runs as its own dedicated
user named after the agent (so an agent named `tdd-hermes` runs as
user `tdd-hermes` with files under `/home/tdd-hermes/`). To SSH-verify
after install, switch users on the remote host with
`sudo -u <agent-name> ls /home/<agent-name>/...`.
:::

Re-running `clm agent skill install` is the drift recovery — the local
desired-state file at
`~/.config/clawrium/agents/<agent>/skills.json` is the source of truth,
and every install/remove re-applies it end-to-end. There is no separate
`reconcile` command.

## Troubleshooting

### Install reports success but the file isn't where I expect

Common pitfall — the `~` in the on-host paths is the **agent user's**
home, not yours. When verifying via SSH:

```bash
# Wrong — checks the management user's home
ssh wolf-i 'ls ~/.hermes/skills/clawrium/tdd/'

# Right — switch to the agent user
ssh wolf-i 'sudo -u tdd-hermes ls /home/tdd-hermes/.hermes/skills/clawrium/tdd/'
```

### `clm agent remove` leaves the skill state file behind

Known limitation: `~/.config/clawrium/agents/<name>/skills.json` is
left behind when you `clm agent remove <name>`. Harmless on re-install
(the file contains an empty array) but clean it explicitly if you want
a clean slate:

```bash
rm -rf ~/.config/clawrium/agents/<name>
```

## Authoring

See the [authoring guide](authoring.md) for the full step-by-step on
adding a new skill to the catalog. The short version:

1. Pick a registry (`clawrium/` if cross-agent, otherwise the native
   registry).
2. Create `skills/<registry>/<name>/` with `SKILL.md` (and `_meta.yaml`
   for `clawrium/`).
3. Run `python scripts/validate_skills.py` locally.
4. Open a PR. CI re-runs the validator on every push.

## CI safety net

The
[`skills-validate.yml`](https://github.com/ric03uec/clawrium/blob/main/.github/workflows/skills-validate.yml)
workflow runs on every PR that touches the catalog. It catches:

- **Path-traversal**: directory names that violate the slug rule,
  symlinks inside the tree, unexpected top-level files/dirs.
- **Schema mismatch**: a clawrium `_meta.yaml` mis-placed under a
  native registry, or clawrium-only frontmatter keys in a native
  SKILL.md.
- **Missing required fields** on `_meta.yaml` or SKILL.md frontmatter
  (per-registry JSON schema).
- The clawrium "directory name == `_meta.yaml.name`" invariant —
  required so that zeroclaw's source-dirname install/remove semantics
  stay consistent with the registry slug.

Run the same checks locally before pushing:

```bash
python scripts/validate_skills.py
```
