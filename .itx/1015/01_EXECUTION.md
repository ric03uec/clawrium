## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T17:35:37Z
**Model**: gpt-5.6-terra

```prompt
Execute only GitHub issue #1015: Verify real Claude OAuth provider propagation on i-wolf. You are a stacked E2E worker. Your branch is issue-1015-claude-oauth-e2e; open the PR against issue-1013-claude-oauth-provider and include `Stacked on top of issue-1013-claude-oauth-provider`.

This is a hard product requirement. Validate real OAuth propagation through normal Clawrium provider UX, not `CLAUDE_CODE_OAUTH_TOKEN` in the process environment, not a dummy OAuth token, and not a raw direct secret injection. Read AGENTS.md, #1015, #1013, #989, plans, inherited code and prior i-wolf E2E before edits. Use a task checklist.

Run a fresh, isolated `claude-oauth-e2e` case against i-wolf. Use normal CLI/provider flows to register/select/attach `claude-oauth`; that path must invoke the #1013 local supported `claude setup-token` reader without emitting its stdout or token. Install the agent, configure/sync, and use the existing finite agent-shell command path only to assert redacted booleans: OAuth variable is nonempty, `ANTHROPIC_API_KEY` is empty, credential file ownership/mode is correct, settings/state/evidence/CLI events contain no token. Do not print, copy, scrape, or persist the token. Do not use manual provider secret set or caller-env token as an E2E workaround. Do not launch Claude during installation; a remote Claude invocation is not required unless an official safe no-cost status command is proven and can run without token output.

Then remove the fresh agent and prove cleanup of account/home/prefix/full `.claude`/credential and startup files/local per-instance secret/hosts record while preserving all pre-existing agents. Produce non-secret evidence. If local OAuth cannot be read, fail E2E loudly with diagnostic category only, but user states local auth is working: investigate actual provider flow before declaring a blocker. If #1013's provider mechanism fails, fix only the specific defect required for its real E2E compatibility and test it; do not alter unrelated provider/lifecycle design.

Scope excludes dummy API-key tests, broad provider registry redesign, docs, gateway/chat/UI/service work. Add/update repeatable safe E2E and regression tests. Run focused tests, make test, make lint, and stateless ATX CLI review `atx review request --worktree <worktree-name> --prompt "Review full diff against issue-1013-claude-oauth-provider" --format json --timeout 15m`, max 3. Persist `.itx/1015/atx-session.json`, add `.itx/1015/01_EXECUTION.md`, commit/push/create PR with AGENTS ATX body and Callouts. Do not ask user questions and do not merge.
```

**Output**: Replaced the obsolete environment-token OAuth E2E with a normal provider-registration/attachment harness and redacted evidence. The real i-wolf run completed fresh-install and full-cleanup assertions but failed closed at the supported reader with `LOCAL_OAUTH_SETUP_TOKEN_TIMEOUT`; no reader output, token, or direct secret fallback was used.

### Investigation and scope decision

- `claude auth status` was verified as an official, no-cost local status command: it exited successfully with no credential assignment in either captured stream.
- The normal attachment itself invoked the #1013 reader three times after the harness stripped all caller credential variables. Each run reached only the fixed, secret-free `setup_token_timeout` category; its output was neither printed nor persisted.
- A private PTY diagnostic confirmed the installed Claude Code `setup-token` command enters its browser-login flow even while `auth status` is successful. It did not report a credential assignment before the child was terminated, and no transcript was persisted.
- The only provider-layer change retains a validated, fixed error category through the reader and attachment boundary, so this real E2E can report the timeout without reflecting opaque Claude stdout/stderr. No authentication source, secret transport, lifecycle, or documentation design was changed.

### Validation so far

- Focused E2E/credential/provider tests: `34 passed`.
- Current real i-wolf evidence at this stage: `.itx/1015/02_E2E_OAUTH.md` (expected nonzero fail-closed result with cleanup passed).

## Execution Correction

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T17:44:08Z
**Model**: gpt-5.6-terra

```prompt
CRITICAL CORRECTION: Do NOT treat a `setup-token` timeout as successful completion or submit this E2E as a blocker. The user requires actual local OAuth propagation and states their local credentials work. The environment-only and `setup-token`-only source are not sufficient. Reopen the E2E task and make the provider flow work against the real local authenticated credential.

Research the installed Claude Code credential contract/source further. You may add a narrow Linux credential adapter that reads only the specific locally owned credential artifact/API needed to extract the OAuth access token in memory, validates it, and never copies/parses broadly/persists/prints raw data. A known, version-validated Claude credential file or a supported keyring item is acceptable only if confirmed; do not copy `~/.claude` or a database wholesale. Update #1013 reader behavior as the minimal fix, then rerun the normal provider attach and actual i-wolf sync until evidence says PASS: reader used, remote OAuth env nonempty, API env empty, redaction/cleanup/preservation all pass. Do not publish a failing/timeout E2E as the completion of #1015.
```

**Output**: Confirmed Claude Code 2.1.139's private, current-user-owned `~/.claude/.credentials.json` contract exposes `claudeAiOauth.accessToken`; added a bounded Linux-only reader with ownership, mode, symlink, regular-file, and size checks. The final normal provider attach and i-wolf sync passed every non-secret propagation, redaction, cleanup, and preservation assertion; see `02_E2E_OAUTH.md`.

## Final Validation

- Real i-wolf evidence: `02_E2E_OAUTH.md` records **PASS**, including normal provider attachment, sync, remote OAuth nonempty / API-key empty boolean checks, state/output redaction, fresh-agent owned-resource cleanup, and preservation of pre-existing agents.
- Focused regression suite: `38 passed`.
- Full validation: `make test` passed (`5014 passed, 2 skipped`); `make lint` passed (Ruff plus GUI lint).
- Format-incident scope check: only the issue E2E harness, narrow credential reader, their focused tests, and `.itx/1015/` artifacts remain changed; no broad formatter churn remains.
- ATX stateless review: three iterations against the stacked worktree. Iteration 1 found inherited provider-output concerns and rated 2/5; the scoped second review had no blockers (3/5); final scoped review had no blockers and rated 3.5/5. Details are retained in `atx-session.json`.
