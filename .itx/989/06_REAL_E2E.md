# Issue #989 — Real Claude E2E Evidence

## Scope and safety controls

This validation ran from `feat/claude-native-exec` against `wolf-i` after first
saving a private control-plane snapshot and minting one `clawctl audit`
session. Two new, isolated Claude agents were used: one OAuth-selected agent
via the supported `claude-oauth` provider attachment and one API-key-selected
agent. The controller credential file is dotenv-formatted
(`ANTHROPIC_API_KEY=<value>`): its value was extracted only in a short-lived
Python process and supplied to `clawctl agent secret create` on stdin. The
supported secret-create interface expects the raw key value, not the dotenv
assignment. Neither the assignment nor its value was printed, placed in a
command argument or environment, stored in this repository, or copied into
this evidence.

No pre-existing agent was modified or deleted. The pre-existing fleet snapshot
matched after cleanup.

## OAuth live flow — PASS

1. Installed a fresh dedicated Claude agent, attached `local-claude-oauth`
   through the supported provider workflow, then ran configure and sync.
2. A remote boolean-only probe returned `OAUTH_SELECTED=true` (native OAuth
   document present; API-key artifact absent).
3. A real native invocation returned exactly `OAUTH_LIVE_OK` through
   `clawctl agent exec <name> -- -p ...`.
4. A real CLI one-shot chat returned exactly `OAUTH_CHAT_OK`.
5. A current-worktree FastAPI GUI server streamed `OAUTH_GUI_OK` as an SSE
   content event. A same-session follow-up returned the nonsecret continuation
   marker, and a fresh browser session returned `OAUTH_GUI_NEW_SESSION_OK`.
6. An interactive CLI session retained a nonsecret marker across two turns;
   `/reset` produced the CLI reset notice and the following turn returned
   `OAUTH_CLI_RESET_OK`.
7. A real client disconnect (`curl` timeout, exit 28 before any response) was
   followed by a same-session GUI retry. Initially the retry returned the safe
   generic error, exposing a duplicate-upstream-UUID defect. The backend now
   abandons the partial UUID on cancellation; after restart, the live retry
   returned `OAUTH_GUI_RETRY_OK`.

## API-key live flow — PASS

1. The first isolated API test mistakenly supplied the entire dotenv assignment
   from `~/.ssh/anthropic.key` to the raw-key secret interface. It safely
   produced HTTP 401 and Claude's sanitized `invalid_api_key` category. This
   was a validation-file-format import error, not an external credential or
   Clawrium transport failure.
2. Boolean-only diagnostics established that the protected file contained one
   printable, single-line `ANTHROPIC_API_KEY=<value>` assignment and that its
   in-memory value had the expected key format. A single direct controller
   request with only that parsed value in memory returned HTTP 200.
3. Recreated the isolated API agent, stored only the parsed raw value through
   `clawctl agent secret create --value-stdin`, then ran configure and sync. A
   remote boolean-only probe returned `API_KEY_SELECTED=true`.
4. A direct Anthropic request under the dedicated remote user, using only the
   configured artifact, returned HTTP 200. This proves the render and
   activation path independently of Claude CLI behavior.
5. A real native invocation returned exactly `API_KEY_LIVE_OK`; a real CLI
   one-shot chat returned exactly `API_KEY_CHAT_OK`; and the current-worktree
   FastAPI GUI route streamed `API_KEY_GUI_OK` as an SSE content event.
6. The temporary invalid-key execution also revealed that Claude can put an
   authentication diagnostic on stdout. The backend now classifies either
   stdout or stderr safely without returning the upstream diagnostic to CLI or
   GUI callers.

Both supported credential modes therefore made authenticated exec, CLI-chat,
and GUI-chat requests successfully.

## Secret and cleanup assertions

- A memory-only scan of controller Clawrium logs and audit records reported
  `API_KEY_PLAINTEXT_IN_CONTROLLER_LOGS=false`.
- The no-log host capture transport was exercised with real OAuth and API-key
  modes; it emits only redacted, base64 result events. No credential-bearing
  Ansible result or GUI error was observed.
- Both validation agents were deleted through `clawctl agent delete --yes`.
  Direct privileged, boolean-only remote assertions confirmed account, home,
  owned prefix, credential directory, and ownership marker absence for each.
- Local validation-agent records were absent and the pre-existing fleet
  snapshot comparison returned `PREEXISTING_FLEET_PRESERVED=true`.

## Execute Log

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-10-05T01:43:00Z
**Model**: gpt-5.6-terra

```prompt
NEW USER ACCEPTANCE, HIGH PRIORITY: actual working solution, not passing tests. STOP ALL ATX REQUESTS until real live flows WORK. Reopen task checklist. You own the cumulative stack in worktree feat/claude-native-exec (PR #1026) and may fix inherited auth/chat/GUI/exec code here as needed. Use two fresh isolated Claude agents on wolf-i: one local OAuth via supported provider attach (no manual env token), one API-key using controller ~/.ssh/anthropic.key (limited test key; read securely in memory, NEVER print/log/copy plaintext into repo, process argv, screenshots, PR or tmux). Preserve pre-existing agents; snapshot first. For EACH mode: install/configure/sync, confirm selected remote credential mode privately via boolean-only probe, make a REAL minimal authenticated Claude invocation returning an expected nonsecret answer through `clawctl agent exec NAME -- -p ...` (or native finite command if exec needs fixing), make REAL CLI `agent chat --once` response, and make REAL GUI chat request through running FastAPI/GUI route or browser with SSE session to visible rendered answer. Verify both OAuth and API modes separately. Reproduce API-key failure safely, gather sanitized error category/status only (never secret), fix root cause; do not mark success based on env propagation/tests alone. Test session continuation/reset and GUI disconnect/retry where feasible. If host has external key/credit policy blocker, independently establish exact safe error category, try valid supported authentication path, and document honest blocker; do NOT pretend successful auth. Ensure no key or OAuth token leaks to Ansible events/logs/PR. Remove both agents; assert no account/home/prefix/credentials, and pre-existing fleet preserved. Document redacted evidence in .itx/989/06_REAL_E2E.md. First achieve live success, then make test/lint, then ONLY AFTER live success ATX (new revision/scope; prior ceiling/exhaustion documented; use judgment and no premature review). Commit/push fixes to feat/claude-native-exec, update PR #1026 with precise evidence and callouts; don't merge, no new issues, no user questions. Work until verified, not until timeboxed. Let orchestrator know if you need steering.
```

**Output**: Verified real OAuth and API-key Claude exec/CLI-chat/GUI-chat flows; corrected the protected dotenv-file import in memory without exposing its value; fixed live GUI disconnect retry and stdout authentication classification; cleaned all validation resources.
