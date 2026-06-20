---
name: clawctl
description: Know the clawctl CLI and manage your Clawrium fleet (hosts, agents, providers, channels, integrations, skills, secrets)
argument-hint: "<task or question about fleet management>"
---

# clawctl — Fleet Management CLI

Use this skill whenever the user asks to manage their Clawrium fleet: creating or configuring agents, working with hosts, attaching providers or channels, managing skills, secrets, or memory. All fleet operations use `clawctl` — never `clm`.

## Architecture

```
Your Machine (clawctl CLI)
    │
    ├── Host A ──> zeroclaw instance
    ├── Host B ──> openclaw instance
    └── Host C ──> nemoclaw instance, zeroclaw instance
```

- **Config root**: `~/.config/clawrium/`
- **Agent state**: `~/.config/clawrium/agents/<agent>/`
- **SSH user on every host**: `xclm`
- **Agent types**: `hermes`, `openclaw`, `zeroclaw`, `nemoclaw`

---

## Top-Level Commands

```
clawctl version           # Show version and exit
clawctl completion        # Emit shell-completion script
clawctl tui               # Launch interactive TUI dashboard
clawctl gui               # Launch local web GUI dashboard
clawctl apply <manifest>  # Apply fleet manifest (declarative reconciliation)
clawctl diff <manifest>   # Preview changes without applying
clawctl delete <manifest> # Delete resources declared in a manifest
clawctl service …         # System-level lifecycle ops
clawctl host …            # Manage fleet machines
clawctl agent …           # Manage AI assistant instances
clawctl provider …        # Inference backend providers
clawctl channel …         # Chat surfaces (Discord, Slack)
clawctl integration …     # External service integrations
clawctl skill …           # Skills catalog and user overlay
clawctl mcp …             # MCP servers (placeholder)
```

---

## `clawctl service`

System-level lifecycle for the control plane itself.

```bash
clawctl service init      # Init config dir, check deps (ansible, ssh, python)
clawctl service start     # Start Clawrium daemon (placeholder)
clawctl service stop      # Stop Clawrium daemon (placeholder)
clawctl service snapshot  # Snapshot fleet state (placeholder)
```

**First-time setup**:
```bash
clawctl service init
```

---

## `clawctl host`

Manage fleet machines. Every host must have an `xclm` SSH user — see `docs/host-preparation.md`.

```bash
clawctl host create <hostname-or-ip> --user xclm --alias <name>
clawctl host get                         # List all hosts
clawctl host describe <name>             # Show full host details
clawctl host delete <name>               # Remove host record
clawctl host delete <name> --force       # Also wipe remote xclm state
clawctl host edit <name>                 # Edit host record in $EDITOR
clawctl host reset <name>                # Wipe remote xclm state on host

# Aliases (multi-value)
clawctl host alias <name> --add <alias>
clawctl host alias <name> --remove <alias>
clawctl host alias <name> --list

# Labels (KEY=VALUE / KEY-)
clawctl host label <name> env=prod tier=gpu-a100
clawctl host label <name> env-          # Remove label

# Addresses (multi-value)
clawctl host address add <name> --address <ip-or-dns>
clawctl host address delete <name> --address <ip-or-dns>
clawctl host address get <name>
clawctl host address set-primary <name> --address <ip-or-dns>

# Registry (read-only catalog of host profiles)
clawctl host registry get
clawctl host registry describe <profile>
```

**Quickstart**:
```bash
clawctl host create 192.168.1.100 --user xclm --alias mybox
```

---

## `clawctl agent`

Manage AI assistant instances across the fleet.

### Lifecycle

```bash
clawctl agent create <name> --type <type> --host <host>
clawctl agent get                    # List all agents (status table)
clawctl agent describe <name>        # Full details for one agent
clawctl agent delete <name>          # Remove agent record
clawctl agent edit <name>            # Edit agent record in $EDITOR

clawctl agent configure <name>       # Configure agent (all stages)
clawctl agent configure <name> --stage <stage>  # Single stage
clawctl agent start <name>           # Start agent service
clawctl agent stop <name>            # Stop agent service
clawctl agent restart <name>         # Restart agent service
clawctl agent sync <name>            # Flush control-plane state to host
clawctl agent upgrade <name>         # Upgrade to manifest's max version
clawctl agent doctor <name>          # Diagnose render bundle
clawctl agent logs <name>            # Stream agent logs
```

> `configure`, `sync`, and `restart` all rotate the gateway bearer token
> and overwrite `hosts.json.gateway.auth` atomically (issue #437).

### Interaction

```bash
clawctl agent chat <name>            # Chat with an agent
clawctl agent open <name>            # Open agent web UI in browser
clawctl agent port-forward <name>    # Forward local port to agent
clawctl agent exec <name> -- <args>  # Run command against agent's native CLI
clawctl agent shell <name> -- <cmd>  # Run a command in the agent user's login bash shell on the host
```

> `exec` invokes the agent's native binary (`hermes`, `openclaw`, …);
> `shell` runs `/bin/bash -lic '<cmd>'` as the agent user with the
> full login + interactive env (sources `~/.bash_profile`,
> `~/.profile`, AND `~/.bashrc` — PATH shims, virtualenvs, pipes,
> redirects all work).
> Use `shell` for host-level ops (`ls`, `cat`, `make`, `git`, …).
> Non-interactive only; `--timeout SECONDS` controls the kill window
> (default 120s, hard-capped at 1800s; `0` is an alias for that cap,
> no value disables it).
> Linux hosts only in v1; macOS hosts return a clear preflight error.

### Provider attachments

```bash
clawctl agent provider attach <agent> --provider <provider-name>
clawctl agent provider detach <agent> --provider <provider-name>
clawctl agent provider get <agent>
```

### Channel attachments

```bash
clawctl agent channel attach <agent> --channel <channel-name>
clawctl agent channel detach <agent> --channel <channel-name>
clawctl agent channel get <agent>
```

### Integration attachments

```bash
clawctl agent integration attach <agent> --integration <integration-name>
clawctl agent integration detach <agent> --integration <integration-name>
clawctl agent integration get <agent>
```

### Skills (local, agent-native)

```bash
clawctl agent skill list <agent>
clawctl agent skill add <agent> --from-template <registry>/<name>
clawctl agent skill edit <agent> <skill-name>
clawctl agent skill remove <agent> <skill-name>
# After any skill change, push to host:
clawctl agent sync <agent>
```

Skill references use `<registry>/<name>` (e.g. `clawrium/tdd`) when
copying from the catalog. Once local, the bare name is used (`tdd`).

### Secrets

```bash
clawctl agent secret create <agent> <key> --value <val>   # or prompts
clawctl agent secret create <agent> <key> --stdin          # read from stdin
clawctl agent secret get <agent>                           # List keys
clawctl agent secret describe <agent> <key>                # Metadata only
clawctl agent secret delete <agent> <key>
clawctl agent secret import <agent> --file <dotenv-file>   # Bulk import
```

### Memory

```bash
clawctl agent memory get <agent>               # List memory files
clawctl agent memory get <agent> <file>        # Print one file's content
clawctl agent memory describe <agent> <file>   # Metadata
clawctl agent memory edit <agent> <file> --content <text>
clawctl agent memory delete <agent> <file>
```

### Registry (read-only)

```bash
clawctl agent registry get
clawctl agent registry describe <type>
```

---

## `clawctl provider`

Register inference backends. Providers use Pattern A (attachable).

```bash
clawctl provider registry create <name> --type <type> [flags]
clawctl provider registry get                         # List all providers
clawctl provider registry get --types                 # List supported types
clawctl provider registry describe <name>
clawctl provider registry delete <name>
clawctl provider registry edit <name>
clawctl provider registry refresh <name>              # Refresh Ollama models
```

**Common provider types**: `anthropic`, `openai`, `ollama`, `litellm`

**LiteLLM/custom OpenAI-compatible proxy**:
```bash
clawctl provider registry create myproxy \
  --type litellm \
  --litellm-url http://localhost:8000/v1 \
  --model gpt-4o \
  --api-key <bearer>
```

---

## `clawctl channel`

Register chat surfaces (Discord, Slack). Uses Pattern A.

```bash
clawctl channel registry create <name> --type <type> [flags]
clawctl channel registry get
clawctl channel registry describe <name>
clawctl channel registry delete <name>
clawctl channel registry edit <name>
```

---

## `clawctl integration`

Register external service integrations. Uses Pattern A.

```bash
clawctl integration registry create <name> --type <type> --credential KEY=VALUE
clawctl integration registry get
clawctl integration registry get --types           # List supported types
clawctl integration registry describe <name>
clawctl integration registry delete <name>
clawctl integration registry edit <name>
```

Credentials are never printed. `clawctl agent describe` / `clawctl integration registry describe` shows `Credentials: set` only.

---

## `clawctl skill`

Skills catalog and user overlay management (operator-side; distinct from `clawctl agent skill`).

```bash
clawctl skill add ./my-skill-dir --registry <registry>
clawctl skill registry get
clawctl skill registry get --registry <registry>   # Filter by registry
clawctl skill registry describe <registry>/<name>
```

User overlay lives at `~/.config/clawrium/skills/<registry>/<name>/`.
Overlay entries win over bundled catalog entries for the same slug.

---

## `clawctl mcp`

MCP server management (placeholder — commands exist but are not yet functional).

```bash
clawctl mcp registry get
clawctl mcp registry describe <name>
```

---

## Common Workflows

### First host + first agent

```bash
clawctl service init
clawctl host create 192.168.1.100 --user xclm --alias mybox
clawctl agent create myassistant --type openclaw --host mybox
clawctl agent configure myassistant
clawctl agent start myassistant
clawctl agent chat myassistant
```

### Add a provider and attach it

```bash
clawctl provider registry create myanthropic --type anthropic --api-key $KEY
clawctl agent provider attach myassistant --provider myanthropic
clawctl agent sync myassistant
```

### Install a skill

```bash
clawctl skill registry get                                    # Browse
clawctl skill registry describe clawrium/tdd                  # Inspect
clawctl agent skill add myassistant --from-template clawrium/tdd
clawctl agent sync myassistant
```

### Check fleet health

```bash
clawctl agent get
clawctl agent doctor myassistant
clawctl agent logs myassistant
```

### Manage secrets

```bash
clawctl agent secret create myassistant ANTHROPIC_API_KEY --stdin <<< "$KEY"
clawctl agent secret get myassistant
```

### Open the web UI

```bash
clawctl agent open myassistant    # opens in browser via SSH tunnel
clawctl gui                        # local web dashboard for the whole fleet
```

---

## Key Rules

1. **Always use `clawctl`** — the legacy `clm` CLI was removed in v26.6.3.
2. **After any local state change, run `clawctl agent sync <agent>`** to push to the host.
3. **`configure`, `sync`, and `restart` rotate the bearer token** — remote chat sessions will get a 401 and must reconnect.
4. **Never push directly to `main`** — all changes go via feature branch and PR.
5. **`clawctl agent skill add` writes control-plane only**; `sync` pushes to the host.
6. **Secret values are never printed** — `describe` shows `set`/`unset` only.
7. **Host `~` in on-host paths is the agent unix user's home**, not the operator's.

---

## Audit Logging

Every mutating `clawctl` command you run on the user's behalf — and every mutating command you guide the user to run themselves — MUST be recorded in the operator's audit trail. The trail is the full history of what happened on this control machine via the `/clawctl` skill, and is the only way the operator can later answer "what did the agent do, when, and with what result?"

The audit trail is owned by the **`clawctl audit`** subcommand. Always call `clawctl audit log` — **never hand-roll JSON lines** with `printf`, `echo`, or `jq` in the chat. Hand-rolled lines break the file the moment a `notes` string contains a quote, newline, or backslash.

### The tool

`clawctl audit` is a built-in subcommand of `clawctl` — no separate binary to install. If you have `clawctl` on PATH, you have audit. Logs live at `~/.config/clawrium/changelog/<YYYYMMDD>.jsonl` (one file per UTC day, append-only, one JSON object per line).

Schema per line (managed by `clawctl audit`, **do not write directly**):

| Field | Filled by | Notes |
|---|---|---|
| `type` | tool | Discriminator; currently always `"clawctl_command"`. Reserved for future entry shapes. |
| `uuid` | tool | uuid4, unique per entry. Use to cross-reference. |
| `parent_uuid` | you (optional) | Causal link — set to the previous entry's `uuid` when one step depends on another |
| `session_id` | env / flag | Group everything you do in one workflow (see below) |
| `timestamp` | tool | ISO 8601 UTC, millisecond precision |
| `cwd` | tool | The working directory at write time — useful when the operator asks "where was I when this ran?" |
| `version` | tool | `{audit, clawctl}` — schema version + clawctl version |
| `actor` | you | `"user"` or `"agent"` |
| `action` | you | Short description; **include the literal command** when relevant |
| `result` | you | `"success"`, `"failure"`, or `"skipped"` |
| `notes` | you | Free text — error output, confirmation, surrounding context |

### Sessions

Before kicking off a multi-step workflow on the user's behalf, mint a session id and export it so every `clawctl audit log` call inside the workflow is grouped:

```bash
export CLAWCTL_AUDIT_SESSION_ID="$(clawctl audit session new)"
```

Every subsequent `log` invocation in that shell will tag entries with that session id. The operator can then run `clawctl audit show --session-id <id>` to replay the full workflow.

You may also pass `--session-id <id>` explicitly to override the env var for a single entry.

### Writing entries

```
clawctl audit log "<action>" --result <success|failure|skipped> [--actor <user|agent>] [--notes "<context>"]
```

`--actor` defaults to `agent` (you ran the command yourself). Pass `--actor user` only when the operator ran the command directly and asked you to record it.

Examples (always copy this shape — do NOT improvise the JSON):
```
clawctl audit log "clawctl agent start myassistant" --result success --notes "started zeroclaw on host mybox"
clawctl audit log "clawctl agent configure myassistant" --result failure --notes "ansible failed at stage 'render templates'; see clawctl agent doctor for details"
clawctl audit log "clawctl agent skill add myassistant --from-template clawrium/tdd" --result success
```

### Chaining steps with `parent_uuid` (optional)

If you want to make causal dependency explicit (`configure` → `start` → `sync`), capture the parent's uuid with `--print-uuid` and pass it on the next entry:

```bash
PARENT=$(clawctl audit log "clawctl agent configure myassistant" --result success --print-uuid)
clawctl audit log "clawctl agent start myassistant" --result success --parent-uuid "$PARENT"
```

This is optional. If you don't chain, `parent_uuid` is null and the trail is still useful for time-ordered review.

### Reading the trail

```
clawctl audit tail [-n N]                                    # Last N entries across every day (default 20)
clawctl audit show --date YYYYMMDD                           # One day's entries
clawctl audit show --actor agent --result failure --last 50  # Failures attributed to the agent
clawctl audit show --session-id <id>                         # Everything in one workflow
clawctl audit show --grep '<regex>' [--json]                 # Regex over action+notes, optional raw JSONL
clawctl audit stats [--top N]                                # Summary counts + top action groups
clawctl audit path                                           # Print the log directory
clawctl audit session new                                    # Mint a session id (export it before a workflow)
```

Use these — never `cat`, `grep`, or `jq` the JSONL files in the chat output. The tool understands the schema and won't choke on partial writes.

### When to log

| Log it | Don't log it |
| --- | --- |
| `create`, `delete`, `configure`, `start`, `stop`, `restart`, `sync`, `upgrade`, `apply` | `get`, `describe`, `logs`, `chat`, `open`, `version` |
| Provider / channel / integration `attach` / `detach` | `--help`, registry browse commands |
| `skill add` / `skill remove`, `secret create` / `delete`, `memory edit` / `delete` | Read-only queries used purely to inform a recommendation |
| **Failures** of any mutating command (with the error in `notes`) | |

### If `clawctl` is not on PATH

Stop and tell the operator to install clawctl first — `clawctl audit` ships with it:

```
uv tool install clawrium
```

Do not fall back to inline `jq`/`printf` — fragile JSON in the trail is worse than no trail.

---

## Maintenance Note

This skill must be updated whenever the `clawctl` CLI surface changes — new commands, renamed flags, or deprecated sub-commands. Run `clawctl --help` and each group's `--help` to verify the current surface before updating.

This skill ships in two locations so it is discoverable by both Claude Code and opencode:

- `.claude/skills/clawctl/SKILL.md`
- `.opencode/skills/clawctl/SKILL.md`

The two files MUST stay byte-identical — update both in the same change. `diff` them in CI or pre-commit to enforce.
