# Execution — Issue #333: Phase 4: failures are obvious and recoverable

## Summary

Implemented friendly error messages and remediation hints for hermes (OpenAI-typed) chat failures, ensuring no raw `httpx` exception text leaks to the user.

## Changes

### `src/clawrium/core/chat_hermes.py`
- Dropped raw `httpx` exception text from `ChatConnectionError` messages. Internal transport details (errno codes, socket addrs, file paths) no longer reach the CLI layer. Friendly remediation belongs to the CLI; the backend stays terse.

### `src/clawrium/cli/chat.py`
- Added a dim `--session` no-op warning for OpenAI-typed agents when the value differs from `main`. Chat continues regardless (signature parity with openclaw).
- Branched the error handlers by `chat_type`:
  - `openai` + `ChatAuthenticationError` → "Token mismatch. Re-run `clm agent configure <name>`."
  - `openai` + `ChatConnectionError` → "Check `systemctl --user status hermes-<name>` on the agent host." Adds a legacy-bind hint when persisted `api_server.host == "127.0.0.1"` (pre-migration installs).
  - `websocket` path unchanged.

### `tests/test_cli_chat.py`
- `test_service_unreachable` — refined to assert the systemctl hint and absence of legacy hint under the standard 0.0.0.0 bind.
- `test_service_unreachable_legacy_bind_hint` — new; pre-migration `127.0.0.1` bind surfaces the configure hint.
- `test_401_remediation` — renamed/replaced the prior `test_authentication_failure`; asserts the "Re-run `clm agent configure <name>`" message.
- `test_session_flag_warns_for_hermes` + `test_session_flag_default_does_not_warn` — covers the non-default-session warning and confirms the happy path stays quiet.
- `test_connection_error_does_not_leak_httpx_internals` — CLI-level sanitizer guard.

### `tests/test_chat_hermes.py`
- `test_connection_error_does_not_leak_httpx_internals` — backend-level sanitizer guard for `httpx.ConnectError` with internal text.
- `test_http_error_does_not_leak_httpx_internals` — same for generic `httpx.HTTPError`.

## Verification

- `make test` — 1634 passed.
- `make lint` — clean.

## Exit Criteria Mapping

| Exit Criterion | Covered by |
|---|---|
| `test_service_unreachable` — connection refused → friendly remediation; legacy-bind hint when applicable | `test_service_unreachable` + `test_service_unreachable_legacy_bind_hint` |
| `test_401_remediation` — 401/403 → "Re-run `clm agent configure`" | `test_401_remediation` |
| `test_session_flag_warns_for_hermes` — non-default `--session` → dim warning | `test_session_flag_warns_for_hermes` |
| No raw `httpx` exception strings reach the user | Backend sanitizer tests (`test_chat_hermes.py`) + CLI guard (`test_connection_error_does_not_leak_httpx_internals`) |
| `make test` green; `make lint` clean | Verified |

## Prompt Log

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-11T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 333
```

</details>
