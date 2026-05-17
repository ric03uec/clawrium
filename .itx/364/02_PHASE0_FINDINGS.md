# Issue #364 — Phase 0 Findings (Research + Test-Fleet Stand-Up)

Empirical verification of the four assumptions in `00_PLAN.md` before
implementing phases 1–6 of the Skills Registry. Numbers below come from
`ansible-playbook` probes against the shared test fleet on host `wolf-i`
(192.168.1.36), not from documentation.

## Openclaw discovery mode

**Answer: AUTO-SCAN.** A clawrium-managed skill is discovered by
openclaw v2026.3.13 simply by materializing
`~/.openclaw/skills/<name>/SKILL.md` on the host. No `openclaw.json`
re-render is required.

Empirical probe (against running `wolf-i` openclaw agent):

1. Wrote `/home/wolf-i/.openclaw/skills/clawrium-phase0-probe/SKILL.md`
   with minimal Anthropic-spec frontmatter (`name`, `description`).
2. `openclaw skills list` immediately reported:
   ```
   │ ✓ ready │ 📦 clawrium-phase0-probe │ Phase 0 user-scan probe … │ openclaw-managed │
   ```
3. `openclaw skills info clawrium-phase0-probe` resolved to
   `Source: openclaw-managed`, `Path: ~/.openclaw/skills/clawrium-phase0-probe/SKILL.md`.

This matches the *user-extensible* source classification the openclaw
CLI exposes:
- `openclaw-bundled` — shipped with the npm package at
  `/usr/local/lib/nodejs/.../node_modules/openclaw/skills/<name>/SKILL.md`
- `openclaw-managed` — auto-discovered from `~/.openclaw/skills/<name>/`

Implication for `Q2` in the plan: **drop the `re-render openclaw.json`
step.** The openclaw `skills_apply.yaml` playbook only needs a file copy
to `~/.openclaw/skills/<name>/`. The optional `agents.defaults.skills`
field in `openclaw.json.j2` (template lines 28–32) gates enablement when
present but is **not required** for discovery; if absent, every
discovered skill is available. Both production openclaw agents on
`wolf-i` (`wolf-i`, `maurice`) currently run with no `skills` field in
their `openclaw.json`, confirming the field is optional.

This fork ships **no `openclaw skills install` / `add` subcommand** —
only read-only `check`, `info`, `list`. Skills must be placed on disk
out-of-band (which is exactly what the clawrium playbook will do).

Source-code references:
- `src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2`
  lines 28–32 (optional `skills` array under `agents.defaults`)
- `src/clawrium/platform/registry/openclaw/playbooks/install.yaml` —
  binary discovery + `openclaw.json` render
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml`
  line 89 (`# This enables openclaw's bundled github skill
  automatically`) — bundled-skill side, not user skills

## Zeroclaw on-host path + CLI

**Answer (one correction to the plan):**

| Plan assumption                       | Actual                                                        |
|---------------------------------------|---------------------------------------------------------------|
| `~/.zeroclaw/skills/<name>/`          | **`~/.zeroclaw/workspace/skills/<source-dir-name>/`**         |
| `zeroclaw skills install <path>` CLI  | confirmed                                                     |
| Native audit gate on install          | confirmed (`Security audit completed successfully`)           |
| Manifest version pin                  | `0.7.5` — matches installed binary on `tdd-zeroclaw`/`zc-test`|

Empirical probe (against `zc-test` zeroclaw v0.7.5 binary):

```
$ /home/zc-test/bin/zeroclaw --version
zeroclaw 0.7.5

$ /home/zc-test/bin/zeroclaw skills
Usage: zeroclaw skills [OPTIONS] <COMMAND>
Commands:
  list     List all installed skills
  audit    Audit a skill source directory or installed skill name
  install  Install a new skill from a URL or local path
  remove   Remove an installed skill
  test     Run TEST.sh validation for a skill (or all skills)

$ /home/zc-test/bin/zeroclaw skills install /tmp/clawrium-phase0-probe-skill
Installing skill from: /tmp/clawrium-phase0-probe-skill
  ✓ Skill installed and audited:
    /home/zc-test/.zeroclaw/workspace/skills/clawrium-phase0-probe-skill
    (2 files scanned)
  Security audit completed successfully.

$ /home/zc-test/bin/zeroclaw skills list
Installed skills (1):
  clawrium-phase0-probe v0.1.0 — Phase 0 path probe (safe to remove)
```

**Behaviors the plan needs to absorb:**

1. **Materialization path is workspace-scoped.** Skills land under
   `~/.zeroclaw/workspace/skills/`, not `~/.zeroclaw/skills/`. The plan's
   "Per-claw mechanism" table, "Files to add", and the per-claw apply
   playbook need to use the workspace-scoped path. The zeroclaw native
   `list` empty-state hint confirms it:
   `mkdir -p ~/.zeroclaw/workspace/skills/my-skill`.

2. **On-disk dirname is the SOURCE directory name, not the
   `name:` frontmatter field.** Installing from
   `/tmp/clawrium-phase0-probe-skill` produced
   `~/.zeroclaw/workspace/skills/clawrium-phase0-probe-skill/`
   (kept the source dirname), even though the SKILL.md frontmatter
   declared `name: clawrium-phase0-probe`.

3. **`zeroclaw skills remove` takes the SOURCE directory name, not the
   internal `name:`.** Removing by `clawrium-phase0-probe` returned
   `Error: Skill not found`. Removing by `clawrium-phase0-probe-skill`
   succeeded.

   Operational consequence for `skills_apply.yaml`: the playbook must
   stage skills under a directory whose name matches the canonical
   `<registry>/<name>` slug (e.g., stage `clawrium/tdd` as
   `/tmp/clawrium-stage/tdd/`) and invoke `remove` with that same slug,
   not with the internal `name:` field. The two MUST be the same string
   in skills authored under `skills/clawrium/`.

4. **`audit` is a separate subcommand.** `zeroclaw skills audit <path>`
   runs the security check without installing. The plan's "native audit
   gate" is enforced on every `install` (per the success line above), so
   no separate audit step is needed in the apply playbook.

5. **Idempotency check (Q5 in plan)**: `zeroclaw skills list` returns
   the internal `name:` field, so the playbook should:
   - run `zeroclaw skills list` first
   - skip `install` if the slug appears in the list
   - call `remove <slug>` (slug == source-dirname) on uninstall

## Locked `_meta.yaml` shape for `clawrium/tdd`

Goal: one normalized cross-agent file the clawrium core reads
(`load_skill` / `validate_skill`), which is then materialized into each
native location's expected SKILL.md frontmatter on apply.

Native frontmatter requirements observed:

| Field         | OpenClaw (auto-scan)               | Hermes (auto-scan)                                                  | Zeroclaw (`skills install`)              |
|---------------|------------------------------------|---------------------------------------------------------------------|------------------------------------------|
| `name`        | required                           | required                                                            | required (frontmatter)                   |
| `description` | required                           | required                                                            | required (frontmatter)                   |
| `version`     | optional, surfaced in `skills list`| optional, present on real Hermes skills (e.g. `version: 1.1.1`)     | optional, defaults `v0.1.0` if absent    |
| `license`     | unused                             | optional (`license: MIT` on real skills)                            | unused                                   |
| `author`      | unused                             | optional                                                            | unused                                   |
| `platforms`   | unused                             | optional (`platforms: [linux, macos]`)                              | unused                                   |
| `prerequisites` | optional (env-detected)          | optional (`prerequisites.commands: [...]`)                          | optional                                 |
| `metadata.<claw>.*` | optional                     | used by Hermes for `tags`, `homepage`, `upstream_skill`             | optional                                 |

A working shape that satisfies all three when materialized:

```yaml
# skills/clawrium/tdd/_meta.yaml — clawrium-internal normalized shape.
# Phase 1 materializers transform this into per-claw SKILL.md frontmatter.
name: tdd
description: >-
  Test-Driven Development discipline. Drives a red → green → refactor
  cycle for the active task: write a failing test, make it pass with the
  minimum change, then refactor while green.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]

# Cross-agent compatibility flags consumed by core/skills.py
# check_agent_compatibility. Per the plan, clawrium/* is installable on
# any agent type; the flags below let a normalized skill opt out of a
# specific claw if it can't fulfill that claw's runtime contract.
compatibility:
  openclaw: true
  hermes: true
  zeroclaw: true

# Optional native overrides. The materializer copies the matching key
# verbatim into the per-claw SKILL.md frontmatter; absent keys produce
# minimal frontmatter (name + description + version only).
native:
  hermes:
    metadata:
      hermes:
        tags: [tdd, testing, discipline, clawrium]
  openclaw: {}
  zeroclaw: {}

# Optional. If declared, the materializer surfaces them in the SKILL.md
# frontmatter under `prerequisites:` so each claw's runtime can flag
# `missing-requirements` before invocation.
prerequisites:
  commands: []
  env: []
```

Notes on the shape:

- `name` is the **registry slug** (`<registry>/<name>` = `clawrium/tdd`),
  not a display name. This is also the on-disk directory name used by
  every claw (mandatory for the zeroclaw source-dirname semantics
  documented above).
- `compatibility` is intentionally a flat boolean map — Q4 in the plan
  is settled "strict refs"; a skill that can't run on a claw should
  *fail closed* during `check_agent_compatibility`, not silently install.
- Hermes and OpenClaw consume the same `name`/`description`/`version`
  triple; everything else is optional. The shape is conservative — it
  ships only the union of what's needed; extension via `native.*` is the
  designated growth path.

This document **does not** introduce a `skills/clawrium/tdd/_meta.yaml`
file on disk. Per the plan's Phase 0 contract, only the *shape* is
locked here; Phase 1 will add the actual file plus the JSON schemas
under `skills/_schema/`.

## Test fleet on shared host

**Host (operator-managed):** `wolf-i` (alias) / `192.168.1.36`.
A dedicated `smoke` host alias was not created — the operator-managed
host `wolf-i` is reused as the shared test host for #364.

**Agent names recorded for downstream phase reuse:**

| Type     | Test agent name | Notes                                                              |
|----------|------------------|--------------------------------------------------------------------|
| hermes   | `tdd-hermes`     | running, ollama via `clm-openrouter`                               |
| openclaw | `tdd-openclaw`   | running                                                            |
| zeroclaw | `tdd-zeroclaw`   | systemd unit active; daemon component `gateway` errors at runtime  |

`clm ps` output captured immediately after install/configure/start:

```
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name         ┃ Agent Type ┃ Provider   ┃ Host   ┃ Address      ┃ Port  ┃ Version  ┃ Status                                          ┃ Installed  ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ tdd-hermes   │ hermes     │ openrouter │ wolf-i │ 192.168.1.36 │ 41151 │ 2026.5.7 │ running                                         │ 2026-05-17 │
│ tdd-openclaw │ openclaw   │ -          │ wolf-i │ 192.168.1.36 │ 40012 │ 2026.4.2 │ running                                         │ 2026-05-17 │
│ tdd-zeroclaw │ zeroclaw   │ -          │ wolf-i │ 192.168.1.36 │ -     │ 0.7.5    │ degraded (missing: LLM_PROVIDER_URL, LLM_MODEL) │ 2026-05-17 │
└──────────────┴────────────┴────────────┴────────┴──────────────┴───────┴──────────┴─────────────────────────────────────────────────┴────────────┘
```

(Pre-existing production agents on the same host — `espresso` (hermes),
`maurice` and `wolf-i` (openclaw), `zc-test` (zeroclaw) — are out of
scope for this issue and not shown.)

**`tdd-zeroclaw` partial-degradation note (downstream-fixable, not a
Phase 0 blocker):**

`systemctl status zeroclaw-tdd-zeroclaw.service` shows `active (running)`
— the daemon process is up. The `degraded` label in `clm ps` reflects
the manifest's required-secret check (`LLM_PROVIDER_URL`, `LLM_MODEL`):
the daemon log emits `ERROR zeroclaw_runtime::daemon: Daemon component
'gateway' failed: Unknown provider: default. Check README for supported
providers or run zeroclaw onboard to reconfigure.` This is the same
configure-time schema mismatch that affects the pre-existing `zc-test`
agent and is **independent of the skills-registry work**: `zeroclaw
skills install / list / audit / remove` operate against the on-disk
workspace and were verified working on the same v0.7.5 binary above,
regardless of gateway state. The zeroclaw configure-playbook ↔ v0.7.5
TOML-schema fix is a separate platform issue.

## Net plan adjustments for Phase 1+

1. **Drop `openclaw.json` re-rendering** from openclaw's
   `skills_apply.yaml`. Plain file copy to `~/.openclaw/skills/<name>/`
   is sufficient. (Plan section *Architecture decisions (locked) — 4*
   bullet for openclaw can be replaced with `copy` only.)
2. **Use `~/.zeroclaw/workspace/skills/` everywhere** the plan currently
   says `~/.zeroclaw/skills/`: tables in *Per-claw mechanism* and
   *Workflow → Remote hosts*, and the ASCII rendering box for zeroclaw.
3. **Adopt source-dirname == registry slug** as a hard rule, so
   zeroclaw `remove` arguments match the same string the playbook stages
   and the same string in the `<registry>/<name>` ref. Surface this in
   `core/skills.py` validation: reject a `clawrium/<name>` skill if its
   `_meta.yaml.name` does not equal `<name>`.
4. **Q5 (zeroclaw idempotency)** — resolve as: query `zeroclaw skills
   list`, parse the slug column, install only on diff; remove only when
   the slug is present. No probe via `--check-installed` style — the
   v0.7.5 CLI doesn't expose one.
