# Issue #1015 — Real Claude OAuth Provider E2E Evidence

**Host alias:** `wolf-i` (i-wolf)
**Completed:** 2026-10-03T17:45:36+00:00

## Safety boundary

- OAuth was imported only by normal `clawctl agent provider attach` selection; no direct secret command, dummy credential, or caller OAuth environment variable was used.
- The attachment invokes #1013's narrow local credential reader. It accepts only the current user's validated Claude OAuth access-token field; this harness never prints, copies, hashes, or persists it outside Clawrium's existing per-instance secret flow.
- The harness starts no Claude process: the only agent command is the existing finite `agent shell` environment assertion, which prints fixed booleans only.
- CLI output is captured only in memory for assignment-shape redaction checks and is not included in this evidence.

## Commands exercised

- `clawctl agent create claude-oauth-e2e --type claude --host wolf-i`
- `clawctl provider registry create claude-oauth-e2e-provider --type claude-oauth`
- `clawctl agent provider attach claude-oauth-e2e-provider --agent claude-oauth-e2e`
- `clawctl agent sync claude-oauth-e2e`
- `clawctl agent shell claude-oauth-e2e -- <redacted boolean assertion>`
- `clawctl agent delete --yes claude-oauth-e2e`
- `clawctl provider registry delete --yes claude-oauth-e2e-provider`

## Assertions

- Install-only: **PASS** — no Claude process, service, gateway, port, UI state, local credential, remote `.claude`, or startup hook before OAuth sync.
- Selection-only provider registration: **PASS**
- Normal OAuth attachment: **PASS**
- Supported local reader path: **PASS**
- Sync activation: **PASS**
- Credential file ownership and mode: **PASS** — agent-owned `0600`.
- Redacted agent-shell booleans: OAuth nonempty **PASS**; `ANTHROPIC_API_KEY` empty **PASS**.
- State/settings/CLI-event redaction assertions: **PASS**
- Owned-resource cleanup: **PASS** — account, home, prefix, full `.claude`, credential and startup files, ownership marker, local per-instance secret scope, hosts record, and temporary provider record absent.
- Pre-existing fleet records preserved: **PASS**

## Result

**PASS**
