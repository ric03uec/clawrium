# Issue 359 — Execution Log

Subtask D of #112: ZeroClaw documentation refresh to match `hermes.md` quality and reflect shipped behavior from subtasks A/B/C.

## Scope shipped

| File | Action | Why |
|---|---|---|
| `docs/agent-support/zeroclaw.md` | Full rewrite (180 → ~330 lines) | Match `hermes.md` structure: platforms, providers, channels, features, install/configure/chat/memory walkthrough, pairing, WebSocket frames, security, troubleshooting, deferred list. |
| `website/docs/agent-support/zeroclaw.md` | Full rewrite (mirror) | Same content, Docusaurus-style `/docs/guides/...` links in Next Steps. |
| `docs/agent-onboarding.md` | Targeted edits | Replace stale "minimal identity" line, correct ZeroClaw identity stage explanation, add pairing summary in agent-type quickref. |
| `website/docs/agent-support/integrations/atlassian.md` | Targeted edits | Remove false claims about ZeroClaw Atlassian wiring — integrations are deferred per #112 plan and `config.toml.j2` does not emit `[integrations]`. |
| `website/docs/agent-support/integrations/index.md` | Targeted edit | Same correction in the integrations index table. |

## Plan-vs-shipped deltas honored

Per the expanded scope on issue #359:

1. **Pairing handshake is automated.** Documented as `GET /pair/code` → `POST /pair` performed loopback during `configure`, with the resulting bearer token persisted to `hosts.json` under `agents.<name>.config.gateway.{auth,url}`. No operator-input step.
2. **Gateway binds `0.0.0.0` with `allow_public_bind=true` + `require_pairing=true`.** Documented verbatim. Added a dedicated **Security considerations** section covering the trusted-LAN threat model, token-as-auth-boundary, and SSH-tunnel recommendation for untrusted networks.
3. **`clm chat` over WebSocket.** Documented the `ws://<host>:42617/ws/chat` endpoint, `Authorization: Bearer <token>` header, and the relevant subset of the tagged-JSON frame envelope (`connected`, `chunk`, `thinking`, `tool_call`, `tool_result`, `done`, `error`, `chunk_reset`, `aborted`, `session_start` server frames; `message`, `connect`, `approval_response` client frames). Noted Rich-markup sanitization in `core/chat_zeroclaw.py`.
4. **7 workspace files, not 6, not 8.** Listed: `SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`, `MEMORY.md`, `HEARTBEAT.md`. `BOOTSTRAP.md` explicitly called out as runtime-generated + self-deleting + not in `clm agent memory show`. Reference: upstream `crates/zeroclaw-runtime/src/agent/personality.rs`.
5. **CLI surface is `clm agent memory show|edit|delete`** — not a top-level `clm memory` group. Documented positional file argument for `edit`, `--file` flag for single-delete, `--all --force` for wipe.
6. **`[personality]` block in `config.toml`** documented as part of the configure render with sensible defaults.
7. **`install.py preserved_gateway`** mentioned in the troubleshooting section ("clm chat fails after a reinstall" — explains why this is rare).

## Out-of-scope (documented as deferred, not as supported)

Integrations, hardware, tunnel providers, encrypted secrets, Composio, alternative memory backends, additional providers (Bedrock, Gemini, Azure OpenAI, Copilot, etc.) — all listed in the "Deferred items / follow-ups" section so a reader does not assume they work.

## Cross-tree corrections

The pre-existing `website/docs/agent-support/integrations/{index,atlassian}.md` pages claimed ZeroClaw supports Atlassian via `[integrations]` in `config.toml`. That claim is false in the shipped code:

- `src/clawrium/platform/registry/zeroclaw/templates/config.toml.j2` emits only `[gateway]`, `[providers.models.<name>]`, and `[personality]` — no `[integrations]` block.
- `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml` has no integration-rendering tasks.

Removed those claims from both files and pointed readers at the new ZeroClaw deferred-items section.

## Verification

| Check | Result |
|---|---|
| `npm --prefix website run build` | ✅ success (one pre-existing webpackbar warning about `vscode-languageserver-types`, unrelated to docs changes) |
| `make lint` | ✅ no ESLint warnings or errors |
| `make test` | ✅ 1886 passed (Python), 14 passed (GUI vitest) |
| Side-by-side review vs `hermes.md` | ✅ Same section headings, comparable depth and example density |
| Walk-through readability | ✅ `install → configure → chat → memory` is sufficient from the docs alone |

## Files modified

```
docs/agent-onboarding.md
docs/agent-support/zeroclaw.md
website/docs/agent-support/integrations/atlassian.md
website/docs/agent-support/integrations/index.md
website/docs/agent-support/zeroclaw.md
.itx/359/01_EXECUTION.md  (this file)
```

No source code changes.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-15T15:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 359
```

</details>
