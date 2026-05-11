# Plan — Issue #331: Slice 2 — multi-turn conversations retain context

## Customer Outcome

A user sends "what's 2+2?" → agent says "4". User sends "double that" → agent says "8". Prior turns carry within the REPL session.

## Parent

This is Slice 2 of #322 (Generalize `clm chat` for hermes via OpenAI-compatible HTTP backend). See `.itx/322/00_PLAN.md` for the full architectural plan and per-slice breakdown. The single source of design context is the parent plan; this file captures the scoped-down view used during execution of #331.

## Scope (this slice only)

- `HermesOpenAIBackend` maintains `self._history: list[dict[str, str]]`, populated with each user message + assistant reply on success.
- Each `send_message` call sends the running `messages: [...]` array (prior turns + new user message) to `/v1/chat/completions`.
- `/reset` REPL command clears the history.
- `ChatBackend` Protocol grows a `clear_history()` method; `OpenClawChatClient` implements it as a no-op (its gateway owns session state).
- History is capped at `MAX_HISTORY_TURNS = 100` turns (200 list entries) with front-truncation to bound memory and per-request payload size.

## Files modified

- `src/clawrium/core/chat.py` — add `clear_history()` to `ChatBackend` Protocol; no-op implementation on `OpenClawChatClient`.
- `src/clawrium/core/chat_hermes.py` — `_history` accumulator, `clear_history()`, cap + truncation, atomic-on-failure append semantics.
- `src/clawrium/cli/chat.py` — wire `/reset` in REPL loop; gate help banner hint on `chat_type == "openai"`; expand `_sanitize_exception_text` keyword group; clean up `--session` help text.
- `tests/test_chat_hermes.py` — 3-turn accumulation, resume-after-reset, mid-conversation failure atomicity, cap behavior, idempotent reset.
- `tests/test_cli_chat.py` — REPL `/reset` dispatch tests covering hermes-style backend (history cleared) and no-op backend (websocket).

## Exit Criteria

- [x] Two-turn (extended to 3-turn) conversation: each `send_message` call's request body includes prior user+assistant pairs (`test_history_grows_across_turns`).
- [x] `/reset` empties `_history`; subsequent send goes back to a single-message payload (`test_history_resumes_accumulating_after_reset`).
- [x] `make test` green; `make lint` clean.
- [ ] Manual verification: 3-turn conversation on a real hermes install demonstrates context retention.

## Dependencies

Slice 1 (#322 sub-issue 1, merged in commit `020afef`) provides the dispatch + single-turn backend this slice builds on.

## References

- Parent: #322
- Parent plan: `.itx/322/00_PLAN.md`
- Slice 2 section of parent plan: lines 160-167 of `.itx/322/00_PLAN.md`
- ATX review history: see PR body
