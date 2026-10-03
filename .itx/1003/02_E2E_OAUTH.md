# Issue #1003 — Claude Provider E2E Evidence

**Host alias:** `wolf-i` (i-wolf)
**Completed:** 2026-10-03T09:24:53+00:00

## Safety boundary

- OAuth is accepted only from an explicitly exported `CLAUDE_CODE_OAUTH_TOKEN`; the harness never reads a keychain, browser profile, database, or local `~/.claude`.
- The API-key phase creates a unique dummy value and supplies it only on stdin. It never invokes `claude` or an authenticated external API.
- Captured command stdout/stderr is never persisted. The harness fails if its dummy value appears in a checked output surface.

## Commands exercised

- `clawctl agent create <fresh-name> --type claude --host wolf-i`
- `clawctl agent secret create ANTHROPIC_API_KEY --agent <fresh-name> --value-stdin` (API-key case only)
- `clawctl agent sync <fresh-name>`
- `clawctl agent shell <fresh-name> -- <non-authenticating environment assertion>`
- `clawctl agent delete --yes <fresh-name>`

## OAuth: `claude-oauth-e2e`

- Install-only: **PASS** — package prefix exists; no Claude process, service, gateway/port/UI record, local credentials, remote `.claude`, or managed credential hook before sync.
- OAuth source: blocked: explicit CLAUDE_CODE_OAUTH_TOKEN environment source absent; local ~/.claude was not inspected
- Credential activation: **NOT RUN / BLOCKED**
- Redaction assertion: **NOT RUN / BLOCKED**
- Owned-resource cleanup: **PASS** — account, home, prefix, complete `.claude`, credential file, startup hook, ownership marker, local instance secrets, and hosts record absent.
- Pre-existing fleet records preserved: **PASS**
- Result: **ENVIRONMENT BLOCKER** — install-only and cleanup completed; OAuth activation was not attempted.

## Callout

- The OAuth authenticated-command check is intentionally not run when the explicit environment source is unavailable. No fallback source was inspected.
- Real Anthropic API authentication is deliberately deferred: the API-key assertion validates only exclusive remote environment transport with a generated dummy value.

## Follow-up OAuth propagation validation

**Requested:** 2026-10-03T15:55:06Z

- The fresh `claude-oauth-e2e` identity remains absent locally and on i-wolf after the prior completed cleanup.
- The current Pi worker process does **not** have an explicitly exported `CLAUDE_CODE_OAUTH_TOKEN` (presence-only check; no value was read or printed).
- This is the precise blocker: `import_claude_oauth_from_environment` supports only that invoking-process environment variable. It deliberately has no safe fallback for a working local Claude session, `~/.claude`, keychain, browser profile, or credential database.
- No OAuth agent was created, no remote credential file was written, and no Claude/API command was invoked during this follow-up; doing so without the supported exported source would weaken the credential boundary.
