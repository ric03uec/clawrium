# ZeroClaw

ZeroClaw is the [ZeroClaw Labs Rust agent runtime](https://github.com/zeroclaw-labs/zeroclaw) — a single statically linked daemon that exposes a WebSocket chat surface, manages a file-based personality workspace, and pairs with clients over a token-mint handshake.

**Status:** 🚧 In Development

**Best for:** Low-resource hosts (Raspberry Pi 2/3 armv7l, aarch64 SBCs, small x86_64 servers) that need a minimal, single-binary AI agent with file-based personality and a LAN-reachable chat endpoint. ZeroClaw is intentionally narrower than [Hermes](hermes.md) (no OpenAI-compatible HTTP, no MCP integrations) and narrower than [OpenClaw](openclaw.md) (no Discord/web channels).

**Pinned version:** `v0.7.5`. The release tarball SHA256 is pinned per architecture in `src/clawrium/platform/registry/zeroclaw/manifest.yaml` for five `(os, os_version, arch)` combinations; every version bump requires re-pinning all five.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported (use a different claw) |
| 📋 | Deferred — tracked as follow-up |

---

## Supported Platforms

The same statically linked `zeroclaw` binary is reused across Ubuntu major versions for the same architecture (identical SHA256 per arch). The `(os, os_version, arch)` tuple is matched against the host facts at install time.

| OS | Version | Architecture | Min RAM | Notes |
|----|---------|--------------|--------:|-------|
| Debian | 13 (trixie) | `armv7l` | 512 MB | Raspberry Pi 2 / 3 |
| Ubuntu | 22.04 | `aarch64` | 1024 MB | Raspberry Pi 4 / 5, aarch64 SBCs |
| Ubuntu | 24.04 | `aarch64` | 1024 MB | Raspberry Pi 4 / 5, aarch64 SBCs |
| Ubuntu | 22.04 | `x86_64` | 1024 MB | Desktops / servers |
| Ubuntu | 24.04 | `x86_64` | 1024 MB | Desktops / servers |

No GPU required. Python ≥ 3.9 is listed as a manifest dependency for parity with the rest of the agent fleet; the daemon itself is a static Rust binary and has no Python runtime requirement.

---

## Provider Support

ZeroClaw upstream supports a long catalog of providers (anthropic, openai, ollama, bedrock, gemini, openrouter, openai-compatible, azure-openai, copilot, claude-code, telnyx, kilocli). clawctl exposes only the four that are wired end-to-end through `config.toml` rendering and validated by the configure playbook.

| Provider | Status | clawctl `provider.type` | `kind` discriminator | Rendered keys |
|----------|:------:|---------------------|----------------------|---------------|
| **[Anthropic](providers/anthropic.md)** | ✅ | `anthropic` | `anthropic` | `api_key`, `model` |
| **[OpenAI](providers/openai.md)** | ✅ | `openai` | `openai` | `api_key`, `model` |
| **[Ollama / OpenAI-compatible](providers/ollama.md)** | ✅ | `ollama` | `ollama` | `base_url`, `model` (no api_key) |
| **[OpenRouter](providers/openrouter.md)** | ✅ | `openrouter` | `openrouter` | `api_key`, `model` |
| **AWS Bedrock** | 📋 | — | — | Deferred (no follow-up issue yet) |
| **Google Gemini / Vertex** | 📋 | — | — | Deferred |
| **Azure OpenAI** | 📋 | — | — | Deferred |
| **Copilot / Claude Code / Telnyx / Kilocli** | 📋 | — | — | Deferred |

`config.toml` is rendered from a Jinja template that hard-allows only the four `kind` values above; any other `provider.type` causes the configure playbook to fail with a remediation message.

---

## Channel Support

ZeroClaw's only chat surface is the daemon's own WebSocket endpoint at `GET /ws/chat`. `clawctl agent chat <name>` is a WebSocket client that speaks the daemon's tagged-JSON frame protocol.

| Channel | Status | Notes |
|---------|:------:|-------|
| **`clawctl agent chat <zeroclaw-name>`** | ✅ | Connects to `ws://<host>:42617/ws/chat` with `Authorization: Bearer <paired-token>`. See [Use the WebSocket chat surface](#3-use-the-websocket-chat-surface). |
| **OpenAI-compatible HTTP API** | ❌ | Not exposed by upstream ZeroClaw. Use [Hermes](hermes.md) when an OpenAI-style HTTP endpoint is required. |
| **[Discord](channels/discord.md)** | ✅ | Native — rendered as `[channels.discord]` in `config.toml`. Bot token is **inline TOML**, not env-based (differs from hermes). Schema follows zeroclaw v0.7.5 upstream: `bot_token`, `allowed_guilds`, `allowed_users`, `reply_to_mentions_only`, `draft_update_interval_ms`. Configure via `clawctl agent configure <name> --stage channels`. |
| **Slack** | ❌ | Not supported (use [OpenClaw](openclaw.md) or [Hermes](hermes.md)). Tracked as a follow-up. |
| **Web / WhatsApp / Telegram / Email / Matrix** | ❌ | Not supported. |

---

## Feature Support

| Feature | Status | Notes |
|---------|:------:|-------|
| **WebSocket chat endpoint** | ✅ | `GET /ws/chat` on the daemon's gateway port (default `42617`). Auth: `Authorization: Bearer <token>` minted by the pairing handshake. |
| **Multi-provider** | ✅ | One active provider per agent, rendered as `[providers.models.<name>]` in `config.toml`. Switch providers by re-running `clawctl agent configure <name> --stage providers`. |
| **Workspace personality files** | ✅ | 7 files in `~/.zeroclaw/workspace/` (`SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`, `MEMORY.md`, `HEARTBEAT.md`). Rendered with `force: no` so re-configure never clobbers user edits. |
| **Memory CLI (`clawctl agent memory get --agent / edit / delete`)** | ✅ | Dispatched via `workspace.memory_path` + `features.memory: true` in the manifest. Surface is identical to hermes / openclaw. |
| **Pairing handshake** | ✅ | Automated by `clawctl agent configure`. Reads `/pair/code`, exchanges for a bearer token at `/pair`, persists the token to `hosts.json` under `agents.<name>.config.gateway.auth`. |
| **LAN-reachable gateway** | ✅ | Bound to `0.0.0.0` with `allow_public_bind = true` + `require_pairing = true`. The pairing token is the only auth boundary. See [Security considerations](#security-considerations). |
| **Auto-restart** | ✅ | Systemd unit `zeroclaw-<agent_name>.service` with `Restart=on-failure`, `RestartSec=5`. |
| **Log streaming** | ✅ | `journalctl -u zeroclaw-<agent_name>.service` on the agent host. |
| **Onboarding wizard** | ✅ | 4 stages: `providers` (required) → `identity` (auto-skipped) → `channels` (required, CLI confirm) → `validate` (3 local checks: agent install record, provider config + API key, provider connectivity). |
| **Personality block in `config.toml`** | ✅ | `[personality]` with `name`, `timezone`, `communication_style` defaults; rendered with `force: no` semantics through Ansible's template default — re-running configure preserves the file because `notify` only fires when content actually changes. |
| **Bootstrap file (`BOOTSTRAP.md`)** | ✅ | **Not rendered by clawctl.** The ZeroClaw daemon generates `BOOTSTRAP.md` on first boot and self-deletes it after use. Never appears in `clawctl agent memory get --agent`. |
| **[GitHub integration](integrations/github.md)** | ✅ | Two-layer wiring (#422): tokens land in a systemd drop-in (`/etc/systemd/system/zeroclaw-<name>.service.d/10-zeroclaw-env.conf`) so the daemon's environment has `GITHUB_TOKEN`, AND in `[autonomy] shell_env_passthrough` in `config.toml` so the agent's shell tool can actually see them (required: zeroclaw auto-strips `_TOKEN`-pattern vars unless explicitly allow-listed). `gh auth login --with-token` runs as a soft-dep convenience when `gh` is on the host. |
| **Jira / GitLab / Linear / Notion integrations** | 📋 | Deferred. No native consumer in zeroclaw v0.7.5; would require either a `[mcp.servers]` block (potential future path) or per-integration env passthrough. Tracked as a follow-up. |
| **Hardware support (GPIO / serial / debug probes)** | 📋 | Deferred. |
| **Tunnel providers (Cloudflare / Tailscale / Ngrok / custom)** | 📋 | Deferred. Reach the gateway over your own SSH tunnel or LAN. |
| **Encrypted secrets (ChaCha20-Poly1305)** | 📋 | Deferred. |
| **Composio / Sovereign tool modes** | 📋 | Deferred. |
| **Memory backends beyond Markdown** (Sqlite / Lucid / Postgres / Qdrant / None) | 📋 | Deferred. Current iteration uses the upstream default backend; clawctl's memory CLI only sees the workspace MD files. |

---

## Getting Started

### 1. Install ZeroClaw

```bash
clawctl agent create --type zeroclaw --host <host-alias> --name <agent-name>
```

What happens:

1. The host's `(os, os_version, arch)` is matched against the manifest's 5 platform entries. Unknown architecture fails with a clear remediation message.
2. The release tarball is fetched from `https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.7.5/zeroclaw-<arch-triple>.tar.gz` and verified against the SHA256 pinned in `manifest.yaml`.
3. A dedicated Linux user (`<agent-name>`) is created with `/usr/sbin/nologin` (service account, no interactive shell).
4. The binary is dropped at `/home/<agent-name>/bin/zeroclaw` (mode 0755, owned by the agent user). `~/.zeroclaw/` is created mode 0700.
5. A systemd unit `/etc/systemd/system/zeroclaw-<agent-name>.service` is dropped, **disabled and not started**:

   ```ini
   [Unit]
   Description=ZeroClaw AI Assistant (<agent-name>)
   After=network.target

   [Service]
   Type=simple
   User=<agent-name>
   WorkingDirectory=/home/<agent-name>/.zeroclaw
   ExecStart=/home/<agent-name>/bin/zeroclaw daemon
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

6. Re-running install on a host that already has the target version is a no-op (version skip). `--force` (via the `force_install` extra-var) reinstalls cleanly.

Install is a pure "binary present, unit dropped" step. No `config.toml` is rendered, no service is started, no provider is selected. Step 2 (`configure`) is the one that turns the daemon on.

### 2. Configure the agent

```bash
clawctl agent configure <agent-name>
```

The wizard walks through:

| Stage | Behavior |
|-------|----------|
| **providers** | Required. Pick from your registered clawctl providers; clawctl validates connectivity via `provider_test`. |
| **identity** | Auto-skipped. ZeroClaw manages its own identity through the workspace MD files (`SOUL.md`, `IDENTITY.md`, …) which clawctl renders below — there is no separate identity wizard. |
| **channels** | Required. ZeroClaw confirms the always-on CLI channel and offers a `discord` opt-in. Selecting `discord` prompts for the bot token (persists to `secrets.json` as `DISCORD_BOT_TOKEN`) plus optional allowlists; clawctl renders the result as `[channels.discord]` in `~/.zeroclaw/config.toml`. Slack remains unsupported on ZeroClaw — use [Hermes](hermes.md) or [OpenClaw](openclaw.md) for Slack. |
| **validate** | Local validation only, three steps for zeroclaw: (1) agent install record, (2) provider config + API key, (3) provider connectivity. The control-machine SOUL.md check is skipped — zeroclaw owns its identity through `~/.zeroclaw/workspace/` on the agent host, not under `~/.config/clawrium/agents/zeroclaw/`. The playbook's own post-render readiness probe (`GET /health/providers`) is separate from this stage. The manifest's `binary_check` task (`zeroclaw --version`) is not dispatched yet — remote version verification is planned. |

Configure renders TWO things on the agent host, then runs the pairing handshake against the freshly started daemon.

#### `~/.zeroclaw/config.toml` (mode 0600, owner `<agent-name>`)

```toml
[gateway]
host = "0.0.0.0"
port = 42617
allow_public_bind = true
require_pairing = true

default_provider = "<provider-name>"
default_model = "<model-id>"

[providers.models.<provider-name>]
kind = "anthropic"          # or "openai" / "ollama" / "openrouter"
api_key = "..."             # omitted for ollama
model = "<model-id>"
# base_url = "..."          # ollama only

[personality]
name = "<agent-name>"
timezone = "UTC"
communication_style = "direct, concise"
```

Per-provider rendering:

| clawctl `provider.type` | Rendered `kind` | `api_key` | `base_url` | Notes |
|---------------------|------------------|-----------|------------|-------|
| `anthropic` | `anthropic` | yes (from `provider_api_key` extra-var) | — | — |
| `openai` | `openai` | yes | — | — |
| `ollama` | `ollama` | — | `<provider.endpoint>` (as-is) | No API key. Endpoint must be reachable from the **agent host**, not just your control machine. |
| `openrouter` | `openrouter` | yes | — | — |

#### `~/.zeroclaw/workspace/` (mode 0700, files mode 0600)

Seven personality files seed the daemon on first start:

| File | One-line purpose |
|------|------------------|
| `SOUL.md` | High-level voice + values the agent embodies. |
| `IDENTITY.md` | Role and behavioral boundaries. |
| `USER.md` | User profile and preferences. |
| `AGENTS.md` | Defaults and examples for any sub-agents this instance delegates to. |
| `TOOLS.md` | Built-in and custom tool registry. |
| `MEMORY.md` | Free-form notes scratchpad. |
| `HEARTBEAT.md` | Cadence / recovery prompts for long-running sessions. |

All seven are rendered with `force: no` so subsequent `clawctl agent configure` runs **never** clobber operator edits.

`BOOTSTRAP.md` is intentionally **not** rendered by clawctl — the ZeroClaw runtime generates it on first daemon start and self-deletes it after use. It will never appear in `clawctl agent memory get --agent`. Reference: upstream `crates/zeroclaw-runtime/src/agent/personality.rs` const `PERSONALITY_FILES`.

#### Pairing handshake

Once the daemon is started, configure runs an automated two-step handshake against the loopback gateway:

```text
GET  http://127.0.0.1:42617/pair/code     -> { "code": "<one-shot-code>" }
POST http://127.0.0.1:42617/pair
     body: { "code": "<one-shot-code>" }  -> { "token": "<bearer-token>" }
```

Both calls happen over `127.0.0.1` so the code and token never traverse the LAN before pairing completes. The resulting bearer token is persisted to `hosts.json` under:

```text
agents.<agent-name>.config.gateway.auth = "<bearer-token>"
agents.<agent-name>.config.gateway.url  = "ws://<agent-host>:42617/ws/chat"
```

Re-running `clawctl agent configure <agent-name>` (or `sync` or `restart`) **always re-pairs** and overwrites the persisted token (issue #437). Live chat sessions on **other machines** must reconnect on their next message — `clawctl agent chat` on the local machine reloads `hosts.json` automatically on a 401 and reconnects transparently. See [Gateway token lifecycle](#gateway-token-lifecycle) below for the full contract.

A non-fatal warning is surfaced when the post-configure readiness probe (`GET /health/providers`) returns 401: the gateway is reachable but the provider credentials likely mismatch the API key supplied in `config.toml`. Re-run with the correct key.

#### Gateway token lifecycle

The zeroclaw daemon mints its bearer through a loopback `/pair/code` → `/pair` handshake. The daemon does not persist that bearer across systemd restarts, so `clawctl` enforces a single invariant: every lifecycle op (`install`, `configure`, `sync`, `restart`) ends with a fresh pair handshake and an atomic write to `hosts.json.gateway.auth`. There is no idempotent-skip path and no `force_repair` opt-out — branching here was the cause of issue #437.

Trade-off (accepted): every `sync`/`restart` invalidates in-flight chat sessions on other machines. The CLI emits a single `gateway_token_rotated` yellow notice when this happens, including the agent name so you know which remote sessions need to reconnect.

### 3. Use the WebSocket chat surface

```bash
clawctl agent chat <agent-name>
```

What clawctl does:

1. Reads `agents.<agent-name>.config.gateway.{auth,url}` from `hosts.json`.
2. Connects to `ws://<host>:42617/ws/chat` with header `Authorization: Bearer <token>`.
3. Streams stdin lines as `message` frames; renders streamed reply chunks back to the terminal.

The frame envelope (relevant subset, useful when troubleshooting):

| Direction | `type` | Purpose |
|-----------|--------|---------|
| Server → client | `session_start` | Session metadata at the start of a turn. |
| Server → client | `connected` | Handshake acknowledged. |
| Server → client | `chunk` | Streamed reply delta. The client appends `text` (or equivalent) to the visible response. |
| Server → client | `thinking` | Model's reasoning trace (rendered separately when present). |
| Server → client | `tool_call` / `tool_result` | Tool dispatch / result, for tools the agent invokes. |
| Server → client | `done` | Terminal frame. Carries the final response, token counts, cost, provider, model. |
| Server → client | `error` | Terminal frame. Carries an `error` / `message` field. |
| Server → client | `chunk_reset` / `aborted` | Stream control (rare; emitted on cancellation). |
| Server → client | `approval_request` | Terminal frame for `clawctl agent chat`. The current client does **not** support inline tool approval — receipt closes the WebSocket and raises a remediation error. Pre-approve tools in `~/.zeroclaw/config.toml` on the agent host. |
| Client → server | `message` | `{"type":"message","content":"<prompt>"}` |
| Client → server | `connect` | Protocol-level handshake frame; `clawctl agent chat` does not send this — it relies on the bearer header alone. |
| Client → server | `approval_response` | Defined upstream; **not sent by `clawctl agent chat`** (the session is terminated on `approval_request` instead). |

Server-supplied text is passed through `sanitize_server_text` in `core/chat_zeroclaw.py` before it reaches the terminal — every visible field is stripped of C0/C1 controls, zero-width codepoints, BIDI overrides, and line/paragraph separators. Rich-markup escaping is the responsibility of the CLI render layer, not this sanitizer.

#### Off-host access from the control machine

The gateway binds `0.0.0.0:42617` so any host on the same LAN can reach it once it holds the pairing token. The token is the only auth boundary — treat it like an API key.

`clawctl agent chat` rebuilds the gateway URL from `hosts[<host>].hostname` (the registered primary address), not from `127.0.0.1` — see `_reconstruct_gateway_url` in `cli/chat.py`. A plain `ssh -L 42617:…` tunnel therefore **does not** redirect `clawctl agent chat`; the client still dials the registered hostname directly. Two workable paths:

1. **Verify with a raw WebSocket client.** Open `ssh -L 42617:127.0.0.1:42617 <user>@<agent-host>`, then point `wscat` or `websocat` at `ws://localhost:42617/ws/chat` with `-H "Authorization: Bearer <token>"`.
2. **Register the host with a routable address.** If the agent host is reachable over Tailscale or another overlay, add that address and promote it: `clawctl host address add <host-alias> <overlay-address>` then `clawctl host address set-primary <host-alias> <overlay-address>`. `clawctl agent chat` then dials the overlay address.

The pairing token itself never leaves the agent host during minting (the handshake is loopback-only inside the configure playbook), so the LAN attack surface is bounded by the token's confidentiality after it has been written to `hosts.json` on the control machine.

### 4. Lifecycle

```bash
clawctl agent start <agent-name>     # systemctl start; gated by onboarding state
clawctl agent stop <agent-name>      # systemctl stop; preserves ~/.zeroclaw/
clawctl agent delete <agent-name>    # stop, remove unit, rm -rf ~/.zeroclaw, userdel
```

`clawctl agent start` is gated by onboarding state — until `configure` completes, `start` is blocked with a remediation message pointing at `clawctl agent configure <agent-name>`.

### 5. Memory operations

```bash
clawctl agent memory get --agent   <agent-name>                # list the 7 workspace files + daily notes
clawctl agent memory edit   <agent-name> <file>         # open in $EDITOR, sync back, restart agent if running
clawctl agent memory delete <agent-name> --file <file>  # remove a single file
clawctl agent memory delete <agent-name> --all --force  # remove every memory file (typed confirmation required)
```

`edit` takes the workspace-relative path as a positional argument (e.g. `SOUL.md`, `memory/2026-05-15.md`), not a `--name` flag. `delete` requires `--file` for a single file or `--all --force` for the wipe path.

The dispatcher reads the manifest's `workspace.memory_path` (`~/.zeroclaw/workspace`) and `features.memory: true` — the CLI surface is identical to hermes and openclaw.

---

## Security Considerations

ZeroClaw's threat model is **trusted LAN**, parity with the upstream daemon's defaults adjusted for the deployment shape clawctl targets.

- **Gateway binds `0.0.0.0`.** Any host that can reach the agent on TCP `42617` can attempt to connect. `require_pairing = true` means an unpaired connection is rejected; the bearer token is the auth boundary.
- **API keys land in `config.toml` on the agent host (mode 0600, owner `<agent-name>`).** The configure playbook renders that file with `no_log: true` so the API key never appears in Ansible output even at `-vvv`. The same `no_log: true` covers the credential-handling pairing tasks (`Request pairing code`, `Exchange pairing code for bearer token`, and the `Resolve` / `Save` set_fact pair that touches the token value). The two `Validate <…> shape` fail tasks intentionally **omit** `no_log` — their `msg` bodies contain only `agent_name`, `agent_type`, and the documented rotation instructions, never the code or token, so they must remain visible for operator recovery.
- **The bearer token traverses the network in cleartext on `ws://` connections.** The pairing handshake itself happens loopback-only inside the configure playbook, so the code/token never leave the agent host during minting — but every subsequent `clawctl agent chat` carries the token in an `Authorization` header over plain WebSocket. Fine on a trusted LAN; **not fine** over an untrusted network. `core/chat_zeroclaw.py` warns once per session when the destination is non-loopback (`_warn_if_token_in_cleartext`). For production / untrusted networks, terminate TLS at a reverse proxy (Caddy / nginx) and use a `wss://` URL; clawctl does not run that proxy itself.
- **A plain `ssh -L 42617:…` tunnel does not redirect `clawctl agent chat`.** `clawctl agent chat` rebuilds the gateway URL from the host record's primary address in `hosts.json` (see [Off-host access from the control machine](#off-host-access-from-the-control-machine) above). For ad-hoc verification, point a raw client (`wscat`, `websocat`) at the tunnelled loopback instead; for persistent overlay-network access, register the overlay address via `clawctl host address add` + `set-primary` so `clawctl agent chat` dials it directly.
- **Tokens persist to `hosts.json` on the control machine.** Treat the file like any other credential store; review its permissions (it is not chmod-0600 by default) and avoid checking it into version control. On a multi-user control machine, tighten the file mode manually.
- **Re-configure always re-mints the bearer (issue #437).** `clawctl agent configure`/`sync`/`restart` overwrite `config.gateway.auth` on every run. Local `clawctl agent chat` reloads the token transparently on 401; remote sessions must reconnect. See [Gateway token lifecycle](#gateway-token-lifecycle).
- **Server-supplied text is BIDI / control-char sanitized before rendering.** `core/chat_zeroclaw.py` routes every visible field from server frames through `sanitize_server_text` (which strips C0/C1 controls, zero-width codepoints, BIDI overrides U+202A–U+202E and U+2066–U+2069, line/paragraph separators, and the word-joiner). Rich-markup escaping is handled separately by the CLI render layer, not by this sanitizer.
- **`approval_request` frames tear down the session.** Inline tool approval is not implemented; the client closes the WebSocket and raises a remediation error pointing operators at `~/.zeroclaw/config.toml`. Pre-approve or disable tools at the agent host before invoking them. See [Use the WebSocket chat surface](#3-use-the-websocket-chat-surface) for the full frame envelope.
- **Treat `config.toml` as an audited surface.** clawctl only emits `[gateway]`, `[providers.models.<name>]`, and `[personality]`. Any block manually added (e.g. `[integrations]`, `[hardware]`) is honored by the daemon but **invisible to `clawctl`** — `clawctl agent configure` will not validate it and `clawctl` cannot detect drift between renders and manual edits.

---

## Important caveats

- **No OpenAI-compatible HTTP.** ZeroClaw's only chat surface is the WebSocket at `/ws/chat`. If you need to point an OpenAI SDK client at the agent, use [Hermes](hermes.md) instead.
- **Workspace personality is operator-owned after first configure.** Every workspace template renders with `force: no`. After the initial seed, the daemon and the operator (via `clawctl agent memory edit`) are the only writers.
- **`BOOTSTRAP.md` is runtime-generated and self-deletes.** Do not expect to see it in `clawctl agent memory get --agent`. It only exists between first daemon start and the daemon's own bootstrap cleanup.
- **`clawctl agent chat` requires the daemon to be running.** The CLI does not run the runtime in-process; it speaks to the systemd-managed daemon. If `systemctl status zeroclaw-<name>` is `inactive (dead)`, `clawctl agent chat` will fail to connect.
- **Re-installing preserves the gateway token; configure/sync/restart do not.** `install.py`'s `preserved_gateway` carry-over keeps `config.gateway.auth` across reinstalls because install itself does not re-pair. Lifecycle ops that touch the running daemon (`configure`, `sync`, `restart`) always re-pair — see [Gateway token lifecycle](#gateway-token-lifecycle).

---

## Troubleshooting

<details>
<summary><strong>Service won't start (<code>clawctl agent start</code> hangs or exits)</strong></summary>

1. SSH to the agent host and inspect the journal:

   ```bash
   sudo journalctl -u zeroclaw-<agent-name>.service -n 100 --no-pager
   ```

2. Confirm `~/.zeroclaw/config.toml` exists and parses. The configure playbook renders it mode 0600 owned by the agent user — if you've edited it by hand and broken TOML, the daemon will fail to start and emit a parse error to the journal.

   ```bash
   # Redact the api_key line so it does not get pasted into chat / logs.
   sudo -u <agent-name> grep -v '^api_key' /home/<agent-name>/.zeroclaw/config.toml
   ```

3. Verify the binary is present and executable:

   ```bash
   sudo -u <agent-name> /home/<agent-name>/bin/zeroclaw --version
   ```

   Anything other than `0.7.5` here means a stale binary; `clawctl agent delete` + reinstall.

</details>

<details>
<summary><strong><code>/health/providers</code> warning during configure</strong></summary>

The configure playbook probes `GET http://127.0.0.1:42617/health/providers` and prints a warning when it returns 401:

> _/health/providers returned 401 — gateway is reachable but provider credentials may be invalid._

The gateway is up; the daemon is rejecting requests at the provider layer. Verify the API key for the active provider (`config.toml` → `[providers.models.<name>] api_key`) and re-run `clawctl agent configure <agent-name>`. For `ollama`, ensure the `base_url` is reachable from the **agent host**, not just your control machine:

```bash
ssh <agent-host> "curl -fsS <endpoint>/api/tags"
```

</details>

<details>
<summary><strong>Pairing handshake fails (no token minted)</strong></summary>

Both pairing steps validate their responses; failure modes:

- `GET /pair/code` returned non-200, or a body missing the `code` field → daemon is up but pairing endpoint is disabled. Check the journal for upstream errors.
- `POST /pair` returned non-200, or a token shorter than 16 chars → the code expired or was already consumed.

Recovery: re-run `clawctl agent configure <agent-name>` — every configure run unconditionally mints a fresh token (see [Gateway token lifecycle](#gateway-token-lifecycle)). If `/pair/code` still fails, check the journal for upstream errors and restart the daemon (`clawctl agent restart <agent-name>`), which also re-pairs.

</details>

<details>
<summary><strong><code>clawctl agent chat</code> fails after a reinstall</strong></summary>

`install.py preserved_gateway` carries `config.gateway.auth` across reinstalls so this is rare. If it happens, run `clawctl agent configure <agent-name>` — every configure unconditionally re-pairs (see [Gateway token lifecycle](#gateway-token-lifecycle)) and brings `hosts.json` into agreement with the rebuilt daemon state.

</details>

<details>
<summary><strong><code>clawctl agent memory edit SOUL.md</code> fails with "file not found"</strong></summary>

The 7 personality files are rendered by `clawctl agent configure`, not `install`. If you ran `install` but skipped `configure`, the workspace will be empty. Run:

```bash
clawctl agent configure <agent-name>
```

The render is idempotent (force: no), so this is safe to run against a partially configured agent.

</details>

<details>
<summary><strong><code>BOOTSTRAP.md</code> appeared in <code>memory show</code> output</strong></summary>

`BOOTSTRAP.md` is filtered out of the memory listing by design — the runtime generates it transiently and deletes it once bootstrap completes. If it's still on disk, the daemon either failed to complete its first-run bootstrap or never started. Check the journal and confirm `systemctl status zeroclaw-<agent-name>` is `active (running)`.

</details>

---

## Deferred items / follow-ups

The following are explicitly out of scope for issue #112 and tracked as separate follow-ups:

- **Non-GitHub integrations** — GitLab, Atlassian (Jira + Confluence), Linear, Notion. Tracked as follow-ups; the upstream `[mcp.servers]` block is the most likely landing pad. GitHub is supported as of #422 — see the Feature Support table above.
- **Hardware** — GPIO, serial, debug-probe support.
- **Tunnel providers** — Cloudflare Tunnel, Tailscale, Ngrok, custom tunnels. Use SSH tunneling in the meantime.
- **Encrypted secrets** — ChaCha20-Poly1305 secret encryption is upstream-only for now.
- **Composio / Sovereign tool modes.**
- **Memory backends beyond the Markdown workspace** — Sqlite, Lucid, Postgres, Qdrant. clawctl's memory CLI only sees the workspace MD files in this iteration.
- **Additional providers** — Bedrock, Gemini / Vertex, Azure OpenAI, Copilot, Claude Code, Telnyx, Kilocli.
- **Installer-checksum refresh helper** — every version bump re-pins five SHA256s by hand.

---

## Next Steps

- [Hermes Support Matrix](hermes.md) — OpenAI-compatible HTTP alternative with MCP integration support.
- [OpenClaw Support Matrix](openclaw.md) — full-featured alternative with Discord / Slack / web channels.
- [Agent Onboarding](/docs/guides/agent-onboarding) — the onboarding wizard, stage by stage.
- [Host Preparation](/docs/guides/host-setup) — host prereqs and provider credential setup.
