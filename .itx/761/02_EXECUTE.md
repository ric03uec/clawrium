# Issue #761 — Execution Log

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-06-20T23:23:14Z
**Model**: claude-opus-4-7

```prompt
761 — execute per .itx/761/00_PLAN.md. Use the ATX CLI (atx review) for
the review loop, NOT the MCP tool; the user explicitly requested CLI
review. Persist .itx/761/atx-session.json across iterations. Open PR
against main when ready.
```

**Output**: implementation of `clawctl agent shell <name> -- <cmd>` per
plan §1/§2. Self-contained core (`core/agent_shell.py`), CLI seam
(`cli/clawctl/agent/shell.py`), single Linux playbook
(`platform/shell/shell.yaml`), and three test files (CLI / core /
platform). Three ATX CLI review iterations resolved 7 blockers and
9 warnings; one architectural blocker (macOS dispatcher pattern)
intentionally deferred to the macOS subissue per plan §1 scope lock.

## ATX Review Session

State persisted across iterations at `.itx/761/atx-session.json`.

| Iter | Rating | Blocking | Blockers | Cost (USD) | Duration |
|------|--------|----------|----------|------------|----------|
| 1    | 2/5    | true     | 2        | $5.02      | 553s     |
| 2    | 3/5    | true     | 5        | $4.45      | 435s     |
| 3    | 3/5    | false    | 1 deferred | $3.74    | 390s     |

Total: $13.20, 23min.

### Iter 1 → fixes

- B1: `shlex.join(['ls -la ~/'])` broke single-element argv → switched to ssh-style `' '.join(cmd_argv)`.
- B2: macOS hosts had no preflight → core returns clean Linux-only error when `host.os_family == 'darwin'`.
- W1: Ansible Jinja sub-injection on cmd_str → base64 hop (Python encodes, playbook decodes inline via `| b64decode`); no plain `cmd_str` reaches the templater.
- W4–W8 covered with new test cases (macOS preflight K20, Jinja W1, failure-msg branches, traversal alias defense, kill-after-5 / SHELL_* prefix contracts).

### Iter 2 → fixes

- B1: reserved unix names (root, daemon, …) bypassed regex → applied `RESERVED_UNIX_NAMES` denylist in core + CLI seams.
- B2: inner `rc=124` synthetic-timeout message masked legitimate apps' exit 124 → dropped that mapping; only `runner.status == 'timeout'` (K5) produces the friendly message.
- B3: `_cleanup_artifacts` left `project/`, `command*.json`, `daemon.log`, `pid` behind → replaced with `shutil.rmtree(log_dir, ignore_errors=True)`.
- B4: `.opencode/skills/clawctl/SKILL.md` mirror missed → re-synced byte-identical.
- B5: `bash -lc` claim about `~/.bashrc` was wrong → temporarily switched to `bash -lic` (revised in iter 3, see W1 below).

### Iter 3 → fixes / deferrals

- B2 (playbook): `shell_timeout | int` had no Jinja default → playbook validation task rejects undefined / `< 1`.
- W1: `bash -i` side effects (history pollution, job-control stderr, `~/.bash_logout`) → reverted to `bash -lc` and Python caller now prepends an explicit `[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc";` to keep PATH shims without the interactive-mode noise.
- W3: malformed `cmd_b64` hit by `no_log: true` → defined/non-empty validation task before the no-log boundary.
- W5: CLI denylist seam coverage gap → added test asserting CLI exit-2 + `'reserved system user'` before reaching core.
- W6: misleading `--timeout 0` wording ("no client-side timeout") → corrected to "alias for the hard 1800s cap; no value disables it" in CLI help and both SKILL.md mirrors.
- W7: rc=255 raw-stderr dump for infra failures → routed through `emit_error` with `Error:` / `Hint:` framing.
- **B1/B3 (architectural)**: reviewer flagged the inline `if os_family == 'darwin'` short-circuit as a dispatcher-pattern violation and the missing `shell_macos.yaml` sibling. **Intentionally deferred**: plan §1 locked Linux-only for v1; the dispatcher fork pattern (`*_macos.yaml` + dispatcher routing) is in-scope for the macOS subissue, not for this PR. Surfaced as a Callout.
- W2 (streaming/buffering) and W4 (non-UTF-8 binary) acknowledged as documented v1 boundaries.
