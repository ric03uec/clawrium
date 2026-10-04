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
