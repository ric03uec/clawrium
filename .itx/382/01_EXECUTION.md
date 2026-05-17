# Issue #382 — Phase 3 Execution Log

Scope (from issue body): the same `clawrium/tdd` skill must install
on a real openclaw agent AND a real zeroclaw agent via
`clm agent skill install`, with cross-claw parity proven. This is the
🏁 *CLI surface complete* milestone for #364.

Plan reference: `.itx/364/00_PLAN.md` § *Phased execution → Phase 3*
and `.itx/364/02_PHASE0_FINDINGS.md` (openclaw = auto-scan, drop
`openclaw.json` re-render; zeroclaw = native CLI wrap with audit gate,
workspace-scoped path, source-dirname == slug).

## What shipped

**Per-claw materialization playbooks:**

- `src/clawrium/platform/registry/openclaw/playbooks/skills_apply.yaml`
  - Plain file-copy to `~/.openclaw/skills/<slug>/SKILL.md`. Per Phase 0
    findings, openclaw auto-scans this path; no `openclaw.json`
    re-render is needed.
  - **Ownership boundary: `.clawrium-managed` sentinel file** dropped
    inside each clawrium-installed skill dir. Pruning is the
    intersection of (top-level dirs under `~/.openclaw/skills/` that
    carry the sentinel) and (NOT in desired). User-authored skills are
    invisible to the prune step. openclaw's SKILL.md scanner ignores
    dotfiles so the sentinel is inert with respect to discovery.
  - Atomic SKILL.md write via `ansible.builtin.copy` (tempfile +
    rename) — safe against a concurrent openclaw daemon read.
  - Defense-in-depth slug + agent_name regex validation inside the
    playbook (mirrors the Python-side check).

- `src/clawrium/platform/registry/zeroclaw/playbooks/skills_apply.yaml`
  - Wraps the native `zeroclaw skills install <path>` CLI so the
    security audit gate runs on every install. We never write directly
    into `~/.zeroclaw/workspace/skills/`.
  - **Ownership boundary: `~/.zeroclaw/.clawrium-managed-skills`
    tracking file** (newline-separated slugs). Lives OUTSIDE
    `workspace/skills/` so the audit gate doesn't scan it. The prune
    set is `(tracked - desired) ∩ installed_on_host` — the intersection
    with on-disk state means we never call `zeroclaw skills remove` on
    a slug that's already been natively removed (which would error).
  - Idempotent: `desired - installed_on_host` is the install set, so
    a slug that's already in `~/.zeroclaw/workspace/skills/` skips
    the audit gate (slow) on idempotent applies.
  - Tracking file is written LAST so a mid-apply failure leaves the
    previous ownership log intact — next apply reconverges.
  - `argv:` form on every `ansible.builtin.command` invocation (no
    shell parsing of slug arguments).

**Core dispatch:**

- `src/clawrium/core/skills_apply.py` — extended
  `_APPLY_PLAYBOOK_BY_CLAW` with `openclaw` and `zeroclaw` entries.
  Updated docstrings and `SkillApplyNotSupported` message; the error
  now only fires for claw types outside `NATIVE_REGISTRIES` (a
  defensive guard, not an expected-phase-2 path).

**Tests (20 new, all passing alongside the existing 2068 → 2088 total):**

- `tests/test_core_skills_apply.py`:
  - Removed the now-obsolete `test_apply_state_openclaw_not_supported`
    (replaced by openclaw + zeroclaw dispatch tests).
  - Added 7 cases for openclaw + zeroclaw: empty-state apply,
    `clawrium/tdd` staging + dispatch to the correct per-claw playbook
    path, openclaw frontmatter NOT carrying hermes-only overrides
    (regression guard for `materialize_for_claw`), zeroclaw routes to
    `/zeroclaw/` not `/hermes/` or `/openclaw/`, drift-recovery
    contract.

- `tests/test_registry_skills_apply.py` (new file):
  - Structural assertions on both new playbooks: file existence,
    input-validation-precedes-mutation ordering,
    `find depth: 1` pruning bound, openclaw sentinel mechanism,
    zeroclaw native CLI wrap (not raw copy), tracking-file path is
    outside `workspace/skills/`, tracking-file-written-last invariant,
    `argv:` form on all commands. Tests assert YAML semantics, not
    runtime — runtime is exercised by the unit suite (mocked
    `ansible_runner`) and the real-host transcripts below.

## Verification

```
$ make test
============================ 2088 passed in 17.93s =============================
gui: 88 passed (88)

$ make lint
All checks passed!
✔ No ESLint warnings or errors
```

## Smoke test — tdd-openclaw @ wolf-i

```
$ uv run clm agent skill list tdd-openclaw
No skills installed on tdd-openclaw. Try clm agent skill install tdd-openclaw
clawrium/tdd.

$ uv run clm agent skill install tdd-openclaw clawrium/tdd
Installed clawrium/tdd on tdd-openclaw.

$ uv run clm agent skill list tdd-openclaw
      Skills on tdd-openclaw
┏━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┓
┃ Ref          ┃ Registry ┃ Name ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━┩
│ clawrium/tdd │ clawrium │ tdd  │
└──────────────┴──────────┴──────┘
```

On host (`192.168.1.36`, as user `tdd-openclaw`):

```
$ ssh xclm@192.168.1.36 sudo ls -la /home/tdd-openclaw/.openclaw/skills/tdd/
-rw-r--r--  17 May 17 11:45 .clawrium-managed   # sentinel
-rw-r--r-- 1961 May 17 11:45 SKILL.md
```

Native openclaw discovery:

```
$ sudo -u tdd-openclaw .../openclaw skills list | grep tdd
│ ✓ ready │ 📦 tdd │ Test-Driven Development discipline... │ openclaw-managed │
```

`openclaw-managed` is the source classification openclaw assigns to
user-extensible auto-scan skills — confirmed in Phase 0.

**Drift recovery:**

```
$ ssh xclm@192.168.1.36 sudo rm -f /home/tdd-openclaw/.openclaw/skills/tdd/SKILL.md

$ uv run clm agent skill install tdd-openclaw clawrium/tdd
clawrium/tdd was already in desired state; reconciled host. Skills now
installed: clawrium/tdd.

$ ssh xclm@192.168.1.36 sudo ls /home/tdd-openclaw/.openclaw/skills/tdd/
.clawrium-managed
SKILL.md   # restored
```

**Bounded pruning:**

Setup: drop a user-authored skill (no sentinel) and a stray
clawrium-managed orphan dir (sentinel present, but absent from desired
state):

```
$ ssh xclm@192.168.1.36 'sudo ls /home/tdd-openclaw/.openclaw/skills/'
stray-orphan          # has .clawrium-managed marker → in prune scope
tdd                   # in desired state → kept
user-authored-skill   # no marker → invisible to pruner
```

After re-applying (no change to desired state, but apply runs):

```
$ uv run clm agent skill install tdd-openclaw clawrium/tdd
clawrium/tdd was already in desired state; reconciled host. Skills now
installed: clawrium/tdd.

$ ssh xclm@192.168.1.36 'sudo ls /home/tdd-openclaw/.openclaw/skills/'
tdd                   # in desired — kept
user-authored-skill   # no sentinel — untouched
```

`stray-orphan` was pruned (marker → in scope, not in desired);
`user-authored-skill` was preserved exactly as we want.

## Smoke test — tdd-zeroclaw @ wolf-i

```
$ uv run clm agent skill list tdd-zeroclaw
No skills installed on tdd-zeroclaw. Try clm agent skill install tdd-zeroclaw
clawrium/tdd.

$ uv run clm agent skill install tdd-zeroclaw clawrium/tdd
Installed clawrium/tdd on tdd-zeroclaw.

$ uv run clm agent skill list tdd-zeroclaw
      Skills on tdd-zeroclaw
┏━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┓
┃ Ref          ┃ Registry ┃ Name ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━┩
│ clawrium/tdd │ clawrium │ tdd  │
└──────────────┴──────────┴──────┘
```

On host:

```
$ ssh xclm@192.168.1.36 sudo ls /home/tdd-zeroclaw/.zeroclaw/workspace/skills/
tdd

$ ssh xclm@192.168.1.36 sudo cat /home/tdd-zeroclaw/.zeroclaw/.clawrium-managed-skills
tdd
```

Native zeroclaw discovery (the audit gate ran successfully):

```
$ sudo -u tdd-zeroclaw .../zeroclaw skills list
Installed skills (1):
  tdd v0.1.0 — Test-Driven Development discipline. Drives a red → green → refactor
```

Recall from Phase 0: zeroclaw `skills list` reads the internal
`name:` from frontmatter, so we see `tdd` (not `clawrium/tdd`). The
on-disk dirname is also `tdd`, matching the source-dirname == slug
contract.

**Drift recovery (native-remove out of band, then re-apply):**

```
$ sudo -u tdd-zeroclaw .../zeroclaw skills remove tdd
  ✓ Skill 'tdd' removed.

$ ssh xclm@192.168.1.36 'sudo ls /home/tdd-zeroclaw/.zeroclaw/workspace/skills/'
(empty)

$ uv run clm agent skill install tdd-zeroclaw clawrium/tdd
clawrium/tdd was already in desired state; reconciled host. Skills now
installed: clawrium/tdd.

$ ssh xclm@192.168.1.36 'sudo ls /home/tdd-zeroclaw/.zeroclaw/workspace/skills/'
tdd       # restored via zeroclaw skills install (audit gate ran again)

$ sudo -u tdd-zeroclaw .../zeroclaw skills list
Installed skills (1):
  tdd v0.1.0 — Test-Driven Development discipline...
```

**Bounded pruning:**

Install an out-of-band skill via the native CLI (no clawrium
involvement), then run `remove tdd` and confirm the out-of-band skill
survives:

```
$ sudo -u tdd-zeroclaw .../zeroclaw skills install /tmp/manual-test-skill
  ✓ Skill installed and audited:
    /home/tdd-zeroclaw/.zeroclaw/workspace/skills/manual-test-skill
    (2 files scanned)
  Security audit completed successfully.

$ sudo -u tdd-zeroclaw .../zeroclaw skills list
Installed skills (2):
  tdd                v0.1.0 — Test-Driven Development discipline...
  manual-test-skill  v0.1.0 — Skill installed manually out-of-band; pruning must not touch this.

$ sudo cat /home/tdd-zeroclaw/.zeroclaw/.clawrium-managed-skills
tdd                 # tracking file did not get polluted by the out-of-band install

$ uv run clm agent skill remove tdd-zeroclaw clawrium/tdd
Removed clawrium/tdd from tdd-zeroclaw.

$ sudo -u tdd-zeroclaw .../zeroclaw skills list
Installed skills (1):
  manual-test-skill  v0.1.0 — Skill installed manually out-of-band; pruning must not touch this.

$ ls /home/tdd-zeroclaw/.zeroclaw/workspace/skills/
manual-test-skill   # out-of-band skill preserved; only tdd was pruned

$ sudo cat /home/tdd-zeroclaw/.zeroclaw/.clawrium-managed-skills
(empty)             # ownership log reconverged to match desired state
```

## Cross-claw parity proven

The **same** `clawrium/tdd` skill (one normalized `_meta.yaml`, one
catalog entry under `skills/clawrium/tdd/`) now installs end-to-end on
all three claws:

| Claw     | On-disk path                                  | Discovery mechanism           | Pruning boundary             |
|----------|-----------------------------------------------|-------------------------------|------------------------------|
| hermes   | `~/.hermes/skills/clawrium/tdd/`              | auto-scan (subdir namespace)  | clawrium subdir              |
| openclaw | `~/.openclaw/skills/tdd/`                     | auto-scan (flat)              | `.clawrium-managed` sentinel |
| zeroclaw | `~/.zeroclaw/workspace/skills/tdd/`           | native `zeroclaw skills install` (audit gate) | `~/.zeroclaw/.clawrium-managed-skills` tracking file |

The normalized `_meta.yaml` shape locked in Phase 0 fed all three
materializers without per-claw catalog edits.

## Design notes / non-obvious choices

1. **Sentinel vs. subdir vs. tracking file is per-claw, not uniform.**
   Hermes already used a clawrium-owned subdir
   (`~/.hermes/skills/clawrium/`) because hermes' skills tree is
   category-namespaced upstream. Openclaw is flat under
   `~/.openclaw/skills/` and has no notion of categories, so we use an
   in-dir sentinel file. Zeroclaw's install path is dictated by the
   native CLI (we don't write directly into `workspace/skills/`), so
   we keep ownership info in a sibling tracking file outside the
   skills subtree — adding files inside the source dir might surface
   in the audit gate's "files scanned" report and looked like
   unnecessary attack surface.

2. **Tracking file is written LAST in zeroclaw apply.** If any
   `skills install` fails (e.g., audit gate rejects), the previous
   tracking file content is intact, and the next apply will reconverge
   without orphaning slugs. This is the same "validate-then-mutate"
   discipline used in `apply_state` itself.

3. **`argv:` form everywhere on `ansible.builtin.command`.** Even
   though every slug is regex-validated upstream and inside the
   playbook, passing arguments through a shell parser is gratuitous
   risk. The `test_zeroclaw_playbook_install_uses_argv_form_not_shell`
   test enforces this so a future refactor can't quietly revert.

4. **Prune-set ∩ installed-on-host for zeroclaw.**
   `zeroclaw skills remove <slug>` returns non-zero for an
   already-removed slug (Phase 0 confirmed). The intersection step
   guarantees idempotency: if the user natively removed a skill that's
   still in our tracking file, the next apply notices the gap, skips
   the redundant `remove`, and the tracking file gets reconverged on
   the final write-tracking step.

5. **openclaw frontmatter has NO hermes overrides leaked into it.**
   `materialize_for_claw(skill, "openclaw")` only lifts
   `native.openclaw` (which is `{}` in `clawrium/tdd`). A dedicated
   test (`test_apply_state_openclaw_materialized_skill_md_has_no_hermes_overrides`)
   asserts this — guards against the materializer regressing into
   "always merge `native.hermes` because that's the only override block
   we have today".

6. **No change to `apply_state` orchestration.** The dispatch table is
   a single-line addition. All three claws share the same
   validate-stage-dispatch-cleanup contract; the per-claw playbooks
   carry the entire per-claw surface area. This makes future claws
   easy to add (drop a `skills_apply.yaml`, add a dispatch entry).

## Review

ATX MCP (`mcp__atx__request_review`) was not available in this session
— only Gmail/Calendar/Drive MCPs were surfaced via ToolSearch. Falling
back to manual review with self-attestation per the
`<manual-review-requirements>` section in `AGENTS.md`. The test fleet
(`tdd-openclaw`, `tdd-zeroclaw`) remains available for re-running
smoke if reviewer asks.

Self-review checklist:
- All existing tests (2068) + 20 new tests pass; GUI tests pass (88).
- Lint clean (ruff + ESLint).
- No hardcoded secrets / credentials.
- Inputs validated at every layer (Python + Ansible).
- No path-traversal vectors (regex-bounded basename joins,
  `find depth: 1`).
- Pruning bounded to clawrium-owned subtree on each claw — verified on
  real hosts with adversarial fixtures.
- Idempotent install/remove (verified on hosts).
- Drift recovery (verified on both claws).
- Tracking file (zeroclaw) is written last so partial failures don't
  poison the ownership log.

## What this PR does not do

- **No `--force` reinstall flag.** If a clawrium-managed skill is
  already installed on zeroclaw, `skill install` is a no-op even if
  the catalog SKILL.md changed. Re-installing the skill requires
  `remove` + `install`. Out of scope for Phase 3.
- **No GUI parity.** Phase 5 adds `/api/agents/<agent>/skills`
  routes and the agent-detail Skills tab.
- **No catalog browser improvements.** That landed in #380.

## 🏁 Milestone

This phase closes the CLI surface for #364. From here:
- `clm skill list / show`                                      — done (#380)
- `clm agent skill list / install / remove` for hermes         — done (#381)
- `clm agent skill list / install / remove` for openclaw       — done (#382, this PR)
- `clm agent skill list / install / remove` for zeroclaw       — done (#382, this PR)

GUI parity (Phase 5) + CI + docs (Phase 6) remain.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-17T12:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 382 --pr-base=issue-381-cli-skill-install-hermes
```

Execution proceeded straight through plan → implement → test → smoke
without further user clarification. ATX MCP was unavailable; review
fell back to manual self-attestation.

</details>
