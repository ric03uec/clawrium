# Claude GUI Chat Execution

## Prompt Log

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-04T23:52:09Z
**Model**: pi coding agent

```prompt
Execute ONLY the Claude Code GUI chat phase for parent #989, stacked on existing CLI chat PR #1024 branch feat/claude-cli-chat. Read AGENTS.md, issue #989 + checklist comment, GUI chat FastAPI SSE route and React tab, inherited Claude ChatBackend and tests. Make a task checklist. Implement POST /api/agents/{agent_key}/chat dispatch for manifest chat.type=claude using the same shared backend, preserving session continuity per browser conversation and a working SSE contract (content/error/[DONE]) with prompt/cancellation/timeouts and no secret/log leakage; GET chat/info must indicate chat supported for claude while web-ui capability stays unavailable and Open Agent UI remains hidden. Add backend route and frontend tests meaningful for OAuth and API-key mode behavior, errors, session reset and inactive/missing agent. Do not add daemon/gateway/tunnel/pairing or duplicate Claude invocation logic. Scope GUI/FastAPI only plus strictly needed shared integration fixes; do not implement agent exec (#next), change auth mechanism (#1023), Herdr, or reformat unrelated code. Update docs/changelog to reflect GUI chat. Run make test and make lint and relevant website build if touched. Request stateless ATX review via atx review request --worktree feat/claude-gui-chat --format json --timeout 15m, at most 3 iterations; fix blockers. Record execution/review in .itx/989/04_CLAUDE_GUI_CHAT.md (preserve existing planning files). Inspect status/diff/log before staging only intended files; commit/push/open PR base feat/claude-cli-chat and include 'Stacked on top of feat/claude-cli-chat', AGENTS ATX/Testing/## Callouts (mention API-key real-request validation gap). No new issues, merges, user questions; if ATX exhausted, open PR with [ITX-STUCK] marker and precise Callouts. Timebox fixes; hand off with PR URL promptly.
```

**Output**: Added Claude Code GUI chat using the inherited on-demand CLI backend, with bounded browser-session continuity and SSE safety coverage.

## Implementation

- Added `chat.type: claude` FastAPI dispatch that reuses
  `ClaudeCodeChatBackend`; it neither reads credentials nor implements a second
  Claude command transport.
- Cached backend state per `(agent_key, browser_session)` with a 30-minute TTL
  and bounded idle eviction. The route serializes a conversation's turns,
  forwards a 120-second response timeout, emits `content` or generic `error`
  SSE followed by `[DONE]`, and closes the backend on success, failure, or
  cancellation.
- Added a browser-scoped session key and **New chat** action to the Chat tab.
  Reset cancels any pending request and ignores stale completion/error output.
- Kept Claude's native web UI unavailable and verified the header hides **Open
  Agent UI**. No daemon, gateway, tunnel, pairing, agent-exec, auth-mechanism,
  or Herdr work was added.
- Updated support docs, README, website mirrors, and the unreleased changelog.
  A targeted website CLI-reference anchor correction was required for the
  relevant website build.

## Validation

- `make test` — **5110 passed, 2 skipped**.
- `make lint` — passed (Ruff and GUI ESLint).
- `website: npm run build` — passed after correcting the inherited Claude
  no-daemon section anchor.
- `git diff --check` — passed.

## ATX Review

| Iteration | Rating | Result |
|---|---:|---|
| 1 | 2/5 | Added direct generator-cancellation coverage after B1/B2 requested verification of cleanup and same-session retry. |
| 2 | 2/5 | Added ASGI/FastAPI `http.disconnect` coverage after B1/B2 requested transport-level verification. |
| 3 | 2/5 | ATX test-coverage could not inspect the uncommitted/untracked diff, so it reported no source finding. The final `make test` verifies the ASGI disconnect test; the three-review ceiling is exhausted. |

The nonsecret ATX session metadata is retained in `atx-session.json`.

## Known Callouts

- API-key real-request validation remains an inherited gap from the preceding
  `feat/claude-api-key-auth` stack (#1023); this GUI phase exercised neither a
  live Anthropic API-key request nor credentials values.
- The final ATX iteration could not ingest the uncommitted/untracked patch for
  its coverage specialist. All reported source-level blockers were addressed,
  but the PR is marked `[ITX-STUCK]` because the three-review ceiling was
  reached with that transport limitation.
