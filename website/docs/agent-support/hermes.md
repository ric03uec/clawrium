# Hermes

Hermes is the [Nous Research self-improving AI agent](https://github.com/NousResearch/hermes-agent) — a Python daemon that exposes a local OpenAI-compatible HTTP API and is designed to maintain its own identity, memory, and skills over time.

**Status:** 🚧 In Development

**Best for:** Local-first agents that need an OpenAI-compatible HTTP endpoint, file-based memory, and self-managed identity. Particularly useful with self-hosted inference (Ollama, vLLM, llama.cpp) since the api_server platform turns any of those into a unified OpenAI-style backend.

**Pinned version:** `v2026.5.7` (manifest entry, both Ubuntu 22.04 and 24.04 x86_64). The installer SHA256 is pinned in `src/clawrium/platform/registry/hermes/manifest.yaml`; every version bump requires re-pinning.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported (use a different agent) |
| 📋 | Deferred — tracked as follow-up |

---

## Provider Support

Hermes supports cloud providers via API keys and any OpenAI-compatible local endpoint via its `custom` provider (alias `ollama`):

| Provider | Status | clawctl `provider.type` | Notes |
|----------|:------:|---------------------|-------|
| **[OpenRouter](providers/openrouter.md)** | ✅ | `openrouter` | Renders `OPENROUTER_API_KEY` + `model.base_url: https://openrouter.ai/api/v1` |
| **[Anthropic](providers/anthropic.md)** | ✅ | `anthropic` | Renders `ANTHROPIC_API_KEY`; uses hermes default `base_url` |
| **[OpenAI](providers/openai.md)** | ✅ | `openai` | Renders `OPENAI_API_KEY`; uses hermes default `base_url` |
| **[Ollama / custom OpenAI-compatible](providers/ollama.md)** | ✅ | `ollama` | Renders `model.provider: custom` + `model.base_url: <endpoint>/v1`. No API key required for local endpoints. |
| **[AWS Bedrock](providers/bedrock.md)** | ✅ | `bedrock` | Renders `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_DEFAULT_REGION`. Requires IAM credentials with `bedrock:InvokeModel` permission. |
| **Google Vertex** | 📋 | — | Deferred. |
| **ZAI / BigModel** | 📋 | — | Deferred. |
| **Azure OpenAI** | 📋 | — | Deferred. |

The provider mapping is implemented in `src/clawrium/platform/registry/hermes/templates/` and walked through in [Configure the agent](#2-configure-the-agent).

---

## Channel Support

Hermes supports three channels managed by clawctl: a loopback OpenAI-compatible HTTP API (always on), Discord (opt-in), and Slack (opt-in via Socket Mode).

| Channel | Status | Notes |
|---------|:------:|-------|
| **Local OpenAI-compatible HTTP API** (`POST /v1/chat/completions`, `GET /v1/models`, `GET /health`) | ✅ | Bound to loopback on the agent host. See [Use the local API](#3-use-the-local-openai-compatible-api). |
| **[Discord](channels/discord.md)** | ✅ | clawctl-managed via `clawctl agent configure <name> --stage channels`. Token in `secrets.json` (B3 invariant); non-sensitive config in `hosts.json`. See [Discord channel page → Hermes Configuration](channels/discord.md#hermes-configuration). |
| **[Slack](channels/slack.md)** | ✅ | Socket Mode (no public endpoint). clawctl-managed via `clawctl agent configure <name> --stage channels`. Both tokens in `secrets.json`; non-sensitive config in `hosts.json`. See [Slack channel page → Hermes Configuration](channels/slack.md#hermes-configuration). |
| **`clawctl agent chat <hermes-name>`** | ✅ | Supported via the OpenAI-compatible HTTP backend (`HermesOpenAIBackend`). Connects to `http://<host>:8642/v1` using the bearer token from `secrets.json`. |
| **Telegram / WhatsApp / Signal** | 📋 | Deferred |
| **Email / Matrix / Mattermost / Teams / Google Chat** | 📋 | Deferred |

---

## Feature Support

| Feature | Status | Notes |
|---------|:------:|-------|
| **Local API server** | ✅ | `API_SERVER_ENABLED=1` + `API_SERVER_KEY` in `~/.hermes/.env`, bound to `127.0.0.1:8642` |
| **Multi-provider** | ✅ | Up to **10 attachments per agent**: 1 `primary` slot + 9 upstream auxiliary slots (`vision`, `web_extract`, `compression`, `session_search`, `skills_hub`, `approval`, `mcp`, `title_generation`, `curator`). One provider per slot. See [Multi-provider attachments](#multi-provider-attachments). |
| **Memory (Markdown backend)** | ✅ | Two-file model: `MEMORY.md` (≤ 2200 chars), `USER.md` (≤ 1375 chars). See [Memory model on GitHub](https://github.com/ric03uec/clawrium/blob/main/docs/agent-support/memory.md). |
| **Pluggable memory backends** (Holographic / Honcho / Hindsight / Mem0 / Byterover / OpenViking) | 📋 | Deferred. clawctl's `memory` CLI sees only the default markdown backend in this iteration. |
| **Secrets management** | ✅ | `HERMES_API_SERVER_KEY` persisted in `~/.config/clawrium/secrets.json` (NOT `hosts.json`) under the canonical instance key `<host>:hermes:<agent-name>` (single-colon, 3 components). `secrets.json` is chmod 0600 on creation. Per-agent secrets are isolated by instance key. |
| **Auto-restart** | ✅ | Systemd unit `hermes-<agent_name>.service` with `Restart=on-failure`; systemd is the supervisor (no separate process). |
| **Log streaming** | ✅ | `journalctl -u hermes-<agent_name>.service` on the agent host |
| **Onboarding wizard** | ✅ | 4 stages: `providers` (required) → `identity` (auto-skipped) → `channels` (cli, discord, slack) → `validate` |
| **Identity files (`SOUL.md` / `AGENTS.md`)** | ✅ | Hermes-managed inside `~/.hermes/`. The identity onboarding stage auto-skips (by design — hermes owns these). `SOUL.md` is reachable via `clawctl agent memory read/write/info` (routed to `~/.hermes/SOUL.md`). |
| **MCP server registration** | ✅ | Supported for `atlassian` and `slack-user` / `slack-cookie` integrations — hermes launches each as a stdio subprocess and exposes their tools. See [Atlassian integration](integrations/atlassian.md) and [Slack integration](integrations/slack.md). |
| **`~/.hermes/state.db` (session/transcript history)** | 📋 | Out of scope for memory CLI |
| **OAuth / webhook secrets** | 📋 | Deferred |

---

## Getting Started

### 1. Install Hermes

```bash
clawctl agent create --type hermes --host <host> --name <agent-name>
```

What happens:

1. Preflight checks that `ripgrep` and `ffmpeg` are installed system-wide on the host. If either is missing, the install aborts with a remediation message.
2. The installer script is fetched from `https://raw.githubusercontent.com/NousResearch/hermes-agent/v2026.5.7/scripts/install.sh` and verified against the pinned SHA256.
3. A dedicated Linux user (`<agent-name>`) is created with `/usr/sbin/nologin` shell.
4. The installer runs non-interactively as that user:

   ```bash
   bash install.sh --skip-setup --branch v2026.5.7 \
     --hermes-home /home/<agent-name>/.hermes \
     --dir /home/<agent-name>/.hermes/code
   ```

5. `clawctl` creates `~/.hermes/` (mode 0700), `~/.hermes/.env` (mode 0600, empty), and `~/.hermes/memories/` (mode 0700) under the agent user.
6. A systemd unit `hermes-<agent-name>.service` is dropped, **disabled and not started**. Step 2 (configure) starts it.
7. A 64-char lowercase-hex `HERMES_API_SERVER_KEY` is generated and persisted in `~/.config/clawrium/secrets.json` under the canonical instance key `<host>:hermes:<agent-name>` (single-colon, 3 components). Re-installing reuses the existing key. The 64-char-lowercase-hex format is validated on load; a hand-edit to an invalid format produces an error at next configure/start.

The full install takes about 10-12 minutes (uv venv, pip install, npm install, Playwright). Wrapped in an Ansible `async` poll so the SSH connection is reused per-poll.

### 2. Configure the agent

```bash
clawctl agent configure <agent-name>
```

The wizard walks through:

| Stage | Behavior |
|-------|----------|
| **providers** | Required. Pick from your registered clawctl providers; clawctl validates connectivity. |
| **identity** | Auto-skipped. Hermes manages `SOUL.md` / `AGENTS.md` internally inside `~/.hermes/`. |
| **channels** | Required. Offers `cli`, `discord`, and `slack`. The api_server (CLI) is always enabled; Discord and Slack are opt-in. |
| **validate** | Required. Runs `hermes --version`, checks `~/.hermes/.env`, and probes `GET /health`. |

Configure renders TWO files on the agent host:

- `~/.hermes/.env` (mode 0600):

  ```env
  HERMES_INFERENCE_PROVIDER=<provider-name-or-custom>
  OPENROUTER_API_KEY=<...>           # only the active provider's key
  API_SERVER_ENABLED=1
  API_SERVER_HOST=127.0.0.1
  API_SERVER_PORT=8642
  API_SERVER_KEY=<64-char-hex>       # from secrets.json
  ```

- `~/.hermes/config.yaml` (mode 0600):

  ```yaml
  model:
    provider: openrouter             # or anthropic, openai, custom
    base_url: https://openrouter.ai/api/v1   # omitted for anthropic/openai defaults
    default: <model-id>
  ```

Hermes deep-merges `config.yaml` with its built-in defaults at load time, so only the `model:` block is rendered. Per-provider mapping:

| clawctl `provider.type` | Rendered `model.provider` | Rendered `model.base_url` | Rendered `.env` key |
|---------------------|---------------------------|----------------------------|---------------------|
| `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `anthropic` | `anthropic` | (omitted; hermes default) | `ANTHROPIC_API_KEY` |
| `openai` | `openai` | (omitted; hermes default) | `OPENAI_API_KEY` |
| `ollama` (or any custom OpenAI-compatible URL) | `custom` | `<provider.endpoint>/v1` (suffix `/v1` appended if missing) | (none — local endpoint) |
| `bedrock` | `bedrock` | (omitted; hermes uses boto3 credential chain) | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_DEFAULT_REGION` |

After `.env` write, the restart handler enables and starts the systemd unit. The configure playbook probes `http://127.0.0.1:8642/health` with `retries: 20, delay: 3` (≈60s max). `/health` is unauthenticated; `/v1/*` requires the bearer header.

### Multi-provider attachments

Hermes is the only agent type in clawrium that accepts more than one provider attachment. Each hermes agent supports **up to 10 attachments**:

| Slot | Role | Purpose |
|------|------|---------|
| 1 | `primary` | The main inference model. Required — the first attachment on a hermes agent **must** use `--role primary`. |
| 2 | `vision` | Image / multimodal input handling. |
| 3 | `web_extract` | Extracting structured content from fetched web pages. |
| 4 | `compression` | Summarising / compressing long context windows. |
| 5 | `session_search` | Semantic search across past sessions. |
| 6 | `skills_hub` | Skill discovery and routing. |
| 7 | `approval` | Action / tool-call approval gating. |
| 8 | `mcp` | MCP server routing. |
| 9 | `title_generation` | Generating session / transcript titles. |
| 10 | `curator` | Memory curation / pruning. |

The slot list comes from upstream `NousResearch/hermes-agent` (`hermes_cli/config.py`) and is mirrored in `src/clawrium/core/provider_attachments.py:AUXILIARY_SLOTS`. `zeroclaw`, `openclaw`, and `nemoclaw` reject `--role` and continue to enforce the single-provider invariant.

#### Attach a primary and an auxiliary

```bash
# 1. Register the providers (one-time, fleet-wide)
clawctl provider registry create my-openrouter --type openrouter --api-key <...>
clawctl provider registry create my-anthropic-haiku --type anthropic --api-key <...>

# 2. Attach them to the agent with explicit roles
clawctl agent provider attach my-openrouter      --agent <agent-name> --role primary
clawctl agent provider attach my-anthropic-haiku --agent <agent-name> --role title_generation

# 3. Materialise on the agent host
clawctl agent sync <agent-name>
```

#### Invariants

- **`--role` is required on hermes.** Omitting it returns: _"agent `<name>` is a hermes agent; --role is required"_.
- **One provider per slot.** Re-attaching a different provider to a slot that is already filled is rejected; detach the existing one first.
- **Primary is required and detached last.** `clawctl agent provider detach <primary-name>` refuses to remove the primary attachment while any auxiliary attachments remain — detach the auxiliaries first. An agent with zero attachments fails to render (`agent '<name>' has no provider attached`).
- **Same-type collisions fail loudly.** Two attachments of the same provider type (e.g. two `bedrock` slots) with mismatched credentials are rejected at render time rather than silently overwriting the `.env`.

#### Rendered output for multi-provider

With two attachments on an openrouter primary, `~/.hermes/config.yaml` renders as:

```yaml
model:
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"
  default: "<primary-model>"
auxiliary:
  title_generation:
    provider: "anthropic"
    model: "claude-haiku-4-5-20251001"
```

`~/.hermes/.env` carries the bearer key for every cloud-provider attachment (the AWS triple for bedrock). The `ollama` / `custom` provider type does not emit an auxiliary block by itself — local primary models are not paired with a remote aux pin by default; explicit auxiliary attachments are still honoured.

When no auxiliary is attached, the renderer falls back to the upstream per-primary-type default for `title_generation` (e.g. `anthropic/claude-haiku-4.5` for openrouter primaries). The fallback is hermes' own behaviour, not a clawctl invention.

`clawctl agent provider get <agent-name>` renders the `role` and `model` columns for hermes; the legacy flat output is preserved for single-provider agent types.

### 3. Use the local OpenAI-compatible API

The api_server platform binds to `127.0.0.1:8642` on the agent host. From a shell on the same host:

```bash
# Pull the bearer token from clawctl's secrets store on your control machine, OR
# read it from ~/.hermes/.env on the agent host. The two are byte-identical
# (configure hydrates .env from secrets.json).
#
# Instance key format: "<host>:<claw_type>:<claw_name>" — single-colon, 3
# components. For host alias `wolf-i`, agent `hermes-test`:
KEY=$(jq -r '.["wolf-i:hermes:hermes-test"].HERMES_API_SERVER_KEY.value' \
  ~/.config/clawrium/secrets.json)

# Note: `127.0.0.1:8642` is the AGENT HOST's loopback. Run the curl below on
# the agent host. For control-machine access, see "Off-host access" below.
curl -fsS http://127.0.0.1:8642/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-agent",
    "messages": [{"role": "user", "content": "Say only the word OK."}],
    "max_tokens": 16
  }'
```

Substitute the canonical instance key (`<host>:hermes:<agent-name>` — single colons) for your fleet. The `model` field is always `hermes-agent` — hermes routes to whatever upstream model is configured in `config.yaml`.

#### Off-host access (loopback constraint)

The api_server only binds to `127.0.0.1` by design. To reach it from your control machine, open an SSH tunnel:

```bash
ssh -L 8642:127.0.0.1:8642 <user>@<agent-host>
# In another terminal on the control machine:
curl -fsS http://127.0.0.1:8642/v1/models \
  -H "Authorization: Bearer $KEY"
```

Exposing hermes on a non-loopback interface is not supported in this iteration. Doing so without a properly hardened reverse proxy would let any LAN client invoke the model with the bearer token in plaintext.

### 4. Lifecycle

```bash
clawctl agent start <agent-name>     # systemctl start; waits for ActiveState ∈ {active, activating}
clawctl agent stop <agent-name>      # systemctl stop + disable; preserves ~/.hermes/
clawctl agent delete <agent-name>    # stop, remove unit, rm ~/.hermes/, userdel
```

`clawctl agent start` checks systemd's `ActiveState` after a 3-second settle window and fails loudly if the unit is not `active` or `activating`. The HTTP `/health` probe runs during the `validate` onboarding stage, NOT during `clawctl agent start`.

`clawctl agent start` is gated by onboarding state — until `configure` completes and onboarding reaches READY, `start` is blocked with: _"Cannot start `<host:hermes:name>`: onboarding incomplete (state=`<current-state>`). Run 'clawctl agent configure `<agent-name>`' first."_ Use `--force` to override the gate (not recommended; bypasses provider/validate checks).

---

## Important caveats

- **Discord and Slack are the clawctl-managed messaging gateways today.** Telegram, WhatsApp, Signal, email, Matrix, Mattermost, Teams, Google Chat are tracked as separate follow-ups. See [Discord channel page → Hermes Configuration](channels/discord.md#hermes-configuration) and [Slack channel page → Hermes Configuration](channels/slack.md#hermes-configuration).
- **Identity is hermes-managed by design.** Hermes owns `SOUL.md` and `AGENTS.md` inside `~/.hermes/`; the onboarding `identity` stage auto-skips. `SOUL.md` is editable via `clawctl agent memory write <name> SOUL.md`, which routes to `~/.hermes/SOUL.md` (other memories live under `~/.hermes/memories/`).
- **Bearer token lives in `secrets.json`, not `hosts.json`.** As of PR #318, the canonical store for `HERMES_API_SERVER_KEY` is `~/.config/clawrium/secrets.json` keyed by `<host>:hermes:<agent-name>` (single-colon, 3 components). Provider keys use a different schema (`provider:<provider-name>`) in the same file.
- **Memory has hard size limits.** `MEMORY.md` ≤ 2200 chars, `USER.md` ≤ 1375 chars. Other filenames in `~/.hermes/memories/` are rejected by `clawctl agent memory edit`. See [Memory model on GitHub](https://github.com/ric03uec/clawrium/blob/main/docs/agent-support/memory.md).
- **Concurrent writes are visible-atomic.** Hermes' `memory_write.yaml` uses a stage-then-rename pattern (`rename(2)` within the same filesystem) so the running hermes daemon never observes a partial file. The pattern is visible-atomic, not crash-durable (no explicit `fsync`).

---

## Memory model

Hermes ships a two-file Markdown memory backend at `~/.hermes/memories/`:

| File | Limit | Purpose |
|------|------:|---------|
| `MEMORY.md` | 2200 chars | Agent notes / scratchpad |
| `USER.md` | 1375 chars | User profile |

Both are managed by `clawctl agent memory get --agent|edit|delete <hermes-name>`. The dispatcher is driven by the agent's manifest (`workspace.memory_path` + `features.memory: true`), so the CLI surface is identical to openclaw. (Note: `read` and `write` are not separate CLI subcommands in this iteration — use `edit`.)

Full details: [Memory model on GitHub](https://github.com/ric03uec/clawrium/blob/main/docs/agent-support/memory.md).

---

## Troubleshooting

<details>
<summary><strong>Service won't start (`clawctl agent start` hangs or exits)</strong></summary>

1. SSH to the agent host and inspect the journal:

   ```bash
   sudo journalctl -u hermes-<agent-name>.service -n 100 --no-pager
   ```

2. Check that `~/.hermes/.env` exists and has `API_SERVER_ENABLED=1` and `API_SERVER_KEY=...`:

   ```bash
   sudo cat /home/<agent-name>/.hermes/.env
   ```

3. Confirm the unit's `ExecStart` references `hermes gateway run` (the foreground supervisor command — both `install.yaml` and `start.yaml` render this). If you see `gateway start` in the unit file, you're on a pre-PR #318 build; `clawctl agent delete` + reinstall to pick up the corrected unit.

</details>

<details>
<summary><strong>`/health` returns non-200 or connection refused</strong></summary>

1. Confirm the service is active:

   ```bash
   sudo systemctl status hermes-<agent-name>.service
   ```

2. From the agent host (not your control machine — loopback only):

   ```bash
   curl -v http://127.0.0.1:8642/health
   ```

3. If the service is active but the probe fails, the most likely cause is the api_server platform failing to register. That happens when `API_SERVER_KEY` is missing from `.env` (the configure stage should always write it). Re-run `clawctl agent configure <name> --stage providers`.

4. From your control machine, you cannot reach `/health` directly — use SSH port-forwarding (see [Off-host access](#off-host-access-loopback-constraint)).

</details>

<details>
<summary><strong>Provider connectivity failed during configure</strong></summary>

1. Verify the provider is registered and has a key:

   ```bash
   clawctl provider registry get
   ```

2. Re-run the onboarding `providers` stage; clawctl runs `provider_test` connectivity validation as part of that stage:

   ```bash
   clawctl agent configure <agent-name> --stage providers
   ```

3. For `ollama` / custom endpoints, ensure the **agent host** (not just your control machine) can reach the endpoint URL:

   ```bash
   ssh <agent-host> "curl -fsS <endpoint>/v1/models"
   ```

4. Inspect the agent's `~/.hermes/.env` and `~/.hermes/config.yaml` on the agent host to verify the rendered provider settings:

   ```bash
   ssh <agent-host> "sudo -u <agent-name> cat ~<agent-name>/.hermes/config.yaml"
   ```

</details>

<details>
<summary><strong>`memory edit USER.md` rejects on save with character limit</strong></summary>

`USER.md` is hard-capped at 1375 chars, `MEMORY.md` at 2200. The limit is enforced client-side in `clawctl` before any Ansible dispatch, so you get an immediate error after `$EDITOR` exits. Trim the content and retry. Other filenames are rejected with `"hermes memory accepts only MEMORY.md and USER.md"`.

</details>

<details>
<summary><strong>`userdel` fails on `clawctl agent delete`</strong></summary>

Hermes runs `loginctl enable-linger` on first start, which keeps a per-user systemd manager + dbus running even after the system unit stops. `remove.yaml` runs `loginctl disable-linger` + `pkill -KILL -u <user>` before `userdel`, but if you hit a stuck state, do it manually:

```bash
sudo loginctl disable-linger <agent-name>
sudo pkill -KILL -u <agent-name>
sudo userdel -r <agent-name>
```

Then re-run `clawctl agent delete <name> --force`.

</details>

---

## Slack integration

Hermes agents can attach the [Slack integration](integrations/slack.md) (`--type slack-user` recommended, `--type slack-cookie` discouraged fallback) to gain outbound Slack tool calls via the [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) stdio subprocess. See the [Slack integration doc](integrations/slack.md) for the full token acquisition, security posture, and end-to-end walkthrough.

Hermes-specific details:

- **Config surface:** the Slack MCP subprocess is rendered into the `mcp_servers:` block of `~/.hermes/config.yaml` (mode 0600), adjacent to the atlassian branch. Renderer: [`src/clawrium/core/render.py:render_hermes`](https://github.com/ric03uec/clawrium/blob/main/src/clawrium/core/render.py). The subprocess env block carries the `SLACK_MCP_XOX*` tokens verbatim; no separate `.env` write path.
- **Binary install location:** `~/<agent-name>/.local/bin/slack-mcp-server` — same path pattern as the atlassian `uvx` binary, but Slack ships as a single Go binary so there is no Python runtime dependency.
- **First MCP subprocess on Darwin.** Slack is the first MCP subprocess supported on Darwin hermes (atlassian macOS was deferred). `clawctl agent sync` installs the darwin arm64 / x86_64 tarball via the dedicated `install_slack_mcp_macos.yaml` runbook. The `workspace_excluded` invariants and `no_log: true` render behavior apply identically on Linux and macOS.
- **Composite blast-radius warning applies.** Attaching both the Slack **channel** (inbound, see [Slack channel](channels/slack.md)) and the Slack **integration** (outbound) to the same hermes agent enables a prompt-injection tool-call exfiltration path. See [integrations/slack.md → Composite blast-radius warning](integrations/slack.md#composite-blast-radius-warning) — for high-sensitivity workspaces, split inbound and outbound into two separate hermes agents.

Quick attach + sync:

```bash
printf 'SLACK_MCP_XOXP_TOKEN=xoxp-...' | \
  clawctl integration registry create slack --type slack-user --credential-stdin
clawctl agent integration attach <hermes-name> --integration slack
```

Then `clawctl agent chat <hermes-name>` — the model gains `channels_list`, `conversations_history`, `conversations_add_message`, `conversations_search_messages`, and `conversations_replies` under the `slack_*` tool prefix.

---

## Deferred items / follow-ups

The following are explicitly out of scope for issue #68 and tracked as separate follow-ups (see `.itx/68/00_PLAN.md` → "Out of scope"):

- Messaging gateway pairing: Telegram, WhatsApp, Signal, email, Teams, Google Chat, Matrix, Mattermost, QQBot, Feishu, DingTalk. (Discord and Slack shipped — see [Discord channel page → Hermes Configuration](channels/discord.md#hermes-configuration) and [Slack channel page → Hermes Configuration](channels/slack.md#hermes-configuration).)
- Pluggable memory backends: Holographic, Honcho, Hindsight, Mem0, Byterover, OpenViking. clawctl's `memory` CLI only sees the default markdown backend.
- `~/.hermes/state.db` (session / transcript history) inspection via clawctl.
- OAuth file (`HERMES_OAUTH_FILE`) and webhook secrets.
- Installer-checksum refresh helper (manifest must be re-pinned every version bump — currently manual).

---

## Next Steps

- [Memory model on GitHub](https://github.com/ric03uec/clawrium/blob/main/docs/agent-support/memory.md) — manifest-driven memory CLI across claw types
- [OpenClaw Support Matrix](openclaw.md) — full-featured alternative with multi-channel support
- [Agent Onboarding](/docs/guides/agent-onboarding) — detailed onboarding wizard guide
- [Host Preparation](/docs/guides/host-setup) — installing provider credentials and host prereqs
