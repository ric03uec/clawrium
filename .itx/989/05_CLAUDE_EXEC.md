# Issue #989 — Claude Native Exec Execution Evidence

## Summary

Implemented the Claude native `clawctl agent exec` phase stacked on the CLI and GUI chat branches. Claude is now accepted by the shared exec dispatcher and invoked through Linux and macOS playbooks as the dedicated agent user, using its pinned per-agent binary and structured argv.

The fixed host-side wrapper clears inherited credentials, sources an API-key artifact only when present, preserves native OAuth state, captures raw child output in a private temporary directory, redacts selected API/OAuth credential values before emitting one base64 result event, and deletes the temporary files. No raw child stdout or stderr reaches an Ansible event. Both operating-system wrappers start the child in a new session and kill the complete process group at the requested deadline.

## Verification

- Focused native-exec coverage: `78 passed`.
- Final `make test`: `5141 passed, 2 skipped` (plus `369` GUI tests).
- Final `make lint`: Ruff and GUI ESLint passed.
- Website build: `npm --prefix website run build` passed.
- `git diff --check` passed.
- The website Claude support page and agent-support index contain the same newly added native-exec text as their canonical engineering docs. Existing unrelated website-only Herdr/link differences remain unchanged.

## ATX Review

The ATX CLI review transport was available. The third successful stateless review (revision `4438e95a-4520-4293-800d-847fd5576bed`) rated the pre-fix diff 2.5/5 and found a valid Linux process-group timeout blocker. It was fixed by replacing GNU `timeout` with the same dedicated-session Perl wrapper used on macOS and by adding a real regression that proves a background child cannot survive a one-second command deadline. No further review was requested because the three-successful-review limit was reached.

The review also requested broader provisioning and GUI/CLI coverage. This bounded phase already adds focused core, CLI, GUI-dispatch, and real-playbook regression coverage; further GUI output-contract work is tracked as #1025 rather than broadening this stacked PR.

## Execute Log

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-10-05T00:43:16Z
**Model**: gpt-5.6-terra

```prompt
Execute only Claude native `agent exec` phase for #989 on `feat/claude-native-exec`, stacked on `feat/claude-gui-chat`; implement safe Linux/macOS Claude exec, tests/docs/changelog, validate, ATX-review, log, commit/push, and open stacked PR.
```

**Output**: Added safe, bounded Claude native exec with host-side credential redaction and complete Linux/macOS process-group cleanup coverage.
