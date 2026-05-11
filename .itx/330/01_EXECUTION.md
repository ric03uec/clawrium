# Execution — Issue #330: Phase 1 (hermes chat E2E, single-turn, non-streaming)

## Scope Implemented

Phase 1 of #322, exactly as scoped:

1. **`core/install.py:847-851`** — new hermes installs persist `agent_record.config.api_server.host == "0.0.0.0"` in hosts.json.
2. **`core/lifecycle.py` hermes branch** — opportunistic migration: legacy `host == "127.0.0.1"` records are rewritten to `"0.0.0.0"` (in-memory + persisted via `update_host`) on the next `configure_agent` call. Idempotent — re-running on an already-migrated record is a no-op.
3. **`core/registry.py`** — extended `FeaturesConfig` TypedDict + `_validate_features` with closed enum `chat: {type: Literal["openai", "websocket"]}`. Manifest validator rejects anything else.
4. **Manifests** — `hermes/manifest.yaml` advertises `features.chat.type: openai`; `openclaw/manifest.yaml` advertises `features.chat.type: websocket`.
5. **`pyproject.toml`** — added `httpx>=0.27` (async HTTP, needed because `requests` is sync-only).
6. **`core/chat.py`** — extracted `ChatBackend` Protocol (async `connect`, `send_message`, `close`). `OpenClawChatClient` conforms with zero behavior change.
7. **`core/chat_hermes.py`** (new) — `HermesOpenAIBackend`:
   - `POST {base_url}/chat/completions` via `httpx.AsyncClient`, non-streaming (`stream: false`).
   - `Authorization: Bearer <HERMES_API_SERVER_KEY>` header.
   - Maps `httpx.ConnectError` → `ChatConnectionError`, `httpx.TimeoutException` → `ChatConnectionError`, 401/403 → `ChatAuthenticationError`, 5xx → `ChatProtocolError`.
   - No history yet (phase 2 scope).
8. **`cli/chat.py`** — replaced the openclaw type gate at L78 with dispatch by `features.chat.type` (`websocket` → `_build_openclaw_backend`, `openai` → `_build_hermes_backend`). Hermes backend constructor mirrors `lifecycle.py:734-771` for bearer lookup and `_reconstruct_gateway_url` for URL construction (uses `host_record.hostname` for the dial target, never `api_server.host`).

## Notable Design Decisions

- **Bearer lookup happens at the CLI layer**, not inside `HermesOpenAIBackend`. The backend takes an already-resolved `SecretStr`. This keeps the backend pure (no I/O at construction) and makes unit tests trivial via `httpx.MockTransport`.
- **`_chat_loop` signature change**: now takes a `backend: ChatBackend` instead of openclaw-specific kwargs (gateway_url, auth_token, device_id, device_private_key). The renderer (`on_delta` + final-text handling) is unchanged — phase 1 hermes fires `on_delta` once with the full reply so the REPL UI works without modification.
- **`api_server.host` is the bind, not the reach.** Even after the migration writes `"0.0.0.0"` to hosts.json, `_build_hermes_backend` constructs the URL from `host_record.hostname`. `0.0.0.0` is not a dial target.

## Exit Criteria Status

- [x] `clm chat <hermes-name>` plumbing wires backend correctly (unit-tested; manual roundtrip is in #322 Slice 1 acceptance).
- [x] `clm chat <openclaw-name>` byte-for-byte unchanged — existing `tests/test_cli_chat.py` openclaw tests pass verbatim; `tests/test_core_chat.py` passes verbatim.
- [x] Manifest validator rejects `features.chat.type` outside `{"openai", "websocket"}` (`test_load_manifest_rejects_unknown_chat_type` in `tests/test_registry.py`).
- [x] New hermes installs persist `agent_record.config.api_server.host == "0.0.0.0"` (`test_install_hermes_persists_zero_bind_in_hosts_json` in `tests/test_install.py`).
- [x] Existing hermes installs with `"127.0.0.1"` are migrated; second configure is a no-op (`TestHermesBindMigration` in `tests/test_hermes_configure.py`).
- [x] `HERMES_API_SERVER_KEY` sourced from `secrets.json`; missing key produces friendly error (`TestHermesChat::test_missing_api_server_key`).
- [x] `make test` green (1623 passed).
- [x] `make lint` clean.
- [ ] Manual verification (`ss -tlnp` on real hermes host) — deferred to deploy-time check by the operator; the migration runs on `clm agent configure <name>`.

## Files Touched

- Modified: `src/clawrium/core/install.py`, `src/clawrium/core/lifecycle.py`, `src/clawrium/core/registry.py`, `src/clawrium/core/chat.py`, `src/clawrium/cli/chat.py`, `src/clawrium/platform/registry/hermes/manifest.yaml`, `src/clawrium/platform/registry/openclaw/manifest.yaml`, `pyproject.toml`, `tests/test_cli_chat.py`, `tests/test_hermes_configure.py`, `tests/test_install.py`, `tests/test_registry.py`
- New: `src/clawrium/core/chat_hermes.py`, `tests/test_chat_hermes.py`

## Deferred (not in this PR)

Per Slice 1 scope:
- Multi-turn history (Slice 2 / phase 2).
- SSE streaming (Slice 3 / phase 3).
- Polished error messaging for `--session` warning, 401/403 remediation hints, service-down hints (Slice 4 / phase 4).
- `docs/research/aichat.md` (Slice 5 / phase 5).

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-05-11
**Model**: claude-opus-4-7

```prompt
/itx-execute 330
```

</details>
