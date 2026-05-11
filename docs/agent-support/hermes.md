# Hermes Support Matrix

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
| ❌ | Not supported (use a different claw) |
| 📋 | Deferred — tracked as follow-up |

---

## Provider Support

Hermes supports cloud providers via API keys and any OpenAI-compatible local endpoint via its `custom` provider (alias `ollama`):

| Provider | Status | clm `provider.type` | Notes |
|----------|:------:|---------------------|-------|
| **[OpenRouter](providers/openrouter.md)** | ✅ | `openrouter` | Renders `OPENROUTER_API_KEY` + `model.base_url: https://openrouter.ai/api/v1` |
| **[Anthropic](providers/anthropic.md)** | ✅ | `anthropic` | Renders `ANTHROPIC_API_KEY`; uses hermes default `base_url` |
| **[OpenAI](providers/openai.md)** | ✅ | `openai` | Renders `OPENAI_API_KEY`; uses hermes default `base_url` |
| **[Ollama / custom OpenAI-compatible](providers/ollama.md)** | ✅ | `ollama` | Renders `model.provider: custom` + `model.base_url: <endpoint>/v1`. No API key required for local endpoints. |
| **AWS Bedrock** | 📋 | — | Deferred. Hermes upstream supports it; clm wiring not in this iteration. |
| **Google Vertex** | 📋 | — | Deferred. |
| **ZAI / BigModel** | 📋 | — | Deferred. |
| **Azure OpenAI** | 📋 | — | Deferred. |

The provider mapping is implemented in `src/clawrium/platform/registry/hermes/templates/` and walked through in [Configure the agent](#2-configure-the-agent).

---

## Channel Support

Hermes supports two channels managed by clm: a loopback OpenAI-compatible HTTP API (always on) and Discord (opt-in via the channels onboarding stage).

| Channel | Status | Notes |
|---------|:------:|-------|
| **Local OpenAI-compatible HTTP API** (`POST /v1/chat/completions`, `GET /v1/models`, `GET /health`) | ✅ | Bound to loopback on the agent host. See [Use the local API](#3-use-the-local-openai-compatible-api). |
| **Discord** | ✅ | clm-managed via `clm agent configure <name> --stage channels`. Token in `secrets.json` (B3 invariant); non-sensitive config in `hosts.json`. See [Discord walkthrough](#discord-walkthrough). |
| **clm `chat <hermes-name>`** | 🚧 | Not supported yet (only openclaw). Tracked as [#322](https://github.com/ric03uec/clawrium/issues/322). |
| **Slack** | 📋 | Deferred |
| **Telegram / WhatsApp / Signal** | 📋 | Deferred |
| **Email / Matrix / Mattermost / Teams / Google Chat** | 📋 | Deferred |

---

## Feature Support

| Feature | Status | Notes |
|---------|:------:|-------|
| **Local API server** | ✅ | `API_SERVER_ENABLED=1` + `API_SERVER_KEY` in `~/.hermes/.env`, bound to `127.0.0.1:8642` |
| **Multi-provider** | ✅ | openrouter, anthropic, openai, ollama / custom |
| **Memory (Markdown backend)** | ✅ | Two-file model: `MEMORY.md` (≤ 2200 chars), `USER.md` (≤ 1375 chars). See [memory.md](memory.md). |
| **Pluggable memory backends** (Holographic / Honcho / Hindsight / Mem0 / Byterover / OpenViking) | 📋 | Deferred. clm's `memory` CLI sees only the default markdown backend in this iteration. |
| **Secrets management** | ✅ | `HERMES_API_SERVER_KEY` persisted in `~/.config/clawrium/secrets.json` (NOT `hosts.json`) under the canonical instance key `<host>:hermes:<agent-name>` (single-colon, 3 components). `secrets.json` is chmod 0600 on creation. Per-agent secrets are isolated by instance key. |
| **Auto-restart** | ✅ | Systemd unit `hermes-<agent_name>.service` with `Restart=on-failure`; systemd is the supervisor (no separate process). |
| **Log streaming** | ✅ | `journalctl -u hermes-<agent_name>.service` on the agent host |
| **Onboarding wizard** | ✅ | 4 stages: `providers` (required) → `identity` (auto-skipped) → `channels` (cli only) → `validate` |
| **Identity files (`SOUL.md` / `AGENTS.md`)** | 🚧 | Hermes manages these internally inside `~/.hermes/`. clm does not push identity files in this iteration — the identity onboarding stage auto-skips. |
| **MCP server registration** | 📋 | Deferred |
| **`~/.hermes/state.db` (session/transcript history)** | 📋 | Out of scope for memory CLI |
| **OAuth / webhook secrets** | 📋 | Deferred |

---

## Getting Started

### 1. Install Hermes

```bash
clm agent install --type hermes --host <host> --name <agent-name>
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

5. `clm` creates `~/.hermes/` (mode 0700), `~/.hermes/.env` (mode 0600, empty), and `~/.hermes/memories/` (mode 0700) under the agent user.
6. A systemd unit `hermes-<agent-name>.service` is dropped, **disabled and not started**. Step 2 (configure) starts it.
7. A 64-char lowercase-hex `HERMES_API_SERVER_KEY` is generated and persisted in `~/.config/clawrium/secrets.json` under the canonical instance key `<host>:hermes:<agent-name>` (single-colon, 3 components). Re-installing reuses the existing key. The 64-char-lowercase-hex format is validated on load; a hand-edit to an invalid format produces an error at next configure/start.

The full install takes about 10-12 minutes (uv venv, pip install, npm install, Playwright). Wrapped in an Ansible `async` poll so the SSH connection is reused per-poll.

### 2. Configure the agent

```bash
clm agent configure <agent-name>
```

The wizard walks through:

| Stage | Behavior |
|-------|----------|
| **providers** | Required. Pick from your registered clm providers; clm validates connectivity. |
| **identity** | Auto-skipped. Hermes manages `SOUL.md` / `AGENTS.md` internally inside `~/.hermes/`. |
| **channels** | Required. Only `cli` is offered (the api_server platform is the CLI-equivalent endpoint). |
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

| clm `provider.type` | Rendered `model.provider` | Rendered `model.base_url` | Rendered `.env` key |
|---------------------|---------------------------|----------------------------|---------------------|
| `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `anthropic` | `anthropic` | (omitted; hermes default) | `ANTHROPIC_API_KEY` |
| `openai` | `openai` | (omitted; hermes default) | `OPENAI_API_KEY` |
| `ollama` (or any custom OpenAI-compatible URL) | `custom` | `<provider.endpoint>/v1` (suffix `/v1` appended if missing) | (none — local endpoint) |

After `.env` write, the restart handler enables and starts the systemd unit. The configure playbook probes `http://127.0.0.1:8642/health` with `retries: 20, delay: 3` (≈60s max). `/health` is unauthenticated; `/v1/*` requires the bearer header.

### 3. Use the local OpenAI-compatible API

The api_server platform binds to `127.0.0.1:8642` on the agent host. From a shell on the same host:

```bash
# Pull the bearer token from clm's secrets store on your control machine, OR
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
clm agent start <agent-name>     # systemctl start; waits for ActiveState ∈ {active, activating}
clm agent stop <agent-name>      # systemctl stop + disable; preserves ~/.hermes/
clm agent remove <agent-name>    # stop, remove unit, rm ~/.hermes/, userdel
```

`clm agent start` checks systemd's `ActiveState` after a 3-second settle window and fails loudly if the unit is not `active` or `activating`. The HTTP `/health` probe runs during the `validate` onboarding stage, NOT during `clm agent start`.

`clm agent start` is gated by onboarding state — until `configure` completes and onboarding reaches READY, `start` is blocked with: _"Cannot start `<host:hermes:name>`: onboarding incomplete (state=`<current-state>`). Run 'clm agent configure `<agent-name>`' first."_ Use `--force` to override the gate (not recommended; bypasses provider/validate checks).

---

## Important caveats

- **No `clm chat <hermes-name>`** in this iteration. `clm chat` only supports openclaw. Tracked as [#322](https://github.com/ric03uec/clawrium/issues/322). Use `curl` against the local API in the meantime.
- **Discord is the only clm-managed messaging gateway today.** Slack, Telegram, WhatsApp, Signal, email, Matrix, Mattermost, Teams, Google Chat are tracked as separate follow-ups. Discord is fully wired — see [Discord walkthrough](#discord-walkthrough).
- **Identity is hermes-managed.** clm does not push `SOUL.md` / `AGENTS.md` into `~/.hermes/`. The identity onboarding stage auto-skips. If you want custom identity, edit those files directly on the agent host via SSH.
- **Bearer token lives in `secrets.json`, not `hosts.json`.** As of PR #318, the canonical store for `HERMES_API_SERVER_KEY` is `~/.config/clawrium/secrets.json` keyed by `<host>:hermes:<agent-name>` (single-colon, 3 components). Provider keys use a different schema (`provider:<provider-name>`) in the same file.
- **Memory has hard size limits.** `MEMORY.md` ≤ 2200 chars, `USER.md` ≤ 1375 chars. Other filenames in `~/.hermes/memories/` are rejected by `clm agent memory edit`. See [memory.md](memory.md).
- **Concurrent writes are visible-atomic.** Hermes' `memory_write.yaml` uses a stage-then-rename pattern (`rename(2)` within the same filesystem) so the running hermes daemon never observes a partial file. The pattern is visible-atomic, not crash-durable (no explicit `fsync`).

---

## Discord walkthrough

Discord is opt-in. You'll need a Discord bot already installed in your server (token from the [Discord developer portal](https://discord.com/developers/applications)) and at least one allowed Discord user ID.

### Interactive setup

```bash
clm agent configure <hermes-name> --stage channels
```

The wizard offers `cli` and `discord`. Pick `discord` and the CLI prompts for:

| Prompt | Stored where | Required | Notes |
|--------|--------------|:--------:|-------|
| Discord bot token | `secrets.json` as `DISCORD_BOT_TOKEN` | yes | Masked input. Bearer token for the Discord gateway. |
| Allowed Discord user IDs | `hosts.json` `channels.discord.allowed_users` | yes (or `all`) | Comma-separated IDs (17–19 digits). Use the literal string `all` to allow any user — you'll get a security warning + confirm prompt. |
| Discord home channel ID | `hosts.json` `channels.discord.home_channel` | optional | Without this, hermes will nudge users to run `/sethome` on every cold start. |
| Discord home channel name | `hosts.json` `channels.discord.home_channel_name` | optional | Defaults to `Home`. Display name only. |
| Allowed channel IDs | `hosts.json` `channels.discord.allowed_channels` | optional | Restrict the bot to specific channels (comma-separated). Empty = any channel the bot is invited to. |
| Require `@mention` to respond? | `hosts.json` `channels.discord.require_mention` | optional | Defaults to true. DMs always work regardless. |

`clm` then runs the configure playbook which re-renders `~/.hermes/.env` with the `DISCORD_*` block and restarts `hermes-<name>.service`. Verification tasks confirm the token + an allowlist landed in the env file before the playbook reports success.

### Resulting on-disk shape

`hosts.json` (non-sensitive only):

```json
"config": {
  "api_server": {"enabled": true, "host": "127.0.0.1", "port": 8642},
  "provider": {...},
  "channels": {
    "discord": {
      "enabled": true,
      "allowed_users": ["740723459344302120"],
      "allow_all_users": false,
      "home_channel": "1503238729962356777",
      "home_channel_name": "Home",
      "require_mention": true
    }
  }
}
```

`secrets.json`:

```json
"192.168.1.36:hermes:<name>": {
  "HERMES_API_SERVER_KEY": {...},
  "DISCORD_BOT_TOKEN": {"value": "<token>", "description": "Discord bot token", ...}
}
```

The bot token **never** lands in `hosts.json` — the configure flow strips it from `config.channels.discord` before persisting (B3 invariant, mirrored from the `api_server.key` strip). Re-running `clm agent configure --stage channels` with the same token reuses it byte-identical (idempotency contract).

### Removal

`clm agent remove <name> --force` purges the entire instance entry from `secrets.json`, including `DISCORD_BOT_TOKEN`. There is no separate "rotate Discord token" command — re-run the channels stage with a new token to overwrite.

### Troubleshooting

<details>
<summary><strong>Bot is online but doesn't respond in the test channel</strong></summary>

1. Confirm your Discord user ID is in `hosts.json` `channels.discord.allowed_users` (or `allow_all_users: true`). Hermes silently drops messages from non-allowlisted users.
2. If `require_mention` is true (default), the bot only responds to messages that `@mention` it directly in a guild channel. DMs always work.
3. Confirm the bot has the right Discord permissions in the guild: Send Messages, Read Message History, Use Slash Commands.
4. If `allowed_channels` is non-empty, the bot only responds in those channel IDs.

</details>

<details>
<summary><strong>Service is active but Discord init silently fails</strong></summary>

Hermes' default log level is WARNING, and Discord-init success/failure logs at INFO. The `/health` endpoint returns 200 even if the Discord platform failed to register. To check:

```bash
ssh <agent-host> "sudo journalctl -u hermes-<name>.service -n 200 --no-pager | grep -iE 'discord|platform'"
```

If you see nothing, temporarily bump `LOG_LEVEL=INFO` in `~/.hermes/.env` (manual edit — note the override will be wiped on next `clm agent configure`) and restart the service. The Discord init line will read `INFO  hermes.platforms.discord: connected as <bot-name>#<discriminator>`.

</details>

<details>
<summary><strong>`DISCORD_ALLOW_ALL_USERS=true` is set and I want to lock it down</strong></summary>

Re-run `clm agent configure <name> --stage channels`, pick `discord` again, and pass specific user IDs (not `all`) at the allowlist prompt. The new value overwrites the previous `channels.discord` block in `hosts.json`, and the next `~/.hermes/.env` render drops `DISCORD_ALLOW_ALL_USERS` entirely.

</details>

### Non-interactive flags

Planned for a follow-up — interactive is the supported path in this release. For automation today, drive `clm agent configure --stage channels` via expect/pexpect, or set the values directly in `hosts.json` + `secrets.json` and re-run the stage to trigger a re-render.

---

## Memory model

Hermes ships a two-file Markdown memory backend at `~/.hermes/memories/`:

| File | Limit | Purpose |
|------|------:|---------|
| `MEMORY.md` | 2200 chars | Agent notes / scratchpad |
| `USER.md` | 1375 chars | User profile |

Both are managed by `clm agent memory show|edit|delete <hermes-name>`. The dispatcher is driven by the agent's manifest (`workspace.memory_path` + `features.memory: true`), so the CLI surface is identical to openclaw. (Note: `read` and `write` are not separate CLI subcommands in this iteration — use `edit`.)

Full details: [memory.md](memory.md).

---

## Troubleshooting

<details>
<summary><strong>Service won't start (`clm agent start` hangs or exits)</strong></summary>

1. SSH to the agent host and inspect the journal:

   ```bash
   sudo journalctl -u hermes-<agent-name>.service -n 100 --no-pager
   ```

2. Check that `~/.hermes/.env` exists and has `API_SERVER_ENABLED=1` and `API_SERVER_KEY=...`:

   ```bash
   sudo cat /home/<agent-name>/.hermes/.env
   ```

3. Confirm the unit's `ExecStart` references `hermes gateway run` (the foreground supervisor command — both `install.yaml` and `start.yaml` render this). If you see `gateway start` in the unit file, you're on a pre-PR #318 build; `clm agent remove` + reinstall to pick up the corrected unit.

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

3. If the service is active but the probe fails, the most likely cause is the api_server platform failing to register. That happens when `API_SERVER_KEY` is missing from `.env` (the configure stage should always write it). Re-run `clm agent configure <name> --stage providers`.

4. From your control machine, you cannot reach `/health` directly — use SSH port-forwarding (see [Off-host access](#off-host-access-loopback-constraint)).

</details>

<details>
<summary><strong>Provider connectivity failed during configure</strong></summary>

1. Verify the provider is registered and has a key:

   ```bash
   clm provider list
   ```

2. Re-run the onboarding `providers` stage; clm runs `provider_test` connectivity validation as part of that stage:

   ```bash
   clm agent configure <agent-name> --stage providers
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

`USER.md` is hard-capped at 1375 chars, `MEMORY.md` at 2200. The limit is enforced client-side in `clm` before any Ansible dispatch, so you get an immediate error after `$EDITOR` exits. Trim the content and retry. Other filenames are rejected with `"hermes memory accepts only MEMORY.md and USER.md"`.

</details>

<details>
<summary><strong>`userdel` fails on `clm agent remove`</strong></summary>

Hermes runs `loginctl enable-linger` on first start, which keeps a per-user systemd manager + dbus running even after the system unit stops. `remove.yaml` runs `loginctl disable-linger` + `pkill -KILL -u <user>` before `userdel`, but if you hit a stuck state, do it manually:

```bash
sudo loginctl disable-linger <agent-name>
sudo pkill -KILL -u <agent-name>
sudo userdel -r <agent-name>
```

Then re-run `clm agent remove <name> --force`.

</details>

---

## Deferred items / follow-ups

The following are explicitly out of scope for issue #68 and tracked as separate follow-ups (see `.itx/68/00_PLAN.md` → "Out of scope"):

- Messaging gateway pairing: Slack, Telegram, WhatsApp, Signal, email, Teams, Google Chat, Matrix, Mattermost, QQBot, Feishu, DingTalk. (Discord shipped — see [Discord walkthrough](#discord-walkthrough).)
- Pluggable memory backends: Holographic, Honcho, Hindsight, Mem0, Byterover, OpenViking. clm's `memory` CLI only sees the default markdown backend.
- MCP server registration.
- `~/.hermes/state.db` (session / transcript history) inspection via clm.
- OAuth file (`HERMES_OAUTH_FILE`) and webhook secrets.
- Installer-checksum refresh helper (manifest must be re-pinned every version bump — currently manual).
- `clm chat <hermes-name>` ([#322](https://github.com/ric03uec/clawrium/issues/322)).

---

## Next Steps

- [Memory model](memory.md) — manifest-driven memory CLI across claw types
- [OpenClaw Support Matrix](openclaw.md) — full-featured alternative with multi-channel support
- [Agent Onboarding](../agent-onboarding.md) — detailed onboarding wizard guide
- [Host Preparation](../host-preparation.md) — installing provider credentials and host prereqs
