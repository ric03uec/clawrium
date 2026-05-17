# Issue #381 — Phase 2 Execution Log

Scope (from issue body): `clm agent skill install <hermes> clawrium/tdd`
round-trips (install → list → remove) on a real hermes agent; drift
recovery works when the file is deleted on host.

Plan reference: `.itx/364/00_PLAN.md` § *Phased execution → Phase 2*
and `.itx/364/02_PHASE0_FINDINGS.md` (hermes path = `~/.hermes/skills/
clawrium/<name>/`; auto-scan; native frontmatter shape).

## What shipped

**Core (state + apply):**

- `src/clawrium/core/skills_state.py` — desired-state CRUD.
  - State file at `${XDG_CONFIG_HOME:-~/.config}/clawrium/agents/<agent>/skills.json`.
  - `read_state`, `write_state`, `add_skill`, `remove_skill`.
  - Atomic writes (tempfile + `os.replace`), canonicalized JSON,
    validation on read + write (rejects URLs, bare names, malformed
    JSON, non-object root, non-string entries). `0o700` on the
    per-agent directory.
- `src/clawrium/core/skills.py` (extended):
  - `IncompatibleSkillRegistry(SkillError)` — new error class.
  - `check_agent_compatibility(skill, agent_type)` — clawrium/* via
    `compatibility` map (fail-closed on `false` or unknown
    agent type); native skills must match agent type exactly.
  - `materialize_for_claw(skill, claw)` — returns the (frontmatter,
    body) tuple to write on the host. clawrium/* lifts
    `name/description/version/license/author/platforms/prerequisites`
    + verbatim `native.<claw>` overrides; native skills returned as-is.
- `src/clawrium/core/skills_apply.py` — `apply_state(agent_name)`:
  - Resolves agent → host + agent_type via `core.hosts.get_agent_by_name`.
  - Loads + validates + checks compatibility for every desired ref
    BEFORE any remote I/O (no partial-apply states).
  - Materializes each skill into a private (0700) staging dir under
    `${clawrium_config}/staging/skills/<agent>-<ts>-*/`.
  - Dispatches to `platform/registry/<claw>/playbooks/skills_apply.yaml`
    via ansible-runner.
  - Always cleans up staging + runner artifacts (`inventory/`, `env/`,
    `artifacts/`) — same secret-hygiene policy as memory.py /
    lifecycle.py.
  - Phase 2 dispatches `hermes` only; `openclaw`/`zeroclaw` raise
    `SkillApplyNotSupported` until Phase 3.

**Per-claw materialization:**

- `src/clawrium/platform/registry/hermes/playbooks/skills_apply.yaml`
  - Inputs: `agent_name`, `staging_dir`, `desired_skill_names`.
  - Validates `agent_name` + every entry in `desired_skill_names`
    against the slug regex (defense-in-depth against tampered extravars).
  - Ensures `~/.hermes/skills/clawrium/` exists; lists existing
    direct children (`find depth: 1`); prunes any dir not in
    `desired_skill_names` (bounded to the clawrium-owned subtree —
    never touches other Hermes skill categories like `creative/`,
    `software-development/`, etc.).
  - Uses `ansible.builtin.copy` to materialize SKILL.md atomically
    (the module stages to a tempfile in the dest dir and renames into
    place — safe against a concurrent hermes daemon reader).

**CLI:**

- `src/clawrium/cli/agent_skill.py` — new `clm agent skill` sub-app:
  - `list <agent>` — table of installed refs from state file.
  - `install <agent> <ref>` — adds to state + re-runs apply
    unconditionally (drift recovery).
  - `remove <agent> <ref>` — removes from state + re-runs apply
    (orphan pruning).
- Wired into `clm agent` via `agent_app.add_typer(agent_skill_app,
  name="skill")` at the bottom of `src/clawrium/cli/agent.py`.

**Tests (75 new, all passing alongside the existing 2066 → 2141 total):**

- `tests/test_core_skills_state.py` (24 tests) — state file CRUD,
  canonical JSON, atomic write, hand-edited file rejection
  (URLs/bare names re-validated on read), agent-name validation.
- `tests/test_core_skills_apply.py` (21 tests) — apply_state happy
  path, empty-state apply, materialized SKILL.md frontmatter merge,
  every documented error path (invalid name, missing agent, ambiguous
  agent, unsupported claw type, missing SSH key, missing playbook
  path, runner timeout, runner failed, unreachable host), staging dir
  cleanup, runner-artifact cleanup, compatibility checks,
  materialize_for_claw, drift-recovery semantics.
- `tests/test_cli_agent_skill.py` (17 tests) — list/install/remove
  happy paths + idempotency, every documented error class rendered
  to stderr with exit 1, canonicalized state file after install/remove
  cycle.

## Verification

```
$ make test
============================ 2141 passed in 16.95s =============================
gui: 88 passed (88)

$ make lint
All checks passed!
```

## Smoke test on real hermes (tdd-hermes @ wolf-i)

The agent referenced by `.itx/364/02_PHASE0_FINDINGS.md` was reused for
the end-to-end test. Full transcript:

**1. Empty initial state.**

```
$ uv run clm agent skill list tdd-hermes
No skills installed on tdd-hermes. Try clm agent skill install tdd-hermes
clawrium/tdd.
```

**2. Install round-trip.**

```
$ uv run clm agent skill install tdd-hermes clawrium/tdd
Installed clawrium/tdd on tdd-hermes.

$ uv run clm agent skill list tdd-hermes
       Skills on tdd-hermes
┏━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┓
┃ Ref          ┃ Registry ┃ Name ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━┩
│ clawrium/tdd │ clawrium │ tdd  │
└──────────────┴──────────┴──────┘

$ cat ~/.config/clawrium/agents/tdd-hermes/skills.json
{
  "skills": [
    "clawrium/tdd"
  ]
}
```

On host (`192.168.1.36`, as user `tdd-hermes`):

```
$ ssh xclm@192.168.1.36 sudo ls -la /home/tdd-hermes/.hermes/skills/clawrium/tdd/
-rw-r--r-- tdd-hermes tdd-hermes 2047 May 17 11:27 SKILL.md
```

Materialized SKILL.md frontmatter (note the `metadata.hermes.tags`
lifted from `_meta.yaml`'s `native.hermes` override):

```
---
name: tdd
description: 'Test-Driven Development discipline...'
version: 0.1.0
license: MIT
author: clawrium
platforms:
- linux
- macos
prerequisites:
  commands: []
  env: []
metadata:
  hermes:
    tags:
    - tdd
    - testing
    - discipline
    - clawrium
---

# TDD — Test-Driven Development
…
```

**3. Drift recovery — manually delete SKILL.md on host, re-run install.**

```
$ ssh xclm@192.168.1.36 sudo rm -f /home/tdd-hermes/.hermes/skills/clawrium/tdd/SKILL.md

$ ssh xclm@192.168.1.36 sudo ls /home/tdd-hermes/.hermes/skills/clawrium/tdd/
(empty)

$ uv run clm agent skill install tdd-hermes clawrium/tdd
clawrium/tdd was already in desired state; reconciled host. Skills now
installed: clawrium/tdd.

$ ssh xclm@192.168.1.36 sudo ls /home/tdd-hermes/.hermes/skills/clawrium/tdd/
SKILL.md   # restored
```

**4. Pruning is bounded — drop a stray dir, run remove, verify outside-subtree
is untouched.**

```
$ ssh xclm@192.168.1.36 sudo mkdir -p /home/tdd-hermes/.hermes/skills/clawrium/stray-orphan

$ ssh xclm@192.168.1.36 sudo ls /home/tdd-hermes/.hermes/skills/clawrium/
stray-orphan
tdd

$ uv run clm agent skill remove tdd-hermes clawrium/tdd
Removed clawrium/tdd from tdd-hermes.

$ ssh xclm@192.168.1.36 sudo ls /home/tdd-hermes/.hermes/skills/clawrium/
(empty — both `tdd/` and `stray-orphan/` pruned)

$ ssh xclm@192.168.1.36 sudo ls /home/tdd-hermes/.hermes/skills/ | head
apple                       # upstream-bundled — untouched
autonomous-ai-agents        # upstream-bundled — untouched
clawrium                    # clawrium-managed (now empty)
creative                    # upstream-bundled — untouched
…
```

All 26 upstream-bundled Hermes skill categories (`apple`,
`autonomous-ai-agents`, `creative`, `data-science`, `devops`, `email`,
`github`, etc.) remained intact — only the clawrium-owned subtree was
reconciled.

## Design notes / non-obvious choices

1. **Validate-then-materialize-then-apply.** `apply_state` runs every
   `parse_skill_ref → load_skill → validate_skill →
   check_agent_compatibility` *before* writing a single byte of
   staging. The cost is one extra catalog walk per apply; the gain is
   that a single bad ref in the state file cannot leave the host in a
   partial-apply state.

2. **Staging dir lives under the clawrium config tree, not `/tmp`.**
   Other users on the control machine should not be able to read the
   rendered frontmatter mid-apply (it includes the full SKILL.md body
   plus any per-claw overrides). 0700 on the parent + 0700 on each
   per-agent tempdir + 0600 on the staged SKILL.md.

3. **Cleanup runs in `finally` — both staging and runner artifacts.**
   Matches the pattern in `core/memory.py` and `core/lifecycle.py`:
   ansible-runner caches inventory (which holds the SSH key path)
   under `inventory/`, and our extravars (including
   `staging_dir`) end up in `env/`. Cleaning these three subdirs
   after every apply keeps the on-disk log noise to the playbook
   stdout/stderr only.

4. **Re-validate persisted entries on read.** `read_state` re-runs
   `parse_skill_ref` over every entry in the file so a hand-edited
   `skills.json` carrying e.g. `https://evil.example/skill` surfaces
   as `ExternalSourceBlocked` on the next read — same chokepoint as
   the live install path, applied once on each read.

5. **Defense-in-depth in the playbook.** Even though every input
   (`agent_name`, each entry in `desired_skill_names`) is validated
   in Python before reaching the playbook, the YAML re-checks both
   against the same regex (`^[a-z][a-z0-9_-]{0,31}$` for agent_name,
   `^[a-z0-9][a-z0-9_-]*$` for skill names). A tampered Ansible
   inventory can therefore not escape `skills_root` via traversal.

6. **Pruning uses `find depth: 1` + set-difference.** The prune list
   is the set difference between (top-level dirs found on host) and
   (desired_skill_names). The find module is depth-bounded so we
   never even enumerate (let alone delete) anything beneath a child
   directory; this means the worst-case blast radius of the pruning
   step is "all of clawrium-managed subtree", which matches the
   product intent.

7. **`install` always re-runs apply** even when the skill was already
   in state (drift recovery). The CLI surfaces a `yellow "was already
   in desired state; reconciled host."` message so the user
   distinguishes a no-op state mutation from a fresh install. `remove`
   has the symmetric behavior — even if the ref wasn't in state,
   apply still runs so any orphan dir on the host gets pruned.

8. **Phase 2 stops at hermes.** `apply_state` for openclaw / zeroclaw
   raises `SkillApplyNotSupported` with a clear "Phase 3 adds these"
   message. The `check_agent_compatibility` logic accepts all three
   claw types so a `clawrium/*` skill in the catalog is reported as
   *compatible* with an openclaw / zeroclaw agent — only the
   materialization-and-apply layer raises until Phase 3.

## Review

ATX MCP (`mcp__atx__request_review`) was not available in this session
— only Gmail/Calendar/Drive MCP tools surfaced via ToolSearch. Falling
back to manual review with self-attestation per the
`<manual-review-requirements>` section in `AGENTS.md`. A separate ATX
review pass can be requested before merge; the test fleet
(`tdd-hermes`) remains available for re-running smoke if reviewer asks.

Self-review checklist:
- All existing tests (2066) + 75 new tests pass.
- Lint (ruff + ESLint) clean.
- No hardcoded secrets / credentials.
- Inputs validated at every layer (Python + Ansible).
- No path-traversal vectors (regex-bounded basename joins).
- Pruning bounded to clawrium-owned subtree (verified on host).
- Idempotent install/remove (verified on host).
- Drift recovery (verified on host).

## What this PR does not do

- **No openclaw / zeroclaw apply.** Phases 3 (openclaw) and 4
  (zeroclaw) add the matching `skills_apply.yaml` playbooks and
  extend the `_APPLY_PLAYBOOK_BY_CLAW` dispatch table in
  `skills_apply.py`. Until then, `clm agent skill install
  <openclaw-or-zeroclaw> …` surfaces a clear "not yet supported"
  error.
- **No GUI parity.** Phase 5 adds `/api/agents/<agent>/skills`
  routes and the agent-detail Skills tab.
- **No catalog browser improvements.** That landed in #380.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-17T11:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 381 --pr-base=issue-380-cli-skill-catalog-browse
```

Execution proceeded straight through plan → implement → test → smoke
without further user clarification. ATX MCP was unavailable; review
fell back to manual self-attestation.

</details>
