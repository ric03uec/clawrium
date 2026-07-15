# Issue #918 — Implement `clawctl agent chat --once`

## Problem

`clawctl agent chat <name> --once "hello"` advertises single-shot mode in
`--help` but currently prints `Not implemented: agent chat --once` and
exits. The stub short-circuit lives at
`src/clawrium/cli/clawctl/agent/chat.py:35-39`. The underlying transport
already streams a full turn via `_chat_loop` in
`src/clawrium/cli/chat.py`; the `input()` fallback at
`chat.py:571-579` already proves piped input works. What is missing is
~25 LOC of glue that skips the REPL loop, sends a single user message,
awaits one top-level completion, prints the response, and exits.

## Design

1. **Thread `once` from clawctl → legacy chat → loop.**
   - `clawctl/agent/chat.py:chat()` passes `once=once` when delegating.
   - `cli/chat.py:chat()` accepts a new `once: Optional[str] = None`
     kwarg and forwards it into `_chat_loop` via `asyncio.run(...)`.
   - `_chat_loop` branches on `once is not None`.

2. **Single-shot branch inside `_chat_loop`.**
   - Skip the interactive prompt entirely (no `_read_user_input`, no
     `PromptSession`, no banner reused from the interactive path).
   - Call `backend.send_message(...)` once with a fixed timeout — the
     lesser of the `--timeout` CLI value and the once-mode idle cap
     (`_ONCE_IDLE_TIMEOUT_SECONDS = 60.0`).
   - Print the final assembled text to stdout (streaming deltas via
     `on_delta` for parity with the REPL).
   - Close the backend in a `finally`.
   - Exit code 0 on success. Existing exception classes
     (`ChatAuthenticationError`, `ChatConnectionError`,
     `ChatProtocolError`) already surface non-zero exits via the
     outer `chat()` handlers with useful stderr messages — the
     once branch reuses them, no new error path needed.

3. **Suppress interactive-only chrome in once mode.**
   - The pre-existing `Connected target:` and "Type /exit ..." banners
     in `chat()` are gated on `once is None` so scripted callers get
     clean stdout containing only the reply.

4. **Remove the stub short-circuit and rewrite the help string.**
   - Drop `echo_not_implemented(...)` in
     `src/clawrium/cli/clawctl/agent/chat.py`.
   - Update the flag help text to:
     `Send one message, print the reply, and exit. Exit code 0 on success, non-zero on transport error.`

5. **Update tests.**
   - `tests/cli/clawctl/agent/test_chat.py::test_chat_once_uses_canonical_placeholder`
     is the ATX iter-1 contract assertion. It is a standalone test
     asserting the "Not implemented" string; remove the whole test
     (there is no table iteration in that file).
   - Add three new tests in the same file:
     - `test_chat_once_sends_single_message_and_exits` — monkeypatch
       `cli.chat.chat` with a spy that asserts `once="hello"` is
       forwarded, returns exit code 0.
   - Add pure `_chat_loop` tests in `tests/test_cli_chat_once.py`
     with a fake `ChatBackend` (async send returning a canned reply)
     covering the three deliverables:
     - single send + stdout contains reply + exit 0
     - transport error → non-zero exit
     - no interactive prompt / banner printed

## Non-goals

- Multi-turn tool loops. The MVP is one send, one completion. The
  60 s idle cap guards a stuck agent.
- Memory / session isolation. `--once` uses the same session key as
  an interactive turn ("main" by default). Callers who want isolation
  pass `--session direct:<key>`.
- `--once-timeout` flag. The idle cap lands as a module constant
  (`_ONCE_IDLE_TIMEOUT_SECONDS = 60.0`) to keep the surface area
  small — can be promoted to a flag in a follow-up if operators
  ask.

## Files touched

- `src/clawrium/cli/clawctl/agent/chat.py`
- `src/clawrium/cli/chat.py`
- `tests/cli/clawctl/agent/test_chat.py`
- `tests/test_cli_chat_once.py` (new)
- `CHANGELOG.md`

## Verification

- `make lint` clean.
- `make test` clean.
- Real-host UAT deferred to PR description (marked PENDING; needs
  wolf-i verification of `--once "reply pong"` returning `pong` with
  exit 0, plus killed-agent → non-zero exit within 30 s).
