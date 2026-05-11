# Execution Scaffolding — Issue #322

**Mode**: multi-phase (5 phases, outcome-driven)

Each phase corresponds to one slice from `.itx/322/00_PLAN.md` and ships as its own PR. Phase 1 is the prerequisite; phases 2, 3, 4 can run in parallel after phase 1; phase 5 is independent.

Shipping order: **1 → (2 ‖ 3) → 4 → 5**.

---

## Phase 1 — `clm chat <hermes>` works end-to-end from any clm machine

**User outcome**: a user can run `clm chat <hermes-name>` from a different machine on the LAN and roundtrip a single message through hermes. No SSH tunnel. Openclaw chat behavior identical.

**Entry Criteria**:
- Plan committed at `.itx/322/00_PLAN.md` (✅ — PR #328 merged).
- Hermes upstream `API_SERVER_HOST` env var confirmed honored at the pinned tag (✅ — verified in plan against `gateway/platforms/api_server.py:583` of `NousResearch/hermes-agent@v2026.5.7`).
- `clm chat <openclaw-name>` works on `main` (baseline regression target).

**Exit Criteria**:
- `clm chat <hermes-name>` from a separate clm machine roundtrips a single user message and prints the agent reply.
- `clm chat <openclaw-name>` byte-for-byte unchanged (existing `tests/test_cli_chat.py::TestOpenClawChat` + `tests/test_core_chat.py` pass verbatim).
- Manifest validator rejects `features.chat.type` values outside `{"openai", "websocket"}` (new test in `tests/test_registry.py`).
- New hermes installs persist `agent_record.config.api_server.host == "0.0.0.0"` in hosts.json (new test in `tests/test_install.py`).
- Existing hermes installs with `host: "127.0.0.1"` are opportunistically rewritten to `"0.0.0.0"` on the next `clm agent configure <name>`; second configure is a no-op (new tests in `tests/test_hermes_configure.py` or `tests/test_lifecycle.py`).
- `HERMES_API_SERVER_KEY` sourced from `secrets.json` via `get_instance_secrets`; missing/invalid key produces a friendly error mirroring `lifecycle.py:748-754` (test in `tests/test_cli_chat.py::TestHermesChat::test_missing_api_server_key`).
- `make test` green; `make lint` clean.
- Manual verification: `ss -tlnp` on a real hermes host shows the gateway listening on `0.0.0.0:8642` after configure.

**Dependencies**: None (this is the foundation).

**Files Affected**:
- `src/clawrium/core/install.py:847-851` — change `host: "127.0.0.1"` → `"0.0.0.0"`.
- `src/clawrium/core/lifecycle.py` (hermes branch, ~734-771) — opportunistic 127.0.0.1→0.0.0.0 migration when merging `api_server` config.
- `src/clawrium/platform/registry/hermes/manifest.yaml` — add `features.chat.type: openai`.
- `src/clawrium/platform/registry/openclaw/manifest.yaml` — add `features.chat.type: websocket`.
- `src/clawrium/core/registry.py` (TypedDicts ~130-144, validator ~498-511) — extend `FeaturesConfig` and `_validate_features` with closed enum.
- `src/clawrium/cli/chat.py:78` and surrounding — remove openclaw type gate; dispatch by `features.chat.type`; add `_build_hermes_backend()`.
- `src/clawrium/core/chat.py` — extract `ChatBackend` Protocol; `OpenClawChatClient` conforms (no behavior change).
- `src/clawrium/core/chat_hermes.py` — **new**: `HermesOpenAIBackend` with non-streaming, single-turn `POST /v1/chat/completions` + bearer hydration.
- `pyproject.toml` — add `httpx>=0.27`.
- `tests/test_install.py`, `tests/test_lifecycle.py` (or `tests/test_hermes_configure.py`), `tests/test_registry.py`, `tests/test_cli_chat.py`, `tests/test_chat_hermes.py` (new) — covering each exit criterion above.

**Complexity**: complex (server-side bind change + manifest schema + protocol abstraction + new backend + dispatch).

**Out of Scope** (deferred to later phases):
- Multi-turn history (phase 2).
- Streaming/SSE (phase 3).
- Polished error messages beyond missing-key (phase 4).
- aichat investigation doc (phase 5).

---

## Phase 2 — Multi-turn conversations remember context

**User outcome**: a user sends "what's 2+2?", agent says "4", user sends "double that", agent says "8". History persists across turns within one REPL session.

**Entry Criteria**:
- Phase 1 merged; `clm chat <hermes>` works for single-turn.

**Exit Criteria**:
- `HermesOpenAIBackend` maintains a `_history: list[dict]` populated with each user message + assistant reply.
- Second `send_message` call within the same backend instance sends the prior turn(s) in the `messages` array (verified by mocked-httpx test in `tests/test_chat_hermes.py::test_history_grows_across_turns`).
- `/reset` REPL command clears the history (mirror semantics with openclaw if it has one, otherwise document the new command in `--help`).
- `make test` green; `make lint` clean.
- Manual verification: 3-turn conversation on a real hermes install demonstrates context retention.

**Dependencies**: Phase 1.

**Files Affected**:
- `src/clawrium/core/chat_hermes.py` — add `_history` accumulator and `/reset` hook.
- `src/clawrium/cli/chat.py` — wire `/reset` command in REPL loop.
- `tests/test_chat_hermes.py` — add history accumulation + reset tests.

**Complexity**: simple.

---

## Phase 3 — Responses stream as they're generated

**User outcome**: a user sees the agent's reply appear word-by-word, identical to `clm chat <openclaw-name>`, instead of waiting for the full response.

**Entry Criteria**:
- Phase 1 merged.

**Exit Criteria**:
- `HermesOpenAIBackend.send_message` uses `httpx.AsyncClient.stream()` against `/v1/chat/completions` with `stream: true` when supported.
- SSE chunks parsed correctly: `data: {...}` lines extracted, `data: [DONE]` sentinel terminates the stream, `:keep-alive` comments and other non-`data:` lines ignored without emitting deltas.
- `on_delta` callback fires per chunk; existing renderer at `cli/chat.py:186-191` works unchanged.
- Non-SSE response (content-type `application/json` or no `text/event-stream` header) falls back to single-JSON-response path.
- Tests in `tests/test_chat_hermes.py`: `test_streaming_deltas`, `test_sse_edge_cases` (DONE sentinel + keep-alive), `test_non_streaming_fallback`.
- `make test` green; `make lint` clean.
- Manual verification: streaming is visible in a real REPL session.

**Dependencies**: Phase 1. Can run in parallel with Phase 2 (different code paths in the same file; rebases will be cheap).

**Files Affected**:
- `src/clawrium/core/chat_hermes.py` — SSE parser + fallback branch.
- `tests/test_chat_hermes.py` — streaming + edge-case tests.

**Complexity**: moderate (SSE parsing edge cases).

---

## Phase 4 — Failures are obvious and recoverable

**User outcome**: when something's wrong, the user gets a clear message that tells them how to fix it, not a stack trace.

**Entry Criteria**:
- Phase 1 merged. Phases 2 and 3 can be in-flight or merged; phase 4 doesn't depend on them but benefits from a stable backend surface.

**Exit Criteria**:
- Missing/invalid `HERMES_API_SERVER_KEY` → `"Re-run 'clm agent install --type hermes ...'"` message (already in phase 1; keep, refine wording if needed).
- Service unreachable / connection refused → `"Check 'systemctl --user status hermes-<name>' on the agent host"`, plus a hint pointing at `clm agent configure` when the persisted bind looks stale (`host == "127.0.0.1"`).
- HTTP 401/403 from gateway → `"Token mismatch. Re-run 'clm agent configure <name>'."`
- `--session` passed to a hermes agent with a non-default value → dim warning (one line) explaining it's a no-op for OpenAI-typed agents; chat still starts.
- Every error path tested in `tests/test_cli_chat.py::TestHermesChat`.
- No raw `httpx`/network exception strings reach the user (sanitizer mirrors `cli/chat.py:309-317`).
- `make test` green; `make lint` clean.

**Dependencies**: Phase 1.

**Files Affected**:
- `src/clawrium/core/chat_hermes.py` — map exception types to friendly `ChatError` subclasses.
- `src/clawrium/cli/chat.py` — `--session` warning for openai-typed agents; remediation hint copy.
- `tests/test_cli_chat.py` — error-path tests for each failure surface.

**Complexity**: moderate (lots of small surfaces, each independently testable).

---

## Phase 5 — aichat investigation note

**User outcome**: future maintainers know why we built our own REPL instead of shelling out to aichat.

**Entry Criteria**: None — independent of all other phases.

**Exit Criteria**:
- `docs/research/aichat.md` exists.
- Covers: base-url config, history handling, model selection, error mapping.
- Records the reference-implementation-vs-sidecar tradeoff and the v1 decision.
- Linked from issue #322.

**Dependencies**: None.

**Files Affected**:
- `docs/research/aichat.md` — **new**.

**Complexity**: simple.

---

## Worktree / Branch Convention

Per `AGENTS.md`, parallel execution uses git worktrees:

```
~/workspace/ric03uec/clawrium/                  # main
~/workspace/ric03uec/clawrium-issue-322-p1/     # phase 1
~/workspace/ric03uec/clawrium-issue-322-p2/     # phase 2 (after phase 1 merges)
~/workspace/ric03uec/clawrium-issue-322-p3/     # phase 3 (after phase 1 merges)
…
```

Each phase ships as its own PR; commits cite `Refs #322` and the phase sub-issue.

---

<details>
<summary>Prompt Log</summary>

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-11T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 322
```

</details>
