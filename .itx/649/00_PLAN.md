# Implementation Plan — Issue #649

**Title**: User can `git push` from a hermes or openclaw agent without manual `gh auth setup-git`
**Type**: bug
**Base**: origin/main @ `fd9e72f` (verified — worktree HEAD matches)
**Status**: NOT stale — bug still present on current main.

## Overview

Zeroclaw's `configure.yaml` runs `gh auth setup-git` after `gh auth login --with-token`, which writes git's `credential.helper` entry into `~/.gitconfig`. Hermes and openclaw configure playbooks are missing that step, so on those agents `gh auth login` succeeds but raw `git push` over HTTPS fails with:

```
fatal: could not read Username for 'https://github.com': No such device or address
```

Fix: replicate the `gh auth setup-git` task from
`src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml:213-231`
into the hermes and openclaw configure playbooks (Linux + macOS siblings where the parallel `gh auth login` task already exists).

## Drift check vs. current main

Verified against `fd9e72f`:

| Claim in issue | Current-main reality |
|---|---|
| Zeroclaw has `gh auth setup-git` block | ✅ Present at `zeroclaw/playbooks/configure.yaml:223` |
| Hermes configure lacks setup-git | ✅ Confirmed. `hermes/playbooks/configure.yaml` renders `gitconfig` (L141) and runs `gh auth login` (L186) but has NO `setup-git` follow-up |
| Openclaw configure lacks setup-git | ✅ Confirmed. `openclaw/playbooks/configure.yaml` renders `gitconfig` (L97) and runs `gh auth login` (L142) but has NO `setup-git` follow-up |
| Issue proposes to mirror shared `gitconfig.j2` block too | ⚠️ Already present on both hermes and openclaw for Linux AND macOS. Only the `setup-git` task is actually missing. Plan below narrows to that. |

Additional gap discovered while auditing (in scope for parity, not called out in the issue):

- `openclaw/playbooks/configure_macos.yaml:143-173` has its own `gh auth login` block but no `setup-git` — same bug on macOS openclaw.
- `hermes/playbooks/configure_macos.yaml` has **no** `gh auth login` block at all (only the gitconfig template render). This is a pre-existing gap wider than #649. Plan proposes to note this in the issue and defer to a follow-up (rather than balloon scope), because it requires porting the full auth block, not just adding one task.
- `openclaw/playbooks/configure.yaml:135-149` invokes gh via `{{ gh_check.stdout }}` (older pattern) while zeroclaw and hermes use the bare `gh` argv form. The `setup-git` task added here should match its host playbook's existing convention (use `{{ gh_check.stdout }}` on openclaw Linux, bare `gh` on hermes; `{{ gh_check.stdout | trim }}` on openclaw macOS) so the new task fits the file it lives in.

## Files to Modify

| File | Change |
|---|---|
| `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` | After the "Authenticate gh CLI for each github integration" task inside the existing `GitHub CLI authentication block` (~L186), add a `Configure git credential helper via gh auth setup-git` task mirroring zeroclaw L213-231. Use bare `gh` argv (matches hermes/zeroclaw style). |
| `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml` | Same shape, appended after the auth task (~L149). Invoke via `{{ gh_check.stdout }}` to match the sibling openclaw task's existing argv form. |
| `src/clawrium/platform/registry/openclaw/playbooks/configure_macos.yaml` | Same shape, appended after the auth task (~L173). Invoke via `{{ gh_check.stdout | trim }}` and guard on `(gh_check.stdout | trim) | length > 0` to match sibling. |
| `CHANGELOG.md` | Add entry under `## [Unreleased]` → `### Fixed` referencing #649. |
| `tests/test_gitconfig_render_task.py` **or** new `tests/test_gh_setup_git_task.py` | Add YAML-parse assertion that a task named exactly `Configure git credential helper via gh auth setup-git` exists in each of the three configure playbooks above and is gated on the presence of a `github` integration + `gh_check.rc == 0` (or macOS stdout-length variant). Mirrors existing structural check in `tests/test_gitconfig_render_task.py`. |

**Explicitly out of scope for #649** (to be tracked as follow-ups if desired):
- Adding the entire `gh auth login` block to `hermes/playbooks/configure_macos.yaml`.
- Normalizing openclaw's `{{ gh_check.stdout }}` invocation to the bare-`gh` argv form used elsewhere.

## Steps

1. **Hermes Linux** — In `hermes/playbooks/configure.yaml`, inside the `GitHub CLI authentication block`, append after the `Authenticate gh CLI for each github integration` task:
   ```yaml
   - name: Configure git credential helper via gh auth setup-git
     ansible.builtin.command:
       argv:
         - gh
         - auth
         - setup-git
     become: yes
     become_user: "{{ agent_name }}"
     changed_when: false
     when:
       - gh_check.rc == 0
       - integrations | dict2items
         | selectattr('value.type', 'equalto', 'github')
         | list | length > 0
   ```
   Rationale: identical to zeroclaw L223-231 (bare `gh`, no `no_log` — the command takes no secrets).

2. **Openclaw Linux** — Same task appended in `openclaw/playbooks/configure.yaml` after L149. Change the first argv element to `"{{ gh_check.stdout }}"` so it matches the sibling `Authenticate gh CLI` task in the same file. Keep the same `when` guard.

3. **Openclaw macOS** — Same task appended in `openclaw/playbooks/configure_macos.yaml` after L173. Use `"{{ gh_check.stdout | trim }}"` for argv[0] and guard as:
   ```yaml
   when:
     - (gh_check.stdout | trim) | length > 0
     - integrations | dict2items
       | selectattr('value.type', 'equalto', 'github')
       | list | length > 0
   ```
   to match sibling conventions.

4. **Structural test** — Add / extend a pytest that parses each of the three YAML files with `yaml.safe_load` and asserts:
   - A task with `name == "Configure git credential helper via gh auth setup-git"` exists.
   - `become: yes` and `become_user: "{{ agent_name }}"`.
   - `changed_when: false`.
   - `when:` list contains a `gh_check` guard AND a selectattr on `value.type == 'github'`.
   - Task ordering: the `setup-git` task appears **after** the `gitconfig` template task and **after** the `Authenticate gh CLI` task in each file (order matters per zeroclaw comment — reversing template render vs. setup-git drops `credential.helper`; here the `credential.helper` is written by `setup-git` and only survives because template runs first).

5. **CHANGELOG** — Under `## [Unreleased]` → `### Fixed`:
   ```
   - hermes and openclaw agents now run `gh auth setup-git` after `gh auth login` during configure, so `git push` over HTTPS works out of the box when a `github` integration is attached (#649).
   ```

6. **Real-host UAT** (required per memory `feedback_no_pr_without_real_host_uat`):
   - Pick one hermes host (e.g., an existing wolf-* / test host) and one openclaw host. Attach `github` integration with a valid token. Run `clawctl agent configure <name>` then, in a working directory on the agent host, run `git clone https://github.com/<owner>/<private-repo>.git && cd <repo> && git commit --allow-empty -m test && git push`. Push must succeed with no interactive prompt.
   - macOS UAT: run the openclaw-macos flow on `mac-test` (100.120.88.97, per memory `mac_test_host`). Same push assertion.
   - Record host names + observed behavior in the PR body.

7. **`make lint && make test`** — must pass before PR (per memory `feedback_run_make_lint_before_push`).

## Test Strategy

- **Unit / structural**: YAML-parse assertion in `tests/` (Step 4) fails if any of the three files loses the task or its ordering — protects against future refactors silently dropping the fix.
- **Playbook-level idempotency**: `gh auth setup-git` is documented as idempotent by upstream `gh`; second run overwrites the same `credential.helper` line. `changed_when: false` normalizes reporting.
- **Real-host UAT**: mandatory per project convention. Covers the actual customer outcome ("`git push` works").
- **Regression on non-github integrations**: the `selectattr('github')` guard means agents without a github integration never invoke `gh` — the task is a strict no-op. Verified structurally by the test in Step 4.

## Risks / Notes

- **Task ordering invariant**: `gitconfig.j2` template render MUST stay ahead of `gh auth setup-git`, because Ansible's `template:` overwrites the whole file while `setup-git` appends. This is already the case (gitconfig at L141/L97 vs. auth block later), and the test in Step 4 asserts it — but any future refactor that reorders these tasks will silently regress #649. The test is the guardrail.
- **Openclaw argv drift**: openclaw's existing `Authenticate gh CLI` uses `{{ gh_check.stdout }}` while zeroclaw and hermes use the bare `gh` string. The plan preserves the file-local convention rather than mass-normalizing (out of scope for #649); a follow-up issue could normalize.
- **Hermes macOS gap**: mentioned above. Not addressed here because the fix requires porting the full auth block (which the issue does not ask for) and would enlarge the surface materially. Recommend opening a follow-up issue titled "hermes configure_macos.yaml missing gh auth login block" if the maintainer wants parity.
- **No BREAKING**: pure additive; agents without a `github` integration are unaffected.
- **No new secrets**: `gh auth setup-git` reads gh's existing config; the task takes no stdin and prints no token. `no_log` not needed and intentionally omitted (matches zeroclaw).

## Subtasks

None — single-task execution. Three near-identical Ansible edits + one structural test + CHANGELOG entry + real-host UAT are within one PR.

---

<details>
<summary>Prompt Log</summary>

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Planning ONLY for issue #649. Do NOT execute or write any implementation code.

Steps:
1. Fetch latest main and confirm this worktree is at origin/main HEAD (git fetch origin main && git log -1 --oneline).
2. Read the GitHub issue in full: gh issue view 649 --json number,title,body,labels,comments.
3. Read the codebase against the LATEST main to verify every file/symbol referenced in the issue still exists and behaves as the issue describes. Flag any drift (renames, moves, already-fixed behavior, changed structure) BEFORE proposing anything.
4. Invoke the /itx:plan-create skill to produce the plan artifact at .itx/649/00_PLAN.md.
5. Stop after writing the plan. Do NOT commit, do NOT push, do NOT open a PR, do NOT run /itx:execute. The user will trigger execution manually.

If the issue is stale relative to current main (already fixed, refactored away, no longer applicable), say so in the plan and stop.
```

**Output**: `.itx/649/00_PLAN.md` — implementation plan for adding `gh auth setup-git` to hermes and openclaw configure playbooks (Linux + openclaw macOS). Issue is NOT stale; single-task PR; real-host UAT required on both hermes and openclaw (Linux + macOS via mac-test).

</details>
