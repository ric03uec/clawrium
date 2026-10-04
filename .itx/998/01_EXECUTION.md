# Issue #998 — Credential activation execution

## Execution

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T07:52:59Z
**Model**: gpt-5.6-terra

```prompt
Implement issue #998: remotely activate the mutually-exclusive Claude credential selected by #999 during configure/sync, securely materialize it, and source it for existing finite agent shell commands.
```

**Output**: Implemented secure Linux/macOS configure and canonical-sync credential activation with focused coverage.

### Implementation

- Added the narrow `get_active_claude_credential()` bridge from #999's encrypted instance-secret selection.
- Routed `configure_agent()` for Claude through the dedicated no-log playbooks, transporting only the selected key/value in a private Ansible inventory. The entire runner private-data directory is removed after every outcome and post-resolution errors are sanitized.
- Extended direct canonical sync to validate the selected credential before remote I/O, atomically write a shell-escaped file that clears both credential names before exporting the selected one, install the private source hook before rotating credentials, and keep activation bodies and paths out of public diffs, events, and result-file accounting.
- Added the Claude-only finite `agent shell` prelude, including legacy `name` record compatibility. It does not alter interactive login-shell behavior.
- Hardened Linux atomic writes to validate the `mktemp` path, apply the configured timeout, drain streams, and wait for cleanup.

### Validation

- Focused: `uv run pytest tests/core/test_lifecycle_canonical_macos_dispatch.py tests/core/test_claude_credentials.py tests/core/test_claude_credential_activation.py tests/core/test_claude_settings.py tests/core/test_agent_shell.py tests/core/test_claude_lifecycle.py tests/cli/clawctl/agent/test_claude_lifecycle.py` — 212 passed.
- Full: `make test` — 4,983 passed, 2 skipped; GUI 366 passed.
- `make lint` — passed.
- `uv run ruff format --check` on all touched Python files — passed.

### ATX review

- Iteration 1: revision `65195dfd-c4a3-4378-b434-092978ac5b30`; the harness output was truncated before findings could be captured.
- Iteration 2: revision `fd65fe33-3d7d-47bb-bfdb-50ab475fa3ff`, rating 2.5/5. Fixed its verified secret-exception and direct-sync failure-coverage blockers. The claimed Linux Darwin-guard violation was not applied: the task-0 opposite-OS guard is explicitly permitted by this repository's `AGENTS.md` dispatcher-contract exception.
- Iteration 3: revision `1df5bdae-5907-4b2f-925e-c09b2849791b`, rating 2/5. Remediated its verified single-resolution, strict runner-data cleanup, post-resolution error sanitization, private activation-error sanitization, and unsafe-`mktemp` test blockers. The three-review budget was then exhausted; the final code was self-reviewed and fully validated.

### Callouts

- `.itx/989/01_SCAFFOLD.md` could not be recovered from the issue-989 worktree branch or repository history; its absence is recorded rather than reconstructed.
