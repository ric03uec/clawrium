# Issue #435 — User can use clawctl with kubectl-style UX across the fleet

GitHub: https://github.com/ric03uec/clawrium/issues/435

---

## Plan (WHAT)

This document captures **what** changes. No execution steps. No subtasks. No
how. Sign-off here gates the next stage (`01_SCAFFOLD.md`).

### 1. Scope

| In scope | Out of scope |
|---|---|
| Full move `clm` → `clawctl`. No alias. No deprecation. | Backwards-compat shims |
| kubectl-style verb grammar across the whole CLI | `apply` verb (tracked separately) |
| Output standardization: kubectl tabwriter padding + `-o table\|json\|yaml\|wide\|name` + `--no-headers` on every `get` | `get all` aggregate |
| New top-level noun `channel` (extracts Discord/Slack from interactive `agent configure`) | GUI behavioural changes |
| New `service` group for system-level ops: `init`, `start`, `stop` (placeholder), `status` (added later), `snapshot` (placeholder) | Version bump (separate issue) |
| Template rename: zeroclaw + hermes templates carry their agent-type prefix | `xclm` system user rename |
| `sync` redefined as drift-to-zero flush with 2-min default timeout | Migration tooling (no data migration; reinstall expected) |
| Non-interactive contract: every command runs to completion via flags alone | `--from-file` for normal config (CLI flags only — exception below) |
| `registry` is the canonical CRUD home for attachable resources (provider, channel, integration, skill, mcp) | Single-file `apply -f manifest.yaml` workflow |
| wolf-i fleet audit captured before and after the change as a regression artifact | Frontend / UI redesign |

### 2. Guardrails

- `clawrium.core.*` modules — untouched. CLI is the only layer that changes.
- `xclm` system user on managed hosts — untouched.
- GUI — only its **textual references** (`clm` strings in copy, tooltips,
  docstrings, commands shown to copy) become `clawctl`. Backend imports stay
  imports.
- TUI / GUI / chat / port-forward / open / logs — rebranded names only;
  internals untouched.
- Protocols (gateway WebSocket, OpenAI HTTP, ansible playbooks) — untouched.
- No version bump in this issue. Done in a follow-up.

### 3. Domain model

Two structural patterns govern the surface:

**Pattern A — Attachables.** Things that get registered once and attached to
agents many times. Their **only** CRUD entrypoint is `clawctl <noun> registry`.
Per-agent operations are `attach` / `detach` / `get`.

  - `provider` — inference backends
  - `channel` — chat surfaces (Discord, Slack) — **new top-level noun**
  - `integration` — external service bindings (GitHub, Linear, etc.)
  - `skill` — repo-bundled skills (read-only registry; CRUD = `get` only)
  - `mcp` — placeholder; not implemented

**Pattern B — Targets.** Things that exist independently and ARE the
operational targets. CRUD lives directly on the noun; `registry` is a
read-only sub-verb for the supported-types catalog.

  - `host` — fleet machine
  - `agent` — AI assistant instance running on a host

**Sub-resources of `agent`** that don't fit either pattern (because they
exist only in the context of a single agent):

  - `agent secret` — per-agent secrets store
  - `agent memory` — per-agent memory files

Everything else attaches to agents via Pattern A's `attach`/`detach`.

### 4. Full CLI surface

```
clawctl
├── service                                          # system-level group
│   ├── init                                         # was: clm init
│   ├── start                                        # placeholder; prints "not implemented"
│   ├── stop                                         # placeholder; prints "not implemented"
│   ├── status                                       # added later (out of scope this issue)
│   └── snapshot                                     # placeholder; prints "not implemented"
│
├── version                                          # explicit verb (--version also works)
├── completion <bash|zsh|fish>                       # NEW
├── tui                                              # rebranded
├── gui [--port] [--no-open]                         # rebranded
│
├── host                                             # Pattern B (target)
│   ├── create <hostname>
│   │     --user U [--port P] [--alias A]
│   │     [--accept-host-key SHA256|*] [--bootstrap]
│   ├── get [-o ...] [-l KEY=VALUE] [--no-headers]
│   ├── describe <hostname> [-o yaml|json]
│   ├── delete <hostname> [--yes]
│   ├── edit <hostname> [--user U] [...]
│   ├── reset <hostname> [--yes]                     # destructive remote wipe; distinct from delete
│   ├── alias <hostname>                             # multi-alias mgmt (a host can have many)
│   │     {--add A | --remove A | --list}
│   ├── address <hostname>                           # nested; addresses are sub-resources
│   │     {add <addr> | delete <addr> | get | set-primary <addr>}
│   ├── label <hostname> KEY=VALUE [KEY-]            # was: host tag
│   └── registry                                     # read-only types catalog (placeholder content)
│       ├── get
│       └── describe <profile>
│
├── agent                                            # Pattern B (target)
│   ├── create <name>
│   │     --type T --host H [--provider P] [--yes]
│   ├── get [-o ...] [--no-headers]
│   ├── describe <name> [-o yaml|json]
│   ├── delete <name> [--yes]
│   ├── edit <name>                                  # opens $EDITOR on YAML of agent record
│   ├── configure <name>                             # all-flags, no prompts
│   │     [--stage providers|identity|channels|validate]
│   │     [--provider P] [--personality T]
│   │     [--channel CH ...] [--yes]
│   ├── start <name> [--force]
│   ├── stop <name>
│   ├── restart <name>
│   ├── sync <name> [--workspace] [--dry-run] [--timeout 120] [--skip-validate]
│   ├── logs <name> [-f] [--tail N] [-o text|json]
│   ├── chat <name> [--session] [--timeout] [--idle-timeout] [--once "msg"]
│   ├── open <name>                                  # browser → web UI
│   ├── port-forward <name> [LOCAL:]REMOTE
│   ├── exec <name> -- <cmd>                         # placeholder; not implemented now
│   │
│   ├── secret                                       # agent-scoped, not Pattern A
│   │   ├── create <key> --agent N {--value V | --value-stdin}
│   │   ├── get --agent N
│   │   ├── describe <key> --agent N
│   │   ├── delete <key> --agent N [--yes]
│   │   └── import --agent N --from-file <path>      # exception: file body input
│   │
│   ├── memory                                       # agent-scoped, not Pattern A
│   │   ├── get --agent N [--file F]
│   │   ├── describe <file> --agent N
│   │   ├── edit <file> --agent N
│   │   │     {--content "..." | --from-file <path>} # exception: file body input
│   │   └── delete <file> --agent N [--yes]
│   │
│   ├── provider                                     # Pattern A per-agent
│   │   ├── attach <name> --agent N
│   │   ├── detach <name> --agent N
│   │   └── get --agent N
│   │
│   ├── channel                                      # Pattern A per-agent
│   │   ├── attach <name> --agent N
│   │   ├── detach <name> --agent N
│   │   └── get --agent N
│   │
│   ├── integration                                  # Pattern A per-agent
│   │   ├── attach <name> --agent N
│   │   ├── detach <name> --agent N
│   │   └── get --agent N
│   │
│   ├── skill                                        # Pattern A per-agent
│   │   ├── attach <skill-ref> --agent N
│   │   ├── detach <skill-ref> --agent N
│   │   └── get --agent N
│   │
│   └── registry                                     # read-only types catalog
│       ├── get                                      # supported agent types
│       └── describe <type>
│
├── provider                                         # Pattern A
│   └── registry                                     # ONLY CRUD entrypoint
│       ├── create <name>
│       │     --type T [--model M]
│       │     [--api-key K | --api-key-stdin]
│       │     [--access-key K --secret-key K --region R]   # AWS
│       │     [--ollama-url U]                              # Ollama
│       ├── get [-o ...] [--no-headers]
│       ├── describe <name> [-o yaml|json]
│       ├── delete <name> [--yes]
│       ├── edit <name> [--model M] [--api-key K | --api-key-stdin] [...]
│       └── refresh <name>
│
├── channel                                          # Pattern A (NEW noun)
│   └── registry                                     # ONLY CRUD entrypoint
│       ├── create <name>
│       │     --type discord|slack
│       │     {--token T | --token-stdin}
│       │     [--app-token T]                                  # slack
│       │     [--allowed-user ID ...]
│       │     [--allowed-channel ID ...]
│       │     [--allowed-guild ID ...]                         # discord
│       │     [--home-channel ID]
│       │     [--require-mention | --no-require-mention]
│       │     [--stream-mode replace|append] [--stream-delay MS]
│       ├── get
│       ├── describe <name>
│       ├── delete <name> [--yes]
│       └── edit <name> [...same flags as create]
│
├── integration                                      # Pattern A
│   └── registry                                     # ONLY CRUD entrypoint
│       ├── create <name>
│       │     --type T [--credential KEY=VALUE ...] [--credential-stdin]
│       ├── get
│       ├── describe <name>
│       ├── delete <name> [--yes]
│       └── edit <name>
│
├── skill                                            # Pattern A
│   └── registry                                     # read-only (skills are repo-bundled)
│       ├── get [-l registry=clawrium]
│       └── describe <skill-ref>
│
└── mcp                                              # Pattern A — PLACEHOLDER
    └── registry
        ├── get                                      # prints "not implemented"
        └── describe <name>                          # prints "not implemented"
```

#### 4.1 Notes on the surface

- **Lifecycle nested under `agent`** (`clawctl agent start`, not
  `clawctl start`). Symmetry with the noun-grouping for hosts/providers
  beats brevity.
- **`agent provider attach`** (Pattern A) replaces the implicit provider
  selection inside `agent configure`. Configure remains for legacy stage
  control; `attach` is the modern path.
- **`channel` is a brand-new global resource.** The ~30 interactive prompts
  in `agent.py:792–1305` (Discord, Slack bot tokens, allowed users,
  allowed channels, etc.) become `clawctl channel registry create` flags.
- **`--yes`** replaces `--force` everywhere for "skip confirm prompt".
  `--force` remains only for true override-safety-check semantics
  (e.g., `agent create --force` for reinstall over existing).
- **`reset` ≠ `delete`.** Delete removes the local record; reset wipes
  remote state. Two distinct verbs by intent.
- **`alias`** is multi-value mgmt (`--add/--remove/--list`), not a rename.
- **No `clawctl ps` at root.** `ps` removed entirely; describe replaces show.

### 5. BEFORE → AFTER command map

Old commands and their new equivalents. Every entry is a hard replacement
(no alias kept).

| Today (`clm`) | After (`clawctl`) |
|---|---|
| `clm init` | `clawctl service init` |
| `clm snapshot` | `clawctl service snapshot` |
| `clm ps` | `clawctl agent get` |
| `clm tui` | `clawctl tui` |
| `clm gui` | `clawctl gui` |
| `clm chat <a>` | `clawctl agent chat <a>` |
| `clm host init <h>` | `clawctl host create <h> --bootstrap` |
| `clm host add <h>` | `clawctl host create <h>` |
| `clm host list` | `clawctl host get` |
| `clm host ps <h>` | `clawctl host describe <h>` |
| `clm host remove <h>` | `clawctl host delete <h>` |
| `clm host alias <h> --set X` | `clawctl host alias <h> --add X` |
| `clm host tag <h> add K=V` | `clawctl host label <h> K=V` |
| `clm host update <h>` | `clawctl host edit <h>` |
| `clm host reset <h>` | `clawctl host reset <h>` |
| `clm host address add` | `clawctl host address add` |
| `clm agent install` | `clawctl agent create` |
| `clm agent ps` | `clawctl agent get` |
| `clm agent configure <a>` | `clawctl agent configure <a>` |
| `clm agent remove <a>` | `clawctl agent delete <a>` |
| `clm agent start/stop/restart/sync <a>` | `clawctl agent start/stop/restart/sync <a>` |
| `clm agent open <a>` | `clawctl agent open <a>` |
| `clm agent logs <a>` | `clawctl agent logs <a>` |
| `clm agent secret set <a> <k> --value V` | `clawctl agent secret create <k> --agent <a> --value V` |
| `clm agent secret list <a>` | `clawctl agent secret get --agent <a>` |
| `clm agent secret remove <a> <k>` | `clawctl agent secret delete <k> --agent <a>` |
| `clm agent secret import <a> <f>` | `clawctl agent secret import --agent <a> --from-file <f>` |
| `clm agent memory show <a>` | `clawctl agent memory get --agent <a>` |
| `clm agent memory edit <a>` | `clawctl agent memory edit <file> --agent <a> --from-file <f>` |
| `clm agent memory delete <a>` | `clawctl agent memory delete <file> --agent <a>` |
| `clm agent integration list <a>` | `clawctl agent integration get --agent <a>` |
| `clm agent integration add <a> <i>` | `clawctl agent integration attach <i> --agent <a>` |
| `clm agent integration remove <a> <i>` | `clawctl agent integration detach <i> --agent <a>` |
| `clm agent skill list <a>` | `clawctl agent skill get --agent <a>` |
| `clm agent skill install <a> <s>` | `clawctl agent skill attach <s> --agent <a>` |
| `clm agent skill remove <a> <s>` | `clawctl agent skill detach <s> --agent <a>` |
| `clm agent registry list` | `clawctl agent registry get` |
| `clm agent registry show <t>` | `clawctl agent registry describe <t>` |
| `clm provider add <p> --type T ...` | `clawctl provider registry create <p> --type T ...` |
| `clm provider list` | `clawctl provider registry get` |
| `clm provider edit <p>` | `clawctl provider registry edit <p>` |
| `clm provider remove <p>` | `clawctl provider registry delete <p>` |
| `clm provider types` | `clawctl provider registry get --types` *or* derived from `describe` |
| `clm provider refresh <p>` | `clawctl provider registry refresh <p>` |
| `clm integration types` | `clawctl integration registry get --types` |
| `clm integration list` | `clawctl integration registry get` |
| `clm integration add <i> --type T` | `clawctl integration registry create <i> --type T --credential K=V ...` |
| `clm integration show <i>` | `clawctl integration registry describe <i>` |
| `clm integration remove <i>` | `clawctl integration registry delete <i>` |
| `clm integration credentials <i>` | `clawctl integration registry describe <i>` |
| `clm skill list` | `clawctl skill registry get` |
| `clm skill show <s>` | `clawctl skill registry describe <s>` |
| (n/a — Discord/Slack lived as `agent configure` prompts) | `clawctl channel registry create <name> --type discord --token ... ...` |
| (n/a) | `clawctl agent channel attach <name> --agent <a>` |
| (n/a) | `clawctl completion <bash\|zsh\|fish>` |

### 6. Output format contract

#### 6.1 Format rules

- Default `get`: plain-text aligned table, kubectl-style. **Option B
  padding**: fixed-width per row using the max width across all rows in
  that column, minimum 3 spaces between columns. No Rich borders. No
  background colors. Status token may be colored on `--output table` only
  when stdout is a TTY; otherwise raw token.
- `--no-headers`: skip the header row.
- `-o name`: `<kind>/<name>` one per line.
- `-o json`: array of objects; field names in `snake_case`; timestamps
  as RFC3339 UTC; `age_seconds` as int.
- `-o yaml`: same shape as JSON, YAML-encoded.
- `-o wide`: like default but includes extra columns
  (ADDRESS, VERSION, INSTALLED, PORT).
- Actions stream events to stdout, one line per phase. `-o json` emits
  one JSON object per line (NDJSON).
- All errors → stderr, exit code non-zero, plain text starting with
  `Error: ` followed by a one-line `Hint: ` when applicable.

#### 6.2 Sample: `agent get` default

```
$ clawctl agent get
NAME             TYPE       HOST     PROVIDER    STATUS     AGE
wise-hypatia     openclaw   wolf-i   anthropic   running    3d
nemotron-alpha   zeroclaw   wolf-i   nemotron    degraded   5h
hermes-prod      hermes     kevin    anthropic   running    12d
```

#### 6.3 Sample: `agent get -o wide`

```
$ clawctl agent get -o wide
NAME             TYPE       HOST     ADDRESS        PROVIDER    STATUS     AGE   PORT    VERSION   INSTALLED
wise-hypatia     openclaw   wolf-i   192.168.1.10   anthropic   running    3d    -       0.4.2     2026-05-20
nemotron-alpha   zeroclaw   wolf-i   192.168.1.10   nemotron    degraded   5h    40123   2.1.0     2026-05-22
hermes-prod      hermes     kevin    192.168.1.20   anthropic   running    12d   45001   1.8.3     2026-05-11
```

#### 6.4 Sample: `agent get -o name`

```
$ clawctl agent get -o name
agent/wise-hypatia
agent/nemotron-alpha
agent/hermes-prod
```

#### 6.5 Sample: `agent get -o json`

```json
[
  {
    "kind": "agent",
    "name": "wise-hypatia",
    "type": "openclaw",
    "host": "wolf-i",
    "address": "192.168.1.10",
    "provider": "anthropic",
    "status": "running",
    "age_seconds": 259200,
    "port": null,
    "version": "0.4.2",
    "installed_at": "2026-05-20T14:23:11Z"
  }
]
```

#### 6.6 Sample: `agent get -o yaml`

```yaml
- kind: agent
  name: wise-hypatia
  type: openclaw
  host: wolf-i
  address: 192.168.1.10
  provider: anthropic
  status: running
  age_seconds: 259200
  port: null
  version: 0.4.2
  installed_at: 2026-05-20T14:23:11Z
```

#### 6.7 Sample: `agent describe`

```
$ clawctl agent describe wise-hypatia
Name:        wise-hypatia
Kind:        agent
Type:        openclaw
Version:     0.4.2
Host:        wolf-i (192.168.1.10)
Provider:    anthropic
Status:      running
Age:         3d
Installed:   2026-05-20T14:23:11Z

Config:
  Port:           -
  Identity File:  ~/.openclaw/IDENTITY.md
  Soul File:      ~/.openclaw/SOUL.md

Skills (2):
  clawrium/tdd
  clawrium/code-review

Integrations (1):
  github       (configured)

Channels: none

Onboarding:
  providers   complete   (2026-05-20)
  identity    complete   (2026-05-20)
  channels    skipped
  validate    complete   (2026-05-20)
```

#### 6.8 Sample: action streaming default

```
$ clawctl agent create wise-hypatia --type openclaw --host wolf-i --provider anthropic
agent/wise-hypatia: installing on wolf-i
agent/wise-hypatia: installed  (0.4.2)
agent/wise-hypatia: configuring providers
agent/wise-hypatia: configured
agent/wise-hypatia: started
agent/wise-hypatia: ready
```

#### 6.9 Sample: action streaming `-o json` (NDJSON)

```
{"resource":"agent/wise-hypatia","phase":"install","state":"started","ts":"2026-05-23T10:14:00Z"}
{"resource":"agent/wise-hypatia","phase":"install","state":"complete","version":"0.4.2","ts":"2026-05-23T10:14:42Z"}
{"resource":"agent/wise-hypatia","phase":"configure","state":"complete","ts":"2026-05-23T10:15:01Z"}
{"resource":"agent/wise-hypatia","phase":"start","state":"complete","ts":"2026-05-23T10:15:14Z"}
```

#### 6.10 Sample: `agent sync`

```
$ clawctl agent sync wise-hypatia
agent/wise-hypatia: validating local state
agent/wise-hypatia: pushing config (provider, skills, channels, env)
agent/wise-hypatia: restarting unit
agent/wise-hypatia: re-pairing gateway
agent/wise-hypatia: verifying health
agent/wise-hypatia: synced  (drift=0, took 18s)
```

#### 6.11 Sample: `agent logs`

```
$ clawctl agent logs wise-hypatia --tail 3
2026-05-23T10:14:00Z  INFO   daemon    startup complete
2026-05-23T10:14:02Z  INFO   gateway   listening on 0.0.0.0:40123
2026-05-23T10:14:15Z  INFO   session   main connected
```

```
$ clawctl agent logs wise-hypatia --tail 3 -o json
{"ts":"2026-05-23T10:14:00Z","level":"info","module":"daemon","msg":"startup complete"}
{"ts":"2026-05-23T10:14:02Z","level":"info","module":"gateway","msg":"listening on 0.0.0.0:40123"}
{"ts":"2026-05-23T10:14:15Z","level":"info","module":"session","msg":"main connected"}
```

#### 6.12 Sample: error

```
$ clawctl agent create dup-name --type openclaw --host wolf-i
Error: agent "dup-name" already exists on host "wolf-i"
Hint:  clawctl agent describe dup-name
exit code: 1
```

#### 6.13 Status vocabulary (single source of truth)

| Token | Meaning | TTY color |
|---|---|---|
| `running` | unit up + health checks passing | green |
| `degraded` | unit up but missing deps (secrets, providers) | yellow |
| `stopped` | unit not active | red |
| `pending` | install record present, never started | yellow |
| `onboarding` | configure phase incomplete | cyan |
| `ready` | configured + healthy but stopped | blue |
| `installing` | install in progress | yellow |
| `failed` | install/configure failed | red |
| `unknown` | health check inconclusive | yellow |

Reasons (e.g., missing secret keys) move to `describe`, never the column.

#### 6.14 AGE formatting

`<60s` → `Xs` · `<60m` → `Xm` · `<24h` → `Xh` · everything else → `Xd`.
No weeks/months — kubectl convention.

### 7. Non-interactive contract

**Hard rule:**

> If all mandatory flags are supplied, the command MUST run to completion
> with **no stdin reads**.
> If a mandatory flag is missing AND stdin is a TTY, the command MAY prompt.
> If a mandatory flag is missing AND stdin is NOT a TTY, the command MUST
> fail fast with a clear error pointing to the missing flag.

**Single exception:** large file-body input. Allowed via either
`--from-file <path>` or `--from-stdin`, in addition to `--content "..."`:

- `agent secret create --value V | --value-stdin | --from-file <path>`
- `agent memory edit --content "..." | --from-file <path>`
- `agent secret import --from-file <path>`

Every interactive prompt in today's CLI (audited from `typer.prompt`,
`typer.confirm` call sites) closes via the flag sets defined in §4.
Discord/Slack prompts move entirely into `clawctl channel registry create`.
Provider credential prompts close via `--api-key` / `--api-key-stdin` /
`--access-key` / `--secret-key` / `--region` / `--ollama-url`.

### 8. `clawctl channel` — the functional shift

**Today:** Discord/Slack are configured inline inside `clm agent configure`
via ~30 prompts (`agent.py:792–1305`). State lives inside each agent's
record in `hosts.json`.

**After:** channels are first-class records, reusable across agents.

- **Storage:** new file `~/.config/clawrium/channels.json` (sibling to
  `providers.json`, `integrations.json`).
- **CRUD:** only via `clawctl channel registry create|get|describe|delete|edit`.
- **Attachment:** `clawctl agent channel attach <name> --agent <a>` writes
  the channel reference into the agent's record. `detach` removes it.
- **No migration tool.** Per the breaking-change posture, users delete
  existing agents and recreate via the new flag-driven path.

Schema (per channel):

```yaml
name: my-discord
type: discord
credentials:
  bot_token: <encrypted>
config:
  allowed_users:    [<id>, <id>]
  allowed_channels: [<id>]
  allowed_guilds:   [<id>]
  home_channel:     <id>
  require_mention:  true
  stream_mode:      replace
  stream_delay_ms:  100
```

### 9. `sync` redefined

`clawctl agent sync <name>` executes in this order:

1. **Validate** local control-plane state (same `validate` stage as today).
2. **Push** all controlled artifacts unconditionally (no diff-skip):
   provider config(s), integration credentials, channel configs, skills,
   identity/SOUL/workspace files, systemd drop-in env file.
3. **Restart** the agent unit unconditionally.
4. **Re-pair** the gateway (zeroclaw) per issue #437.
5. **Verify** post-restart health.
6. Emit one structured event per phase (`-o json` = NDJSON).

**Flags:**

- `--timeout 120` — default 2 minutes; flag overrides.
- `--workspace` — workspace files only, no restart.
- `--dry-run` — validate + show diff vs remote, no push.
- `--skip-validate` — escape hatch.

**Drift contract:** after a successful `sync`, the agent's on-disk
config matches local control-plane byte-for-byte (modulo Jinja
templating). `--dry-run` proves the drift before flushing.

### 10. Template file rename

Per-agent-type prefix convention codified going forward.

| Registry | Source today | Source after | Destination on agent host |
|---|---|---|---|
| zeroclaw | `templates/clm-env.conf.j2` | `templates/zeroclaw-env.conf.j2` | `/etc/systemd/system/zeroclaw-<n>.service.d/10-zeroclaw-env.conf` |
| zeroclaw | `templates/config.toml.j2` | `templates/zeroclaw-config.toml.j2` | `~/.zeroclaw/config.toml` (zeroclaw runtime's expected name) |
| zeroclaw | `playbooks/configure.yaml:112-113` | references updated source + dest | — |
| hermes | `templates/config.yaml.j2` | `templates/hermes-config.yaml.j2` | `~/.hermes/config.yaml` (hermes runtime's expected name) |
| hermes | `templates/.env.j2` | `templates/hermes.env.j2` | `~/.hermes/.env` (hermes runtime's expected name) |
| openclaw | (no `clm-`-prefixed templates today) | unchanged | unchanged |

**Convention rule (new):** every source template under
`src/clawrium/platform/registry/<type>/templates/` MUST start with
`<type>-` or `<type>.`. The destination filename on the agent host is
whatever the agent's runtime expects (we don't dictate that).

**Validation step (verifies sync-to-destination):**

- New test asserts no template under any registry's `templates/` directory
  starts with `clm-`.
- New playbook smoke-test asserts the rendered destination file paths
  match the expected names listed above.

**No migration. No alias.** Existing installs carry stale dropin files
until the next `sync` (which will be re-run anyway since the whole CLI
change requires fleet reinstall).

### 11. wolf-i fleet audit (regression artifact)

Before any code is written:

1. Install every existing agent type on wolf-i:
   - zeroclaw
   - hermes
   - openclaw
2. Configure + start each (interactive — accept defaults).
3. Capture verbatim stdout/stderr of every read-only `clm` command into
   `.itx/435/audit-before.md`, plus one sample of each lifecycle action.
4. Remove the audit agents to leave wolf-i clean.

After the rewrite is complete:

1. Repeat the equivalent `clawctl` sweep against the same fleet.
2. Store in `.itx/435/audit-after.md`.
3. PR review compares the two files line by line. Any unintended
   regression in behavior or output structure blocks merge.

### 12. GUI / blog / version

- **GUI behaviour:** zero changes. The Python imports stay as imports.
  Only string changes: `clm` → `clawctl` in frontend copy, backend
  docstrings, "copy command" buttons.
- **Frontend source:** lives in this repo (confirmed). Exact source path
  is located during execution; built artifact at
  `src/clawrium/gui/frontend/_next/` is regenerated as part of the
  release pipeline.
- **Blog:** existing `website/blog/2026-05-23-introducing-clawrium.md`
  keeps `clm` for historical accuracy. New post announces the rename
  + kubectl-style UX. Title TBD at execution time.
- **CHANGELOG.md:** one section marked `BREAKING`. Lists binary rename,
  full command renames (per §5 table), `channel` extraction, template
  renames, `sync` semantics change.
- **Version:** unchanged in this issue. Separate follow-up issue handles
  the bump.

### 13. Open items resolved in this round

| # | Item | Resolution |
|---|---|---|
| 1 | `integration registry` purpose | Promoted to canonical CRUD entrypoint for ALL attachables (provider, channel, integration, skill, mcp). Pattern A. |
| 2 | `service start`/`stop`/`snapshot` semantics | Placeholders. Each prints `Not implemented: <command>` and exits 0, matching today's `clm snapshot` behavior. |
| 3 | Channel migration tool | None. Clean reinstall expected per breaking-change posture. |
| 4 | Frontend source location | In this repo. Exact path located during execution. |
| 5 | Output column padding | Option B — kubectl tabwriter style, fixed-width per row, min 3 spaces between columns. |

### 14. Open items still pending sign-off

None blocking. Plan ready for scaffold (`01_SCAFFOLD.md`) on approval.

---

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-20T03:40:46Z
**Model**: claude-opus-4-7

```prompt
change the cli from clm to clawctl and align the cli output format with kubectl format. make sure all the commands can be run using cli only and the gui wiring is using the same commaands. this issue is about doing a sweep of the cli surface and stnandardizing it across the board for a cleaner ux
```

**Output**: Created GitHub issue #435 covering (1) rename `clm` → `clawctl`, (2) kubectl-style verb-noun grammar + `-o yaml|json|wide` output, and (3) wiring the GUI through `clawctl` so CLI is the single source of truth.

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-23T00:00:00Z
**Model**: claude-opus-4-7

```prompt
https://github.com/ric03uec/clawrium/issues/435 need to plan this well. read the issue description and requirements first, build an understanding of the cli surface of clm, build an understanding of kubectl (docker etc) clis and then propose the diff and the plan to implement this. this issue MUST NOT make any changes to the core functionality, and is limited to improving the cli UX of clawrium world class. it's ok if there are a few changes here and there but they should be far and few. go plan. don't create any files till i approve the plan.

Iteration 1 (user direction):
1. No deprecation of clm — full replacement. Changelog mentions breaking change.
2. Every command needs a non-interactive option. Fail fast when stdin not TTY and required flag missing.
3. Standardize output to match kubectl. Provision a full agent on wolf-i to capture real outputs.
4. Revisit verbs and hierarchy. Domain-aligned.
5. GUI updated to use new commands; no GUI behaviour changes.
6. Map verbs to kubectl. One format only. No deprecation.
7. xclm system user kept as-is.
8. Zeroclaw template clm-env.conf should be zeroclaw-env.conf. All agents own their files.
9. apply out of scope. sync becomes canonical drift-to-zero flush with validate + restart.

Iteration 2 (user direction):
1. System-level commands move to clawctl service init|start|stop|status (added later) and clawctl service snapshot (placeholder). Remove clawctl ps. All remove → delete. All show/ps → describe. Provider, integration, host levels good. Add channel as a top-level noun. registry as common verb for supported types of a component (agent, host, provider, channel, skill, mcp placeholder).
2. Standardization rules look good.
3. Capture wolf-i audit before+after as regression artifact.
4. No --from-file for normal config — CLI flags only. Exception: file body input (memory, soul). Channel/Discord/Slack prompts collapse via clawctl channel.
5. Completion good. Keep host address nested. Host alias is multi-alias mgmt, not a rename. Host reset separate from delete. Skill/secret/memory single nouns.
6. Sync timeout 2 min default, flag overrides.
7. Template rename OK as long as destination has correct name; validate step required; no migration.
8. GUI talks to backend however it does today (imports).
9. No version bump; separate issue. Change hermes templates too.
10. Show output formats first.

Iteration 3 (user direction — final):
1. integration registry is NOT just the registry; it is the ONLY way to CRUD integrations. provider, channel, skill, integration all CRUD through registry. agent-specific operations are attach/detach only.
2. service start/stop/snapshot are placeholders with "not implemented" message.
3. Channel migration: no tool, clean reinstall.
4. Frontend source is in this repo.
5. Output padding: Option B (kubectl tabwriter, fixed-width, 3-space min gap).
```

**Output**: Wrote `.itx/435/00_PLAN.md` capturing the WHAT — scope, domain model (Pattern A attachables vs Pattern B targets), full command surface, BEFORE→AFTER command map, output format contract with samples, non-interactive contract, `clawctl channel` extraction, `sync` redefinition, template rename map, wolf-i audit plan, GUI/blog/version notes. No execution steps. No subtasks. Awaiting sign-off before `01_SCAFFOLD.md`.
