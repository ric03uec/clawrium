# Execution — #808: macOS support for `clawctl agent shell`

## Stage Outputs

- New file: `src/clawrium/platform/shell/shell_macos.yaml` — macOS
  counterpart to `shell.yaml`. Discovers `gtimeout` (coreutils) on
  Homebrew arm64 / Homebrew x86_64 / MacPorts paths and falls back to
  plain `bash -lc` when absent.
- New file: `tests/platform/test_shell_playbook_macos.py` — static
  YAML invariants mirroring `test_shell_playbook.py`, plus assertions
  on `when:` gating, the `Merge run-task result` set_fact, and the
  `Discover gtimeout` task's `become_user`.
- Modified: `src/clawrium/core/playbook_resolver.py` — added
  `resolve_shell_playbook(os_family)` and `shell_rc_prepend(os_family)`.
  The rc-prepend helper owns the OS literal for the bash-source
  prelude so `agent_shell.py` stays OS-agnostic (dispatcher-only
  OS-fork invariant).
- Modified: `src/clawrium/core/agent_shell.py` — dropped the
  module-level `_PLAYBOOK` constant; resolves per-call via
  `playbook_resolver.resolve_shell_playbook`; deleted the darwin
  preflight short-circuit; rc-prepend is now
  `playbook_resolver.shell_rc_prepend(os_family)`; non-string
  `os_family` values fall back to "linux".
- Modified: `tests/core/test_agent_shell.py` — replaced
  `test_K20_macos_host_preflight_error` with
  `test_K20_macos_host_uses_macos_playbook`; added
  `test_K20_linux_host_uses_linux_playbook`,
  `test_unsupported_os_family_returns_255`,
  `test_non_string_os_family_falls_back_to_linux`,
  `test_darwin_rc_prepend_sources_login_files_then_bashrc`,
  `test_linux_rc_prepend_unchanged`; parametrized
  `test_iter2_B1_reserved_unix_names_rejected` across `os_family`.
- Modified: `tests/core/test_playbook_resolver.py` — added
  `TestResolveShellPlaybook` (linux / darwin / unknown OS /
  FileNotFoundError message-contains-path) and `TestShellRcPrepend`
  (linux / darwin precedence ordering / unknown OS / trailing
  semicolon).
- Modified: `CHANGELOG.md` — `### Added` entry under `[Unreleased]`.

## ATX Review History

| Iter | Rating | Blocking | Cost | Time | Agents |
|---|---|---|---|---|---|
| 1 | 3.5/5 | yes (B1) | $3.49 | 9m 55s | leader, cli-ux, test-coverage, platform-playbooks, lifecycle-core, security-reviewer |
| 2 | 4/5 | no | $3.04 | 5m 2s | leader, cli-ux, test-coverage, platform-playbooks, lifecycle-core, security-reviewer |

**Iter 1 → Iter 2 fixes:**

- B1 (lifecycle-core): inline `if os_family == "darwin":` in
  `agent_shell.py` violated dispatcher-only invariant. Fixed by
  introducing `playbook_resolver.shell_rc_prepend(os_family)` and
  routing the prelude through it.
- W1: clarified timeout-message semantics in module docstring + on the
  rc=124 emit site.
- W2: extended darwin prepend to source `.bash_profile` →
  `.bash_login` → `.profile` (first-found wins) before always-on
  `.bashrc` to match bash login-shell precedence.
- W3: added `test_P4_run_tasks_gated_by_resolved_gtimeout_length` —
  asserts the gtimeout/fallback `when:` predicates.
- W4: added `test_P5_merge_run_task_result_present_and_conditional` —
  asserts the merge set_fact references both registers + the
  `resolved_gtimeout | length` predicate.
- W5: added `test_P5_gtimeout_discovery_runs_as_agent_user` — asserts
  the discovery task's `become_user`.
- W6: tightened `test_K20_macos_host_uses_macos_playbook` to
  `endswith("/shell_macos.yaml")`.
- W7: parametrized `test_iter2_B1_reserved_unix_names_rejected` across
  `os_family in (None, "linux", "darwin")`.
- S1: guarded non-string `os_family` in `agent_shell.py`.
- S2: added `/opt/local/bin` (MacPorts) to the gtimeout discovery PATH.
- S3: dropped redundant `|| true` from the gtimeout discovery shell.
- S6 (test-coverage): added
  `test_unsupported_os_family_returns_255` and
  `test_file_not_found_message_includes_resolved_path`.

## Verification

- `make lint`: ✅ ruff + ESLint clean
- `make test`: ✅ 4031 passed, 8 skipped (Python) + 305 passed (frontend)
- Real-host: ⚠ `mac-test` (100.120.88.97) offline at run-time — not
  in `tailscale status`, SSH connect timeouts. Operator approved
  substituting `esper-mac-oc` on `esper-macmini`
  (espers-mac-mini.tailf7742d.ts.net, darwin/arm64).

### Smoke list on `esper-mac-oc` (espers-mac-mini, darwin/arm64)

| # | Command | Expected | Observed |
|---|---|---|---|
| 1 | `agent shell esper-mac-oc -- ls -la ~/` | listing of `/Users/esper-mac-oc`, rc=0 | ✅ listing rendered, rc=0 |
| 2 | `agent shell esper-mac-oc -- 'echo $HOME'` | `/Users/esper-mac-oc`, rc=0 | ✅ `/Users/esper-mac-oc`, rc=0 |
| 3 | `agent shell esper-mac-oc -- 'echo $PATH'` | shims if `.bash_profile` exports them | ✅ `/usr/bin:/bin:/usr/sbin:/sbin` (no operator shims on host) |
| 4 | `agent shell esper-mac-oc --timeout 2 -- 'sleep 60; echo neverreached'` | rc=124, stderr non-empty | ✅ rc=124, stderr `remote command timed out after 2s` (fallback path: host has no gtimeout, runner kill backstop fired at ~32s) |
| 5 | `agent shell esper-mac-oc -- 'echo "{{ lookup(env,HOME) }}"'` | literal echo, no Jinja expansion | ✅ `{{ lookup(env,HOME) }}` literal, rc=0 |
| 6 | `agent shell esper-mac-oc -- false` | rc=1 | ✅ rc=1 |

Note for #4: the substitute host has no `gtimeout`. Smoke #4 with
`sleep 5` returned rc=0 because the inner `bash -lc` finished before
the runner-level backstop at `2 + 30 = 32s` fired — exactly the
documented "wider kill window" behavior. The smoke was re-run with
`sleep 60`, which exceeds the backstop and exits via the rc=124 path.
On hosts with coreutils installed (`brew install coreutils`), the
inner `gtimeout` fires at the exact `effective`s mark.

## Prompt Log

### Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-06-24T16:25:00Z
**Model**: claude-opus-4-7

```prompt
808 - macOS support for `clawctl agent shell`. Execute plan at
.itx/808/00_PLAN.md end-to-end with operator overrides: atx CLI
review (not MCP), no git push / no PR, mac-test smoke list,
TaskCreate-driven progress, dispatcher-only OS-fork, new commits
never amends.
```

**Output**: Implementation merged into `worktree-issue-808`; two ATX
review iterations (3.5/5 → 4/5, no blockers); smoke list verified on
substitute mac host (`esper-mac-oc`, espers-mac-mini, darwin/arm64).
