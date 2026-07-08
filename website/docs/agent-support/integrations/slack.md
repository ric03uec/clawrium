# Slack (MCP tool integration)

**Status:** ✅ Supported (Hermes, OpenClaw, ZeroClaw — all Linux + macOS on the arches upstream ships; armv7l not shipped by upstream at v1.3.0)

Slack integration connects agents to a Slack workspace as an **outbound tool surface** — the agent can list channels, read message history, search, and post messages via MCP tool calls. Implementation is a stdio-launched subprocess of [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server), the community-leading Slack MCP server. The single-binary Go release is SHA256-pinned per (os, arch) and installed to `/home/<agent-name>/.local/bin/slack-mcp-server` on Linux hosts (or `/Users/<agent-name>/.local/bin/slack-mcp-server` on macOS) — the agent-user's own `~/.local/bin/`, not the SSH user's.

This mirrors the shape of the [Atlassian integration](atlassian.md): one integration record, credentials in `~/.config/clawrium/secrets.json`, attached to any supported agent via `clawctl agent integration attach`. There is no separate `clawctl mcp` command surface — Slack is a first-class integration type.

> **Slack integration ≠ Slack channel.** clawctl also supports a Slack **channel** (`clawctl channel registry create --type slack`) which is the **inbound** surface — users message the agent through Slack. The Slack **integration** described here is the **outbound tool** surface — the agent talks back out to Slack. Both can attach to the same agent, but see [Composite blast-radius warning](#composite-blast-radius-warning) below for the security implication of doing so.

---

## What you can do

The [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) tool surface exposes (as of v1.3.0):

| Tool | Purpose |
|------|---------|
| `channels_list` | List channels (public, private, DMs, group DMs) accessible to the token |
| `conversations_history` | Fetch recent messages in a channel or DM |
| `conversations_replies` | Fetch replies to a thread |
| `conversations_search_messages` | Search across message history (workspace-scoped) |
| `conversations_add_message` | Post a message to a channel or DM |

Refer to the [upstream README](https://github.com/korotovsky/slack-mcp-server#tools) for the authoritative tool list and argument shapes — the set evolves upstream.

---

## Auth model — two paths

| Type | Token(s) | Recommended? | Notes |
|------|----------|:------------:|-------|
| `slack-user` | `SLACK_MCP_XOXP_TOKEN` (xoxp-…) | ✅ **Default and recommended** | User OAuth token. Requires creating a Slack App and installing it to the workspace. Long-lived until rotated in the Slack admin console. |
| `slack-cookie` | `SLACK_MCP_XOXC_TOKEN` (xoxc-…) + `SLACK_MCP_XOXD_TOKEN` (xoxd-…) | ⚠️ **Discouraged fallback** | Browser session tokens extracted from a signed-in Slack tab. See [Cookie mode security warning](#cookie-mode-security-warning) — TOS-adjacent and fragile. |

The two types share the same MCP server binary and the same rendered subprocess shape; only the env-var set differs. clawctl warns on `add` and on every `sync` when a `slack-cookie` integration is attached.

---

## Setup — the recommended path (`slack-user`)

### 1. Create a Slack App and grab an xoxp token

1. Go to **[https://api.slack.com/apps](https://api.slack.com/apps)** and click **Create New App** → **From scratch**.
2. Give it a name (e.g. `clawrium-<agentname>`), pick the workspace, and hit **Create**.
3. In the sidebar, go to **OAuth & Permissions**.
4. Under **User Token Scopes** (NOT Bot Token Scopes — the MCP server uses user auth), add the scopes you need. A common minimum:

   | Scope | Purpose |
   |-------|---------|
   | `channels:history` | Read messages in public channels |
   | `channels:read` | List public channels |
   | `groups:history` | Read messages in private channels the user is in |
   | `groups:read` | List private channels the user is in |
   | `im:history` | Read direct messages |
   | `im:read` | List direct messages |
   | `mpim:history` | Read multi-party direct messages |
   | `mpim:read` | List multi-party direct messages |
   | `search:read` | `conversations_search_messages` |
   | `chat:write` | `conversations_add_message` (posts as the installing user) |

5. Click **Install to Workspace** at the top of the OAuth & Permissions page and approve. Slack returns a **User OAuth Token** starting with `xoxp-`. **Copy it now** — Slack will not show it again in this exact form (you can rotate it later from the same page).

### 2. Register the integration in clawctl

Use `--credential-stdin` to avoid leaking the token into your shell history or a `ps auxww` snapshot:

```bash
printf 'SLACK_MCP_XOXP_TOKEN=xoxp-...' | \
  clawctl integration registry create slack --type slack-user --credential-stdin
```

> **Important:** The integration name **must** be `slack` — the CLI rejects any other name for `slack-user` / `slack-cookie` types. The rendered MCP server key is always the literal `slack`, matching the naming convention of other built-in toolsets (`web`, `browser`, `terminal`, `file`, `atlassian`). (#846)

The credential lands in `~/.config/clawrium/secrets.json` (chmod 0600). It never round-trips through `hosts.json`, terminal output, or logs after the initial write. Passing `--credential SLACK_MCP_XOXP_TOKEN=<value>` still works but leaks the token into `ps auxww` and shell history — prefer stdin.

### 3. Attach to an agent

```bash
clawctl agent integration attach my-hermes --integration slack
```

The attach step gates by agent-type: only agent types whose renderer supports the Slack integration accept it. Today that means all three GA agent types (`hermes`, `openclaw`, `zeroclaw`) accept `slack-user` and `slack-cookie`. Unsupported (agent, integration) pairs exit 2 at attach time with a hint pointing at `clawctl integration registry get`.

### 4. Sync

```bash
clawctl agent sync my-hermes
```

`sync` renders the on-host config (`~/.hermes/config.yaml` on hermes, `~/.openclaw/openclaw.json` on openclaw, `~/.zeroclaw/config.toml` on zeroclaw), installs the `slack-mcp-server` binary at the pinned version + SHA256 to `/home/<agent-name>/.local/bin/slack-mcp-server` (Linux) / `/Users/<agent-name>/.local/bin/slack-mcp-server` (macOS), and restarts the daemon. On zeroclaw the sync also rotates the gateway bearer as part of the standard sync path — remote `clawctl agent chat` sessions will need to reconnect.

### 5. Verify

```bash
clawctl agent chat my-hermes
> list all the slack channels I have access to
> summarise the last 20 messages in #eng-general
```

If the tool is available, hermes / openclaw / zeroclaw will route the request through the Slack MCP subprocess. See [Troubleshooting](#troubleshooting) if the model reports it does not have a Slack tool.

---

## Setup — cookie fallback (`slack-cookie`)

> ⚠️ **Read [Cookie mode security warning](#cookie-mode-security-warning) first.** This path is TOS-adjacent, fragile, and disproportionately likely to trigger Slack's abuse-detection heuristics. Use it only when a proper Slack App install is not possible and you understand the risk.

### 1. Extract the `xoxc` and `xoxd` tokens from your browser

1. Sign in to Slack in a browser tab.
2. Open DevTools → **Application** → **Cookies** → your Slack workspace domain.
3. Copy the value of the `d` cookie — this is the **`xoxd-…`** token.
4. Extract the `xoxc-…` workspace token from the same Slack browser tab. The exact extraction path drifts as Slack changes its client, so **defer to the upstream README for the current step-by-step** — [`korotovsky/slack-mcp-server` → Authentication](https://github.com/korotovsky/slack-mcp-server#authentication). Common landing spots have historically included the browser's Local Storage and `boot_data`/client-boot API responses; do not rely on any single path.

### 2. Register the integration

```bash
printf 'SLACK_MCP_XOXC_TOKEN=xoxc-...\nSLACK_MCP_XOXD_TOKEN=xoxd-...' | \
  clawctl integration registry create slack --type slack-cookie --credential-stdin
```

`clawctl` emits a warning on `create` (and again on every subsequent `sync`) documenting the fragility below.

### 3. Attach + sync as with `slack-user` above.

### Cookie mode security warning

- **TOS-adjacent.** Slack's Acceptable Use Policy is not friendly to automated clients driven by user session cookies. This mode uses your browser session as if it were the API surface; workspace admins can and do audit this pattern.
- **Anti-automation heuristics react to this shape.** Slack's abuse-detection is not publicly documented, but community reports consistently show that high-volume traffic keyed to a `xoxc`/`xoxd` pair — e.g. bulk `conversations_history` fetches — triggers session revocation, account throttling, and admin-visible workspace alerts. Treat it as observable behaviour, not documented policy.
- **`xoxd` rotates unpredictably.** Slack rotates the `d` cookie on browser events (session refresh, password change, admin-triggered session revoke, sometimes at random). When `xoxd` rotates, the MCP subprocess starts returning `401` and every tool call fails until you re-extract and update the credential. There is no refresh path.
- **Blast radius is your full user session.** The token has whatever permissions your user account has, including DMs, private channels, and write access. Cookie mode is not scope-limited — it is your account.

The **recommended path is always `slack-user`.** Cookie mode exists as a graceful fallback for workspaces where you cannot install a Slack App at all; treat it as a discouraged escape hatch, not an equivalent option.

---

## Composite blast-radius warning

Attaching **both** the Slack **channel** (inbound) and the Slack **integration** (outbound) to the **same agent** enables a prompt-injection tool-call exfiltration path:

1. An attacker (or a compromised third party) sends a Slack message to the agent's Slack **channel** — e.g. a DM containing a crafted instruction.
2. The agent's LLM ingests the message as a user turn.
3. The instruction directs the agent to call the Slack **integration** MCP tool (`conversations_add_message`) to post workspace-scoped data (channel history, DMs, search results) back out — to another channel, a DM the attacker controls, or an external webhook the agent has access to via another integration.

Neither the inbound channel nor the outbound integration is broken individually — the risk emerges from **composition**. Traditional MCP tool-approval flows do not distinguish between "this tool call was directed by the human operator" vs. "this tool call was directed by a Slack message the agent just read as content."

**Mitigation:** for high-sensitivity workspaces, run **two separate agents** — one bound only to the Slack **channel** (inbound-only, no Slack integration attached), one attached to the Slack **integration** but not the Slack channel (outbound-only, driven by a different channel like Discord or the CLI). Have the inbound-only agent forward requests via a controlled hand-off (a message queue, a shared memory file, an explicit human approval step). Do **not** attach both surfaces to the same agent when the workspace contains data whose exfiltration you cannot tolerate.

If you attach both to the same agent anyway (small workspaces, personal use), understand that any Slack message reaching the agent can drive Slack MCP tool calls back out until the LLM's own reasoning refuses. That refusal is not a security boundary.

---

## Per-agent-type wiring

Each agent type renders the Slack MCP subprocess into its native config file; the credentials live in the subprocess env block. All three examples below use Linux paths (`/home/<agent-name>/…`); on macOS hosts the equivalent path prefix is `/Users/<agent-name>/…` — the shape is otherwise identical. File mode `0600` is enforced by the configure playbook, not by the renderer itself.

### Hermes → `~/.hermes/config.yaml` (playbook writes mode 0600)

```yaml
mcp_servers:
  slack:
    command: "/home/<agent-name>/.local/bin/slack-mcp-server"
    args: ["--transport", "stdio"]
    env:
      SLACK_MCP_XOXP_TOKEN: 'xoxp-...'
```

For `slack-cookie`, the `env` block instead carries `SLACK_MCP_XOXC_TOKEN` + `SLACK_MCP_XOXD_TOKEN`. Only one Slack integration is permitted per agent — the rendered MCP server key is always the literal `slack` (#846).

See [Hermes agent support → Slack integration](../hermes.md#slack-integration) for the hermes-specific configure flow (single MCP-servers block adjacent to atlassian, macOS support GA).

### OpenClaw → `~/.openclaw/openclaw.json`

```json
{
  "mcp": {
    "servers": {
      "slack": {
        "command": "/home/<agent-name>/.local/bin/slack-mcp-server",
        "args": ["--transport", "stdio"],
        "env": {
          "SLACK_MCP_XOXP_TOKEN": "xoxp-..."
        }
      }
    }
  }
}
```

The top-level `mcp` key is emitted **conditionally** — openclaw agents with no Slack (or other MCP-emitting) integration attached render byte-identical to the pre-#835 output, so upgrading does not touch existing agents. See [OpenClaw agent support → Slack integration](../openclaw.md#slack-integration).

### ZeroClaw → `~/.zeroclaw/config.toml`

```toml
[mcp]
deferred_loading = true
enabled = true

[[mcp.servers]]
name = "slack-slack"
command = "/home/<agent-name>/.local/bin/slack-mcp-server"
args = ["--transport", "stdio"]

[mcp.servers.env]
SLACK_MCP_XOXP_TOKEN = "xoxp-..."
```

Note the ZeroClaw-specific `slack-` prefix on `name`: the zeroclaw TOML template hardcodes `name = "slack-{{ entry.slug }}"` to namespace MCP server names within the zeroclaw daemon's tool surface. Hermes and openclaw do not add this prefix — their key/name is the bare `slack`.

`[mcp].enabled` flips to `true` only when at least one Slack (or other MCP-emitting) integration is attached; zeroclaw agents with no Slack integration render the byte-locked `[mcp]` block with `enabled = false` and no `servers` key at all. See [ZeroClaw agent support → Slack integration](../zeroclaw.md#slack-integration) for the zeroclaw-specific caveats (kevin/armv7l coverage gap, `#437` bearer-rotation ordering).

---

## Binary distribution

`slack-mcp-server` is a single Go binary. clawctl fetches it from the pinned upstream GitHub release, verifies the SHA256, and installs it to `/home/<agent-name>/.local/bin/slack-mcp-server` on Linux (or `/Users/<agent-name>/.local/bin/slack-mcp-server` on macOS) — chmod 0755, owned by the agent user.

The configure playbooks download the **raw binary** directly (not a tarball) via `ansible.builtin.get_url` — the SHA256 pins below are checksums of the bare binaries, not tarball archives:

| OS / arch | Upstream asset (bare binary) | Pinned SHA256 (v1.3.0) |
|-----------|------------------------------|-----------------------:|
| Linux x86_64 | `slack-mcp-server-linux-amd64` | `d1525962e9b9dbfdd2eaf48d0a81ca1eca7d8f1862b8d34931b812c850b3e568` |
| Linux aarch64 | `slack-mcp-server-linux-arm64` | `a307a48d16c2261346bdc257274cdcdb8b2027c867dc971b41d52cef36472c88` |
| macOS arm64 | `slack-mcp-server-darwin-arm64` | `e839aa5c2e28253438ed704dd862aa4afb75711d688080ce447a3b1167855312` |
| macOS x86_64 | `slack-mcp-server-darwin-amd64` | `e38142ee628b2c2ff241f0d021947b96e743540cfb702fc8b01f61a4f7a4a125` |
| Linux armv7l | ❌ Not shipped by upstream at v1.3.0 | — |

The exact download URL template is `https://github.com/korotovsky/slack-mcp-server/releases/download/<version>/slack-mcp-server-<arch-suffix>` — see [`configure.yaml`](https://github.com/ric03uec/clawrium/blob/main/src/clawrium/platform/registry/hermes/playbooks/configure.yaml) in each of the hermes, openclaw, and zeroclaw playbook directories (Linux + `_macos` variants).

The pinned version + SHA maps live in a single Python source of truth at [`src/clawrium/core/playbook_resolver.py`](https://github.com/ric03uec/clawrium/blob/main/src/clawrium/core/playbook_resolver.py) (`_MCP_SLACK_VERSION`, `_MCP_SLACK_SHA256_MAP_LINUX`, `_MCP_SLACK_SHA256_MAP_DARWIN`). Both the hermes and openclaw configure playbooks (Linux + macOS variants) and the zeroclaw configure playbook consume these as extravars threaded by `lifecycle.configure_agent` — a future pin bump lands in one Python location.

**armv7l**: upstream does not publish an armv7 asset at v1.3.0. Raspberry Pi 2/3 (`armv7l`) hosts cannot install this integration until upstream ships an armv7 tarball or clawrium builds one. The configure playbook's arch-guard task fails fast on armv7l hosts with a pointer at the upstream release page. Tracked as a follow-up in the #499 chain.

---

## CLI hygiene — always prefer `--credential-stdin` for tokens

Every long-lived credential (`xoxp`, `xoxc`, `xoxd`) is a bearer token — anyone who reads the value can impersonate the account until it is rotated. The `--credential KEY=VALUE` form on `clawctl integration registry create` and `edit` writes the token into `argv`, which:

- appears in `ps auxww` output while the process runs;
- is captured by any auditing tool that snapshots process args (`auditd`, container runtime logs, some observability agents);
- is written into shell history (`~/.zsh_history`, `~/.bash_history`) unless prefixed with a leading space (and even that is not reliable).

Prefer `--credential-stdin`:

```bash
printf 'SLACK_MCP_XOXP_TOKEN=xoxp-...' | \
  clawctl integration registry create slack --type slack-user --credential-stdin

# multi-credential (slack-cookie)
printf 'SLACK_MCP_XOXC_TOKEN=xoxc-...\nSLACK_MCP_XOXD_TOKEN=xoxd-...' | \
  clawctl integration registry create slack --type slack-cookie --credential-stdin
```

Stdin does not appear in `ps auxww` and is not shell-history-visible unless you deliberately echo it.

---

## One Slack integration per agent

Only one Slack integration can be attached to a given agent. Because the rendered MCP server key is always `slack` (#846), attaching a second Slack integration would collide on that key and `render_hermes` raises `AgentConfigError`. If you need two workspaces, run two separate agents — each with its own Slack integration attached.

---

## Troubleshooting

<details>
<summary><strong>Sync succeeds but the Slack tool doesn't appear in chat</strong></summary>

1. SSH to the agent host and confirm the binary is installed. Use `/home/<agent-name>/…` on Linux hosts and `/Users/<agent-name>/…` on macOS hosts:

   ```bash
   # Linux
   sudo -u <agent-name> stat /home/<agent-name>/.local/bin/slack-mcp-server
   sudo -u <agent-name> /home/<agent-name>/.local/bin/slack-mcp-server --version

   # macOS
   sudo -u <agent-name> stat /Users/<agent-name>/.local/bin/slack-mcp-server
   sudo -u <agent-name> /Users/<agent-name>/.local/bin/slack-mcp-server --version
   ```

   Expected: mode `0755`, version output. If the binary is missing, re-run `clawctl agent sync <agent-name>` — the install task is idempotent.

2. Inspect the rendered config (paths per agent type — see [Per-agent-type wiring](#per-agent-type-wiring); swap `/home/` for `/Users/` on macOS):

   ```bash
   sudo -u <agent-name> cat /home/<agent-name>/.hermes/config.yaml    # hermes
   sudo -u <agent-name> cat /home/<agent-name>/.openclaw/openclaw.json # openclaw
   sudo -u <agent-name> cat /home/<agent-name>/.zeroclaw/config.toml  # zeroclaw
   ```

   Verify the `slack` MCP server entry exists and its env block carries the expected `SLACK_MCP_XOX*` keys.

3. Tail the daemon logs for MCP subprocess errors:

   ```bash
   sudo journalctl -u hermes-<agent-name>.service    -n 200 --no-pager | grep -i mcp
   sudo journalctl -u openclaw-<agent-name>.service  -n 200 --no-pager | grep -i mcp
   sudo journalctl -u zeroclaw-<agent-name>.service  -n 200 --no-pager | grep -i mcp
   ```

</details>

<details>
<summary><strong>`slack_channels_list` returns <code>invalid_auth</code> or <code>token_expired</code></strong></summary>

For `slack-user`: your `xoxp` token has been revoked or the App was uninstalled from the workspace. Re-check the App is still installed under **api.slack.com/apps/&lt;your-app&gt;/install-app** and rotate the User OAuth Token if needed. Update the credential via `clawctl integration registry edit slack --credential-stdin`.

For `slack-cookie`: the `xoxd` cookie has rotated (see [Cookie mode security warning](#cookie-mode-security-warning)). Re-extract both `xoxc` and `xoxd` from a fresh browser session and update the credential. This will happen periodically — cookie mode is inherently fragile.

</details>

<details>
<summary><strong>Sync fails with "unsupported architecture: armv7l"</strong></summary>

The upstream `korotovsky/slack-mcp-server` project does not publish an armv7 asset at v1.3.0. Raspberry Pi 2 / 3 hosts running zeroclaw cannot install this integration until upstream ships an armv7 tarball. Track upstream at [github.com/korotovsky/slack-mcp-server/releases](https://github.com/korotovsky/slack-mcp-server/releases).

</details>

<details>
<summary><strong>Zeroclaw: <code>clawctl agent chat</code> starts returning 401 right after sync</strong></summary>

`clawctl agent sync` on zeroclaw rotates the gateway bearer as part of the standard sync path (issue #437). Remote `clawctl agent chat` sessions (running on a different machine than the one that ran the sync) get a clean 401 on their next request and must reconnect. Local `clawctl agent chat` reconnects transparently. This is unrelated to the Slack integration itself — same behavior applies to every zeroclaw sync.

</details>

---

## Out of scope

- **Slack Enterprise Grid tenant-wide discovery** — the MCP server only sees workspaces the token is installed to.
- **HTTP / SSE transport for `slack-mcp-server`** — clawrium wires the stdio transport because the agent daemon manages the subprocess lifecycle directly; upstream also supports HTTP/SSE but it is not exposed here.
- **Slack Socket Mode** — that is the **channel** side (inbound chat), documented separately at [Slack channel](../channels/slack.md).
- **linux/armv7l** — not shipped by upstream at v1.3.0.

---

## Related

- [Hermes agent support → Slack integration](../hermes.md#slack-integration)
- [OpenClaw agent support → Slack integration](../openclaw.md#slack-integration)
- [ZeroClaw agent support → Slack integration](../zeroclaw.md#slack-integration)
- [Atlassian integration](atlassian.md) — the closest structural analogue (stdio MCP subprocess, per-agent env wiring)
- [Slack channel](../channels/slack.md) — the **inbound** Slack surface (do not confuse; see [Composite blast-radius warning](#composite-blast-radius-warning))
- [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) — upstream MCP server
- [Slack API: OAuth scopes](https://api.slack.com/scopes) — reference for the scopes needed by each tool

[Back to Integrations](index.md)
