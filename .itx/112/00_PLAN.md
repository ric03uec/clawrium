# Issue 112: Align ZeroClaw Onboarding with Native ZeroClaw

## Summary

Bring `clm`'s ZeroClaw integration up to feature parity with native
`zeroclaw onboard` (v0.7.5) so users familiar with upstream ZeroClaw see
the same lifecycle when they manage a ZeroClaw agent through clm. Scope is
restricted to **the providers, workspace files, memory, and chat surfaces
already supported by upstream ZeroClaw** — no additional providers are
introduced. Integrations (GitHub/Jira/Linear/Notion), hardware, tunnel
configuration, encrypted secrets, and Composio are explicitly deferred to
follow-up issues.

## Problem Statement

1. The `zeroclaw` registry entry is pinned to v0.5.7; upstream is v0.7.5.
2. Current `install.yaml` starts the daemon inline before configure runs,
   diverging from the install-disabled / configure-enables pattern used by
   `hermes`.
3. `config.toml.j2` reflects an outdated TOML schema. The v0.7.5 schema
   uses `[providers.models.<name>]` sub-tables with a `kind` discriminator;
   our template uses an obsolete top-level `default_provider = "custom:..."`
   string.
4. ZeroClaw's gateway is **not OpenAI-compatible**. The only chat surface
   it exposes is a `GET /ws/chat` WebSocket with tagged-JSON envelopes,
   pairing-token auth, and `127.0.0.1` bind by default. `clm chat
   zeroclaw` therefore does not work — the manifest has no `features.chat`
   entry and no client speaks ZeroClaw's WebSocket protocol.
5. Workspace scaffolding (`SOUL.md`, `AGENTS.md`, `TOOLS.md`,
   `IDENTITY.md`, `USER.md`, `MEMORY.md`, `HEARTBEAT.md`) is not rendered;
   `clm memory` does not route to ZeroClaw.
6. Documentation (`website/docs/agent-support/zeroclaw.md`, 180 lines) is
   thin compared to `hermes.md` (345 lines) and out of date.

## Research Findings

### Upstream ZeroClaw v0.7.5

| Surface | Source | Finding |
|---|---|---|
| Onboarding sections | `crates/zeroclaw-runtime/src/onboard/mod.rs` enum `Section` | 7 sections: Workspace, Providers, Channels, Memory, Hardware, Tunnel, Personality. (The "9 steps" referenced in the issue body is question count, not section count.) |
| Provider catalog | `docs/book/src/providers/catalog.md` | Native: anthropic, openai, ollama, bedrock, gemini, openrouter, openai-compatible, azure-openai, copilot, claude-code, telnyx, kilocli. Plan scope: anthropic, openai, ollama, openrouter only. |
| Workspace files | `crates/zeroclaw-runtime/src/agent/personality.rs` const `PERSONALITY_FILES` | `SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`, `HEARTBEAT.md`, `MEMORY.md`, `BOOTSTRAP.md`. `BOOTSTRAP.md` self-deletes after first run. |
| Memory backends | `crates/zeroclaw-memory/src/backend.rs` enum `MemoryBackendKind` | Sqlite (default), Lucid, Postgres, Qdrant, Markdown, None. |
| Gateway config | `crates/zeroclaw-config/src/schema.rs` line 2284 | `GatewayConfig { port: 42617, host: "127.0.0.1", require_pairing: true, allow_public_bind: false, paired_tokens: Vec<String> }`. |
| Chat endpoint | `crates/zeroclaw-gateway/src/ws.rs` handler `handle_ws_chat` | `GET /ws/chat` WebSocket. Auth via `Authorization: Bearer <token>` header, `Sec-WebSocket-Protocol: bearer.<token>`, or `?token=` query. |
| Pairing | `crates/zeroclaw-gateway/src/api_pairing.rs` | `GET /pair/code` returns the pairing code; client POSTs to `/pair` to mint a bearer token. |
| `zeroclaw agent` CLI | `src/main.rs` | Runs the runtime **in-process**, not against the daemon. Cannot be reused for clm chat. |

### Chat wire format (server frames)

`session_start`, `chunk`, `thinking`, `tool_call`, `tool_result`,
`approval_request`, `done` (with `full_response`, token counts, cost,
provider, model), `error`, `chunk_reset`, `connected`, `aborted`.

### Chat wire format (client frames)

`{"type":"connect", ...}` (optional handshake), `{"type":"message",
"content":"..."}`, `{"type":"approval_response", "request_id":"...",
"decision":"approve|deny|always"}`.

### Implications for clm

- ZeroClaw daemon must be bound `0.0.0.0` with `allow_public_bind=true` for
  LAN reachability. clm renders both keys in `config.toml`.
- A paired bearer token must be provisioned during `clm agent configure`
  and persisted to `hosts.json` under
  `agents.<n>.config.gateway.auth` (same shape openclaw uses, so
  `_extract_gateway_config` keeps working).
- A new chat backend `core/chat_zeroclaw.py` speaks the WebSocket
  protocol. Modelled on `OpenClawChatClient` for connection/error
  ergonomics, but with the ZeroClaw frame schema. Not the same as the
  `websocket` dispatch value (frame schemas differ; new value `zeroclaw`
  is introduced).

## Subtask Structure

Each subtask is **independently mergeable, testable, and deployable**.
Later subtasks extend earlier ones; they never modify earlier behavior.

### Subtask A — Core installation alignment (v0.7.5)

**Goal:** `clm agent install --type zeroclaw --host <h>` lands the v0.7.5
binary with the systemd unit dropped **disabled, not started**.

**Changes:**
- `manifest.yaml`: bump `version: 0.5.7` → `0.7.5` on all 5 platform
  entries; recompute SHA256s from the v0.7.5 release tarballs.
- `playbooks/install.yaml`: rewrite mirroring `hermes/install.yaml` —
  - Version-aware skip (re-running on the target version is a no-op;
    `--force` overrides).
  - Drop the systemd unit **disabled** and **not started**.
  - Remove the inline `config.toml` rendering; that moves to configure.
  - Scaffold `~/.zeroclaw/{workspace,state}/` at 0700.
  - Use `/usr/sbin/nologin` shell on the agent user.
- `manifest.yaml` `validate` stage: keep `zeroclaw --version`; drop the
  `~/.zeroclaw/config.toml` check (file is configure.yaml's job).

**Exit criteria:**
- Install on Raspberry Pi (armv7l), Ubuntu aarch64, Ubuntu x86_64.
- `zeroclaw --version` reports `0.7.5`.
- `systemctl status zeroclaw-<n>` shows `inactive (dead)` with the unit
  file present.
- Re-running install is a no-op; `--force` reinstalls cleanly.

**Out of scope:** providers, chat, workspace files, memory CLI.

### Subtask B — Providers + WebSocket chat backend

**Goal:** `clm agent configure <n>` selects a provider, automates the
pairing handshake, starts the daemon. `clm chat <n>` opens a WebSocket
session and round-trips a message.

**Changes:**

*Config template* — `templates/config.toml.j2` rewritten for the v0.7.5
schema:

```toml
[gateway]
host = "0.0.0.0"
port = {{ gateway_port }}
allow_public_bind = true
require_pairing = true

default_provider = "<name>"
default_model = "<id>"

[providers.models.<name>]
kind = "<anthropic|openai|ollama|openrouter>"
api_key = "..."   # or base_url for ollama
model = "..."
```

Only the four supported providers may be emitted: `anthropic`, `openai`,
`ollama`, `openrouter`. Integration emission (github/jira/etc.) is removed
from this template and re-introduced in a follow-up issue outside #112.

*Configure playbook* — `playbooks/configure.yaml`:
- Render `config.toml` (no_log, 0600).
- Start the daemon, wait for `/health/providers` 200.
- Pairing handshake: `GET /pair/code` → derive token → `POST /pair` →
  capture bearer token → write to `hosts.json` under
  `agents.<n>.config.gateway.auth`.
- Persist `config.gateway.url = ws://<host-ip>:<port>/ws/chat`.

*Manifest* — add the chat feature flag:

```yaml
features:
  chat:
    type: zeroclaw   # new dispatch value
```

*Chat backend* — new file `src/clawrium/core/chat_zeroclaw.py`:
- WebSocket client implementing the `ChatBackend` protocol from
  `core/chat.py`.
- Connects with `Authorization: Bearer <token>`.
- Sends `{"type":"message","content":"..."}`.
- Reads `chunk` / `thinking` / `tool_call` / `tool_result` / `done` /
  `error` frames; surfaces `chunk` deltas; terminates on `done` / `error`.
- Client-side conversation history, capped à la `HermesOpenAIBackend`.

*Dispatch* — `src/clawrium/cli/chat.py`:
- Add `elif chat_type == "zeroclaw":` branch + `_build_zeroclaw_backend()`.
- Do **not** reuse the `websocket` key: openclaw's frame schema is
  different from zeroclaw's.

**Exit criteria:**
- `clm agent configure <n>` walks provider selection, completes the
  pairing handshake without operator interaction, ends with the service
  `active (running)`.
- `clm chat <n>` connects, sends "hello", receives a streamed reply.
- TOML rendering covered by unit tests for each of the four providers.
- WebSocket frame parsing covered by unit tests with a mocked socket.

**Out of scope:** workspace MD files, memory CLI.

### Subtask C — Workspace files + memory CLI wiring

**Goal:** `~/.zeroclaw/workspace/` populated with the 7 MD files on
configure. `clm memory read|write|delete|info <n>` round-trips against
them, mirroring the hermes wiring.

**Changes:**

*Workspace templates* — new files under
`src/clawrium/platform/registry/zeroclaw/templates/workspace/`:
- `SOUL.md.j2`
- `AGENTS.md.j2`
- `TOOLS.md.j2`
- `IDENTITY.md.j2`
- `USER.md.j2`
- `MEMORY.md.j2`
- `HEARTBEAT.md.j2`

`BOOTSTRAP.md` is **not** rendered — the runtime generates it on first
boot and self-deletes after use.

All seven render with `force: no` so subsequent configure runs do not
clobber user edits.

*Configure playbook* additions:
- Render the seven templates into `~/.zeroclaw/workspace/` (0600,
  agent-owned).
- Render a `[personality]` block in `config.toml.j2` with the agent name,
  default timezone, and communication-style defaults.

*Memory CLI wiring* — mirror hermes:
- Add `workspace.memory_path: "~/.zeroclaw/workspace"` to `manifest.yaml`.
- Verify hermes `memory_*.yaml` playbooks operate on individual files in
  a directory before mirroring; adjust `memory_path` semantics if hermes
  actually points at a single file. (Cheap check at the start of the
  subtask.)
- Add `playbooks/memory_{read,write,delete,info}.yaml` copied from hermes
  with paths adjusted for the zeroclaw layout.

**Exit criteria:**
- `clm agent configure <n>` populates `~/.zeroclaw/workspace/` with 7
  files.
- `clm memory write <n> --name notes.md --content "x"` lands content;
  `clm memory read <n> --name notes.md` returns it; `clm memory info <n>`
  lists files; `clm memory delete <n> --name notes.md` removes it.
- Daemon restart picks up workspace changes without regressing chat from
  Subtask B.

**Out of scope:** integrations, hardware, tunnel, encrypted secrets,
Composio (Subtask D and beyond).

### Subtask D — Documentation refresh

**Goal:** ZeroClaw documentation matches the depth, structure, and quality
of `hermes.md`. Both the source tree (`docs/`) and the Docusaurus build
(`website/docs/`) updated.

**Sequencing:** Lands **after** A + B + C merge so docs reflect shipped
behavior, not aspirational behavior.

**Changes:**
- Rewrite `docs/agent-support/zeroclaw.md` and
  `website/docs/agent-support/zeroclaw.md` mirroring `hermes.md`:
  - Overview / positioning / when to pick ZeroClaw.
  - Supported platforms (5 manifest entries).
  - Install / configure / start / chat / memory lifecycle with
    copy-pastable `clm` commands.
  - Provider matrix (anthropic, openai, ollama, openrouter) with required
    keys.
  - Workspace files reference (the 7 MD files + one-line purpose for each,
    sourced from upstream `personality.rs`).
  - Pairing handshake explanation (why it exists, how clm automates it).
  - `clm chat` and `clm memory` examples.
  - Troubleshooting section matching `hermes.md` structure.
  - Limitations / out-of-scope (integrations, hardware, tunnel, encrypted
    secrets, Composio).
- Audit `docs/agent-onboarding.md` and `docs/index.md` for stale ZeroClaw
  references after the v0.7.5 schema change; update inline.
- Update any `website/docs/agent-support/{providers,channels,
  integrations}/` page that references ZeroClaw.

**Exit criteria:**
- `npm --prefix website run build` succeeds with no broken links.
- Side-by-side review against `hermes.md` confirms structural parity (same
  section headings, comparable depth, comparable example density).
- A reader unfamiliar with ZeroClaw can complete
  `install → configure → chat → memory` using only the docs.

**Out of scope:** content for the deferred integrations / hardware /
tunnel features.

## Files Modified — Summary

| Path | Subtask | Action |
|---|---|---|
| `src/clawrium/platform/registry/zeroclaw/manifest.yaml` | A, B, C | extend (version, features.chat, workspace.memory_path) |
| `src/clawrium/platform/registry/zeroclaw/playbooks/install.yaml` | A | rewrite |
| `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml` | B, C | rewrite + extend |
| `src/clawrium/platform/registry/zeroclaw/templates/config.toml.j2` | B, C | rewrite + extend |
| `src/clawrium/platform/registry/zeroclaw/templates/workspace/*.md.j2` | C | new (7 files) |
| `src/clawrium/platform/registry/zeroclaw/playbooks/memory_{read,write,delete,info}.yaml` | C | new |
| `src/clawrium/core/chat_zeroclaw.py` | B | new |
| `src/clawrium/cli/chat.py` | B | add zeroclaw dispatch branch |
| `docs/agent-support/zeroclaw.md` | D | rewrite |
| `website/docs/agent-support/zeroclaw.md` | D | rewrite |
| `tests/test_zeroclaw_*.py` | A, B, C | new per phase |

## Risks & Open Items

1. **Pairing handshake automation.** Pairing typically expects a human to
   read the code off the daemon and enter it on the client. Plan
   automates this by reading the code directly from `GET /pair/code`. If
   upstream enforces operator confirmation, configure.yaml will need an
   interactive prompt. Will verify against
   `crates/zeroclaw-gateway/src/api_pairing.rs` at execution time.
2. **`workspace.memory_path` semantics.** Confirm whether hermes's memory
   CLI points at a directory or a single file before mirroring. Cheap
   check at the start of Subtask C.
3. **Test fixtures.** Subtasks A and C may need a real LAN host for full
   coverage; unit tests cover rendering but not Ansible execution.

## Test Strategy

- **Unit:** TOML template rendering with each supported provider, with
  and without integrations; WebSocket frame parsing; workspace template
  rendering with default values.
- **Integration:** `make test` after each subtask; manual round-trip on a
  real host per subtask exit criteria.

## Subtasks

- **A** — Core installation alignment (v0.7.5)
- **B** — Providers + WebSocket chat backend
- **C** — Workspace files + memory CLI wiring
- **D** — Documentation refresh

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-15T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Review the plan for issue one one two. Make sure it aligns with how
Hermes agent is set up. I only want the integration and providers that
are currently supported to work with, ZeroClaw No additional providers
are needed. This the structure can be to first make sure the core
installation works. And then add support for, providers. Then add
support for memory, and agents agent and sole and tools file. And then
finally, support for, integrations like Slack and other things. For
now, leave out the integrations. I will test it using CLM chat command.
Do a deep research on the latest ZeroClaw and, make sure the plan
accounts for the latest zero claw structure.
```

Follow-ups during the planning session:

```prompt
For point one, don't defer chat testability. That's the only way I can
test zero claw. Read upstream documents to figure out what's the way to
implement this. If you have to write the new chat back end, that's fine.
Use the template used in OpenClaw If that doesn't work, suggest what's
the next best or alternative. For point two, I don't understand why a
new stage is needed. The memory I'm referring to is the SoleMD and
personality MD and other similar files. They're already part of the
workflow. I don't need changes to any onboarding state machine for this
implementation. The state machine will remain exactly the same as other
agents. For point three, yes. CLM memory command should work exactly
like other claws for this stage. Mirror the Hermes wiring. Ignore point
four. That doesn't need to be implemented right now. Yes. It should be
executed as subtasks. Plan accordingly. Each subtask should be
independently verifiable and testable. And deployable.
```

```prompt
Also, add a task to update documentation in the web with the new
changes. I want the ZeroClaw documentation to be of the same quality as
OpenClaw and Hermes agent.
```

</details>
