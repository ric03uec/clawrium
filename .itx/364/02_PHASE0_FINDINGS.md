# Issue #364 — Phase 0 Findings (Research + Test-Fleet Stand-Up)

Empirical verification of plan-table items **Q2** (openclaw discovery)
and **Q5** (zeroclaw idempotency) from `00_PLAN.md`, plus a worked
proposal for the normalized `_meta.yaml` shape (Q1 / Q3 / Q4 remain
locked as the plan states). Section 1 ("Openclaw") and section 2
("Zeroclaw") are empirical — `ansible-playbook` output against host
`wolf-i` (192.168.1.36). Section 3 (`_meta.yaml`) is a **design
proposal**: no `_meta.yaml` files exist in the codebase yet; the shape
will be validated at Phase 1 schema-implementation time.

## Executive summary — net plan adjustments for Phase 1+

Pulled to the top because every Phase-1 reader needs these.

1. **Drop `openclaw.json` re-rendering** from openclaw's
   `skills_apply.yaml`. Plain file copy to `~/.openclaw/skills/<name>/`
   is sufficient. Leave the `{% if config.skills … %}` conditional in
   `openclaw.json.j2` lines 28–32 **in place** — it's an optional
   enablement gate, not part of the discovery path — only the planned
   playbook re-render task is removed.
2. **Use `~/.zeroclaw/workspace/skills/` everywhere** the plan currently
   says `~/.zeroclaw/skills/`. This PR also patches the two stale path
   references in `00_PLAN.md` (mermaid box + ASCII rendering box).
3. **Adopt source-dirname == registry slug == `_meta.yaml.name`** as a
   hard invariant enforced at `core/skills.py` validation time.
   `zeroclaw skills list` returns the internal `name:` field, but
   `zeroclaw skills remove` takes the *source directory name* — these
   two strings only coincide when the invariant holds. Without it, the
   idempotency algorithm in Phase 3 silently mis-removes skills.
4. **Q5 (zeroclaw idempotency)** — resolve as: query `zeroclaw skills
   list`, parse the slug column, install only on diff; remove only when
   the slug is present. No probe via `--check-installed` style — the
   v0.7.5 CLI doesn't expose one. Openclaw and Hermes don't need an
   equivalent guard — both materialize via Ansible's `copy` module
   (declarative; same source ⇒ no-op), so the list-first diff is a
   zeroclaw-only concern driven by the native CLI's side-effects.
5. **`skills_remove.yaml` cross-claw asymmetry**: zeroclaw removes
   take the source-dirname, while openclaw/hermes remove by deleting
   the directory at `<scan-path>/<name>/`. With the invariant in (3),
   these are the same string; **without** it, a native skill's
   on-disk dir name and `name:` frontmatter could diverge and the
   remove playbook must not assume they match for non-`clawrium/`
   skills.
6. **Phase 1 prerequisites the plan didn't surface**: extend
   `core/registry.py` `AgentManifest` TypedDict with an optional
   `skills` field (currently has `agent`, `platforms`, `secrets`,
   `onboarding`, `workspace`, `features` — no `skills`), and
   create-on-first-use `~/.zeroclaw/workspace/skills/` (zeroclaw's
   `install.yaml` scaffolds `workspace/` but not the `skills/`
   subdirectory). On first reconcile against an agent with no prior
   `skills.json` desired-state, the playbook must run **add-only** —
   pruning activates only after the first reconciled state file exists,
   so pre-existing user-authored skills on `zc-test`-style agents are
   never silently wiped.
7. **`nemoclaw` is out of Phase 1 scope.** The proposed `_meta.yaml`
   `compatibility` map intentionally lists only openclaw, hermes,
   zeroclaw — `nemoclaw` exists in the registry but is not part of the
   #364 v1. Add it in a follow-up issue if/when needed.

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

All zeroclaw probes below ran against the **pre-existing `zc-test`
agent** (zeroclaw v0.7.5, same binary as the newly-installed
`tdd-zeroclaw`). `zc-test` was chosen because its daemon was already
up and the `skills` subcommand operates against the on-disk workspace,
which is independent of gateway state — running the probe on the
degraded `tdd-zeroclaw` would have produced identical results.

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

   The algorithm above is **only safe when** the invariant
   `slug == source-dirname == _meta.yaml.name` holds. `list` reports
   the internal name; `remove` accepts the source-dirname; these two
   strings are forced equal by adjustment (3) in the executive summary
   and enforced at `core/skills.py` validation. A `clawrium/<name>`
   skill whose `_meta.yaml.name` differs from `<name>` must be rejected
   at load time, otherwise the install/skip/remove cycle silently
   corrupts the desired-state file. State this invariant explicitly in
   `validate_skill()` error messages.

## Phase 1 code-inspection prerequisites

Three Phase-1 prerequisites that don't fall out of the playbook
behavior probes above, but are visible in the current codebase. Each
is verifiable by reading the cited file at the cited line range.

1. **`AgentManifest` TypedDict has no `skills` field.**
   `src/clawrium/core/registry.py` defines `AgentManifest` with keys
   `agent`, `platforms`, `secrets`, `onboarding`, `workspace`,
   `features` — no `skills`. Phase 1 must either (a) extend
   `AgentManifest` with an optional `skills` field, or (b) keep agent
   manifests untouched and load skill catalog state via a parallel
   `_meta.yaml`-driven path under `core/skills.py`. Plan section
   *Files to add / modify → Core* implies (b); call the choice
   explicitly when Phase 1 opens.
2. **`~/.zeroclaw/workspace/skills/` is not scaffolded by zeroclaw's
   `install.yaml`.** The playbook creates the workspace directory and
   the seven personality templates (SOUL/IDENTITY/USER/AGENTS/TOOLS/
   MEMORY/HEARTBEAT) but stops there. The `skills/` subdirectory is
   created on demand by `zeroclaw skills install` on first use (probe
   in §2 above corroborates: no `skills/` existed under `zc-test`
   workspace pre-install, was present post-install). Phase 3's
   `zeroclaw/playbooks/skills_apply.yaml` must therefore tolerate
   missing-directory state and not assume the dir exists before the
   first skill is staged.
3. **First reconcile against an agent with no `skills.json`
   desired-state must be add-only.** Plan section *Architecture
   decisions (locked) — 3* declares "Local desired-state is truth" and
   *— 5* declares "Pruning is bounded to a clawrium-owned subtree per
   claw." A naive Phase-3 implementation would treat a missing
   desired-state file as "desired = []" and **prune everything** in
   the clawrium-owned subtree on first run. Agents like `zc-test` (or
   any agent the user managed pre-registry) may carry skill files
   inside paths the registry will later claim. The mitigation is to
   distinguish *first reconcile* (no `skills.json` exists yet) from
   *subsequent reconciles*; first reconcile writes the desired-state
   file from a scan of what's already on disk in clawrium-owned
   paths, then exits without pruning. Phase 3 design must include
   this branch.

## Proposed `_meta.yaml` shape for all `clawrium/` skills

**This section is a design proposal, not an empirical finding.** No
`_meta.yaml` files exist anywhere in the codebase yet. The shape below
is grounded in observed native-frontmatter requirements (probed
empirically and tabulated below), but its final validation lands at
Phase 1 schema implementation. Treat the YAML at the end of this
section as the *starting point* for Phase 1, not a frozen contract.

The Hermes column in the table below comes from **runtime observation**
of an installed Hermes skill (`/home/espresso/.hermes/skills/social-media/xurl/SKILL.md`),
not from registry source — there is currently no skill-related
infrastructure under `src/clawrium/platform/registry/hermes/`. The
frontmatter shape there is the de-facto Hermes convention; Phase 1
should re-confirm against the Hermes runtime if the materializer
output drifts.

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

# Cross-agent compatibility flags. To be consumed by a Phase 1
# `check_agent_compatibility()` function in core/skills.py — not yet
# implemented; Phase 1 introduces it. Per the plan, clawrium/* is installable on
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

`systemctl status zeroclaw-tdd-zeroclaw.service` shows
`active (running)` — the daemon process is up. The `degraded` label in
`clm ps` comes from the manifest's required-secret check
(`secrets.required: [LLM_PROVIDER_URL, LLM_MODEL]` in
`zeroclaw/manifest.yaml`); the daemon log separately emits
`ERROR zeroclaw_runtime::daemon: Daemon component 'gateway' failed:
Unknown provider: default.` There are **two distinct issues** mashed
together by `clm ps` here:

- **Secret contract mismatch (the cause of the `degraded` label):**
  the manifest declares `LLM_PROVIDER_URL` and `LLM_MODEL` as required
  secrets, but the configure playbook writes provider values into
  `~/.zeroclaw/config.toml` via the `[providers.models.<type>]` TOML
  block. The systemd unit emits no `EnvironmentFile` for the agent
  account, so those keys never reach the daemon as env vars. The
  manifest's required-secrets contract and the configure playbook's
  TOML-output contract are unaligned.
- **Daemon-side schema mismatch (the cause of the daemon-log `ERROR`):**
  the configure playbook writes `default_provider = "ollama"` and a
  `[providers.models.ollama]` block, but zeroclaw v0.7.5's runtime
  looks up `[providers.models.default]` (literal `default`). So even
  if the secret contract is fixed, the daemon would still fail.

Both are pre-existing platform issues (same failure on `zc-test`),
**independent of the skills-registry work**. `zeroclaw skills install
/ list / audit / remove` operate against the on-disk workspace and
were verified working on the same v0.7.5 binary above, regardless of
gateway state. **Implication for Phase 1 testing:** route the
end-to-end skill-install integration tests against `tdd-zeroclaw` using
the skills CLI directly (workspace path is reachable); end-to-end
*agent-uses-skill* tests must wait until the configure ↔ v0.7.5
alignment lands. Track the underlying fix as a separate issue.

## Where Phase 1 picks this up

`00_PLAN.md` in this same PR has been patched for the two stale
zeroclaw path references (mermaid + ASCII boxes). The seven-point
executive summary at the top of this document is the canonical
Phase-1 hand-off list — open it side-by-side with `00_PLAN.md` § *Files
to add / modify* when the Phase 1 issue opens.

**Phase 1 integration tests** should target `wolf-i` (alias unchanged)
with `tdd-{hermes,openclaw}` for end-to-end install/list/remove flows;
`tdd-zeroclaw` covers the skills-CLI path only until the configure ↔
v0.7.5 alignment fix lands separately.
