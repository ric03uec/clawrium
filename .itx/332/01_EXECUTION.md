# Execution — Issue #332: Phase 3 (SSE streaming for hermes chat)

Slice 3 of parent #322. Stacked on top of #330 (phase 1 foundation); base
branch is `issue-330-hermes-chat-foundation`.

## Customer Outcome

Reply text appears word-by-word in `clm chat <hermes-name>`, identical to
`clm chat <openclaw-name>` today, instead of waiting for the full response.

## Scope (delivered)

- `HermesOpenAIBackend.send_message` requests `stream: true` and parses
  SSE deltas via `httpx.AsyncClient.stream()` → emits each non-empty
  `choices[0].delta.content` through the existing `on_delta` callback.
- Handwritten SSE parser: spec-compliant event buffering across
  multi-line `data:` continuations (SSE §9.2.6), `[DONE]` sentinel,
  `:keep-alive` and other non-`data:` lines ignored, trailing-event
  flush for servers that close without a final blank line.
- Non-SSE responses (content-type without `text/event-stream`) fall back
  to the single-JSON-response path and fire `on_delta` once with the full
  reply, preserving phase-1 behavior for older servers / buffering proxies.
- REPL renderer at `cli/chat.py` works unchanged; the only CLI tweak is
  a spinner that stops on first delta so the JSON-fallback path is not
  silent during the 120s response window.
- Mid-stream `ChatProtocolError` no longer kills the REPL — the loop
  catches it, prints a newline if any partial text was rendered, and
  prompts for the next turn. Connection and auth errors still terminate.

## Files Touched

| File | Change |
|---|---|
| `src/clawrium/core/chat_hermes.py` | SSE parser (spec-compliant multi-line buffering), JSON fallback, hardened `_short_body` sanitizer, updated `on_delta` docstring. |
| `src/clawrium/cli/chat.py` | Spinner around `send_message`; mid-stream `ChatProtocolError` caught inside `_chat_loop` so REPL survives a malformed chunk. |
| `src/clawrium/cli/tui/widgets/chat_panel.py` | Scrub C0/C1 control chars from exception text before display (defense in depth alongside `_short_body`). |
| `pyproject.toml` | `httpx>=0.27,<1.0` (was floor-only). |
| `tests/test_chat_hermes.py` | New tests: streaming deltas (incl. `Accept` header + `stream: true` body assertions), SSE edge cases, JSON fallback, multi-line `data:` reassembly, malformed/empty-stream protocol errors, mid-stream `ReadError → ChatConnectionError`. Existing `body["stream"]` assertion flipped to `True`; module docstring updated. |
| `.itx/332/01_EXECUTION.md` | This file. |

## ATX Review Iteration

Initial review (PR #337, post-first-commit) returned aggregate **3/5**,
**0 blocking issues, 10 warnings**. All 10 warnings addressed in the
follow-up commit; suggestions S1–S9 deferred (none gate this slice).

| # | Warning | Fix |
|---|---|---|
| W1 | TUI `chat_panel.py:179,182,185` interpolated `{exc}` without C0/ANSI scrubbing. | Added `_scrub_exception()` helper and applied at all three call sites. |
| W2 | `_short_body` only stripped `\n`, leaving `\r`/`\x00`/`\x1b` exploitable by a rogue server. | Replaced with `re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', …)` + space-run collapse; sanitization now happens at the source. |
| W3 | `httpx>=0.27` floor-only allowed any future major. | Capped to `<1.0`. |
| W4 | SSE multi-line `data:` events raised on join (spec §9.2.6). | Refactored parser to buffer `data:` field values, dispatch on empty-line boundary, `json.loads` once per event. Added test `test_sse_multiline_data_field_concatenates_per_spec`. |
| W5 | Terminal silent during JSON fallback up to 120s. | Added `console.status("Waiting for agent...")` spinner stopped on first `on_delta` (or in `finally`). |
| W6 | Mid-stream `ChatProtocolError` killed the REPL with partial text on screen. | Caught inside `_chat_loop`; prints newline if `shown_prefix`, then friendly error and `continue`. Only `ChatConnectionError`/`ChatAuthenticationError` still exit. |
| W7 | `send_message` docstring did not describe `on_delta` call-count semantics. | Docstring spells out: N-call per non-empty SSE chunk vs 1-call JSON fallback; callers must use return value, not call count. |
| W8 | No test for mid-stream `httpx.ReadError`. | Added `test_sse_read_error_mid_stream_raises_connection_error` using a custom `AsyncByteStream` that raises after one chunk. |
| W9 | `Accept: text/event-stream` header never asserted in any test. | `test_streaming_deltas` now captures and asserts both `Accept` header and `stream: true` body. |
| W10 | Test module docstring still said "phase 1: non-streaming". | Updated to cover phases 1 + 3. |

## Issue #331 Coordination (history ghost half-turn)

The orchestrator flagged a potential cross-slice bug: in slice 2, the
client-side `messages: [...]` list is appended *before* the network call
completes, so a mid-stream raise leaves a "ghost" half-turn that
poisons the next request.

**Does not apply to this branch.** This branch carries no history
accumulator — `HermesOpenAIBackend` instantiates `messages` fresh per
call. The W6 fix here (catch `ChatProtocolError` inside `_chat_loop`)
is the CLI-layer half of what slice 2 will need; when #331 lands it
must move the `history.append(user_turn)` call to *after* the
backend's return statement, not before the network I/O.

## Verification

- `make test` — 1638 passed (1633 prior + 5 new SSE tests; one was the
  multi-line-data test added during the fix cycle, others were in the
  initial commit).
- `make lint` — clean.
- Manual REPL verification deferred per phase plan; slated for after
  slice 4 lands so all four phases can be exercised end-to-end on a
  live hermes install.

## Exit Criteria (from issue #332)

- [x] `test_streaming_deltas` — canned SSE chunks → expected `on_delta` calls
- [x] `test_sse_edge_cases` — `[DONE]` terminates; `:keep-alive` ignored
- [x] `test_non_streaming_fallback` — non-SSE response uses JSON path
- [x] `make test` green; `make lint` clean
- [ ] Manual verification on a real REPL session — deferred to end of slice 4

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution (initial + ATX-fix iteration)
**Skill**: /itx:execute
**Timestamp**: 2026-05-11T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 332
```

```prompt
ATX review of PR #337 returned 3/5 aggregate with 10 warnings. Fix all
warnings on the same branch (issue-332-streaming). Create NEW commits
(do not amend). Push to origin when done.
```

</details>
