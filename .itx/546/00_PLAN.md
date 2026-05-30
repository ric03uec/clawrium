# Plan — Issue #546

**Title**: Ethos agent type + declarative fleet management (`clawctl apply`)
**Branch**: `feature/ethos`
**Status**: ✅ Implemented
**Date**: 2026-05-28 → 2026-05-30

---

## 1. Scope

Two interrelated features shipped together:

1. **Declarative fleet management** — `clawctl apply -f fleet.yaml`, `diff`, `delete -f`
2. **Ethos agent type** — first-class `ethos` entry in the clawrium agent registry, on par with hermes, zeroclaw, and openclaw

---

## 2. Declarative Fleet Management

### 2.1 Mental Model

```
fleet.yaml  (desired state)
    │
    ├── clawctl diff -f fleet.yaml     ← preview, touch nothing
    ├── clawctl apply -f fleet.yaml    ← reconcile actual → desired
    └── clawctl delete -f fleet.yaml   ← teardown in reverse order
                    ▼
         Reconciler (differ + executor)
                    │
        ┌───────────▼────────────────────────┐
        │  hosts.json, providers.json, …     │  ← actual state
        └────────────────────────────────────┘
                    │
                    ▼
         ChangeSet → execute in dependency order
```

### 2.2 Resource Schema (Kubernetes envelope)

```yaml
apiVersion: clawrium.io/v1
kind: Host | Provider | Agent   # Channel, Integration also supported
metadata:
  name: <name>
  labels:
    key: value
spec: { ... }
```

#### Supported Kinds

| Kind | Key spec fields |
|---|---|
| `Host` | `hostname`, `user`, `port`, `bootstrap` |
| `Provider` | `type`, `config.defaultModel`, `credentials.apiKey.secretRef` |
| `Agent` | `type`, `host`, `provider`, `channels`, `skills`, `integrations`, `config`, `lifecycle` |
| `Channel` | `type`, `credentials`, `config` |
| `Integration` | `type`, `credentials` |

#### Example fleet.yaml (ethos)

```yaml
---
apiVersion: clawrium.io/v1
kind: Host
metadata:
  name: ethos-homelab
spec:
  hostname: 192.168.1.47
  user: xclm
  port: 22
  bootstrap: true

---
apiVersion: clawrium.io/v1
kind: Provider
metadata:
  name: ethos-openrouter
spec:
  type: openrouter
  config:
    defaultModel: moonshotai/kimi-k2.6
  credentials:
    apiKey:
      secretRef: providers/ethos-openrouter/apiKey

---
apiVersion: clawrium.io/v1
kind: Agent
metadata:
  name: kevin
spec:
  type: ethos
  version: "0.4.3"
  host: ethos-homelab
  provider: ethos-openrouter
  channels: []
  skills: []
  integrations: []
  config:
    model: moonshotai/kimi-k2.6
  lifecycle:
    autoStart: true
    autoRestart: false
```

### 2.3 Code Layout (all new files)

```
src/clawrium/core/manifest/
├── schema.py       # Pydantic models for all resource kinds
├── parser.py       # YAML → ManifestDocument (multi-doc)
├── validator.py    # ref resolution, secret preflight
├── state.py        # ActualState reader from hosts.json
├── differ.py       # ManifestDocument + ActualState → ChangeSet
└── executor.py     # ChangeSet → core.* API calls (ordered)

src/clawrium/cli/clawctl/
├── apply.py        # clawctl apply -f
├── diff.py         # clawctl diff -f
└── delete_file.py  # clawctl delete -f (separate from agent delete)

tests/
├── test_manifest_apply.py
└── test_registry_ethos.py
```

### 2.4 Execution Order (apply)

```
1. Hosts       → create + bootstrap if needed
2. Providers   → create or update
3. Agents      → install (Phase 1)
4. Agents      → configure (Phase 2 — provider attach + onboarding)
5. Agents      → start (if lifecycle.autoStart: true)
```

### 2.5 Secret Preflight

Before executing, the reconciler checks all `secretRef` paths exist. On failure:

```
Error: missing secrets required by fleet.yaml:
  providers/ethos-openrouter/apiKey

Set with:
  echo "sk-or-v1-..." | clawctl provider registry create ethos-openrouter \
    --type openrouter --model <model> --api-key-stdin
```

> **Note**: hint uses `clawctl provider registry create`, NOT the non-existent `clawctl secret set`.

### 2.6 ChangeSet

```python
@dataclass
class ChangeSet:
    creates:  list[ResourceOp]
    updates:  list[ResourceOp]
    attaches: list[AttachOp]
    detaches: list[AttachOp]
    starts:   list[str]
    restarts: list[str]
    deletes:  list[ResourceOp]   # delete -f only
    noops:    list[ResourceOp]
```

### 2.7 Idempotency

Re-running `apply` on an unchanged manifest produces all `unchanged`. The differ compares spec fields; credentials are never re-compared (write-only via SecretsResolver).

### 2.8 Implementation Status

| Phase | Deliverable | Status |
|---|---|---|
| 1 | `schema.py`, `parser.py`, `validator.py` | ✅ Done |
| 2 | `state.py` — ActualState reader | ✅ Done |
| 3 | `differ.py` — ChangeSet builder | ✅ Done |
| 4 | `diff.py` — `clawctl diff -f` | ✅ Done |
| 5 | `executor.py`, `apply.py` — `clawctl apply -f` | ✅ Done |
| 6 | `delete_file.py` — `clawctl delete -f` | ✅ Done (basic teardown; full remote cleanup is #547) |
| 7 | Round-trip export | ⏳ Deferred |
| 8 | Directory apply (`-k ./fleet/`) | ⏳ Deferred |

---

## 3. Ethos Agent Type

### 3.1 Architecture

```
ethos run-all  (single systemd unit: ethos-<agent_name>.service)
  ├── ethos gateway  pid XXXXX   → messaging platforms (Discord/Slack bots)
  │     health: http://127.0.0.1:3002/healthz
  └── ethos serve    pid XXXXX   → web UI + OpenAI-compat API
        ├── http://127.0.0.1:3000  — web UI (SPA), /v1/*, /healthz
        └── ws://localhost:3001    — ACP WebSocket

run-all supervisor health: http://127.0.0.1:3003/healthz
```

> **Key insight**: `ethos gateway` is the **messaging platform gateway** (Discord/Slack adapters),
> NOT the OpenAI-compatible inference API. `adapters:[]` in healthz means no messaging platform
> is configured — this is expected and does NOT indicate a broken install. The inference API
> lives in `ethos serve` on port 3000.

### 3.2 Port Architecture

| Port | Component | Binding | Config field | Purpose |
|---|---|---|---|---|
| 3000 | `ethos serve` | `127.0.0.1` | `config.gateway.port` | Web UI, `/v1/*`, `/healthz` |
| 3001 | `ethos serve` | `localhost` | — | ACP WebSocket (internal) |
| 3002 | `ethos gateway` | `127.0.0.1` | — | Messaging gateway health |
| 3003 | `run-all` | `127.0.0.1` | — | Supervisor health (readiness probe) |
| 43000–44999 | `ethos serve` | `127.0.0.1` | `config.gateway.internal_port` | `ETHOS_GATEWAY_PORT` (per-instance) |

`config.gateway.port = 3000` always (hardcoded by ethos upstream). The `web_ui` resolver uses `port_field: gateway.port` to tunnel to port 3000 for both `clawctl agent open` and `clawctl agent chat`.

### 3.3 Token Architecture

Three distinct credentials:

| Token | Secret key | Format | Purpose |
|---|---|---|---|
| `ETHOS_GATEWAY_API_KEY` | `<host>:ethos:<agent>` | 64-char hex | Internal gateway bearer (written to `.env`) |
| `ETHOS_CHAT_TOKEN` | `<host>:ethos:<agent>` | `sk-ethos-<64hex>` | `/v1/` API bearer for `clawctl agent chat` |
| `web-token` | Remote file `~/.ethos/web-token` | raw hex | Dashboard auth via `/auth/exchange?t=TOKEN` |

- `ETHOS_GATEWAY_API_KEY` is generated at install and never rotates.
- `ETHOS_CHAT_TOKEN` is created post-configure via SSH `ethos api-key create --name clawctl`.
- `web-token` is generated by ethos at runtime; read on-demand over SSH for `clawctl agent open`.

### 3.4 Registry Files

```
src/clawrium/platform/registry/ethos/
├── manifest.yaml
├── playbooks/
│   ├── install.yaml        # npm install -g @ethosagent/cli, create agent user, drop disabled unit
│   ├── configure.yaml      # render .env + config.yaml + personality files, restart unit
│   ├── start.yaml          # re-render unit (upgrade-safe), start, health check
│   ├── stop.yaml           # stop + verify process gone; preserve ~/.ethos/
│   ├── remove.yaml         # stop, remove ~/.ethos/, npm uninstall (if last agent), userdel
│   ├── exec.yaml           # passthrough: run ethos CLI as agent user (dynamic binary path)
│   ├── skills_apply.yaml   # reconcile ~/.ethos/skills/clawrium/
│   ├── memory_{read,write,info,delete}.yaml  # ~/.ethos/personalities/default/
└── templates/
    ├── ethos.env.j2                    # ~/.ethos/.env (provider key + gateway key + channels)
    ├── ethos-config.yaml.j2            # ~/.ethos/config.yaml — MUST include apiKey field
    ├── ethos-soul.md.j2                # SOUL.md
    ├── ethos-toolset.yaml.j2           # toolset.yaml
    ├── ethos-personality-config.yaml.j2
    └── verify_ethos.js                 # runs ethos doctor
```

### 3.5 Key Implementation Decisions (with rationale)

#### D1 — `config.gateway.port = 3000` (not 43000-44999)

**Original plan**: gateway port in 43000-44999 range (per-instance).  
**Actual**: port 3000 is hardcoded by ethos upstream (not configurable). Clawrium stores it as `config.gateway.port = 3000` so the `web_ui` resolver (`port_field: gateway.port`) tunnels to the correct port for both `agent open` and `agent chat`. The per-instance `ETHOS_GATEWAY_PORT` (43000-44999) is stored as `config.gateway.internal_port` and rendered in `.env`, but clawrium never connects to it directly.

**Why this matters**: An early implementation stored 43000-44999 as `gateway.port`. The `configure_agent` lifecycle code had a range-check `43000 <= port <= 44999` that silently re-picked the wrong port when it saw 3000. Both the install and lifecycle code were fixed to use 3000.

#### D2 — Health check on port 3003 (not 3000), timeout 90s (not 30s)

**Original plan**: poll `GET /health` on gateway port, 30s timeout.  
**Actual**: `run-all` supervisor exposes its own readiness signal at `http://127.0.0.1:3003/healthz`. Port 3000 (`ethos serve`) starts immediately (serves dashboard HTML) but is not a reliable readiness signal — the supervisor port 3003 becomes available only when all children are ready. Boot time is 30-60s, so timeout is 90s.

Health check also gates on `systemctl is-active` before attempting HTTP, and tries `/healthz → /health → /v1/models` on port 3003 as fallbacks.

#### D3 — `exec.yaml` uses dynamic binary path

**Original plan**: hardcode `/usr/local/bin/ethos`.  
**Actual**: `npm prefix -g` resolves the real binary path (can be `/opt/clawrium-node24/bin/ethos` on NodeSource installs). `exec.yaml` mirrors `install.yaml`'s dynamic path resolution.

#### D4 — `start.yaml` re-renders the systemd unit

**Parity with hermes**: `start.yaml` re-renders the full unit file on every start, picking up any `ExecStart` changes (e.g., binary path shift after a Node.js upgrade) without requiring a full reinstall.

#### D5 — Identity stage: configure-playbook-owned

**Original plan**: identity stage `auto_skip: true` (skip silently).  
**Actual**: `auto_skip: false` — identity IS required (personality files must be provisioned). But unlike openclaw (where identity requires interactive prompts), ethos identity is fully handled by `configure.yaml` (renders SOUL.md + toolset.yaml + personality config.yaml). In `lifecycle.py`, a `_CONFIGURE_PLAYBOOK_OWNED` set marks `("ethos", "identity")` as completable automatically, bypassing the `_NO_DECLARATIVE_SURFACE_YET` block.

#### D6 — `ethos-config.yaml.j2` must include `apiKey`

The `apiKey: ${secrets:providers/<type>/apiKey}` field is **required** in `config.yaml`. Without it, ethos does not load the inference provider adapter (even if `OPENROUTER_API_KEY` is in `.env`). Ethos uses `config.yaml`'s apiKey field to register the adapter at startup.

#### D7 — Chat uses `ETHOS_CHAT_TOKEN`, not `ETHOS_GATEWAY_API_KEY`

`ETHOS_GATEWAY_API_KEY` (64-char hex) is for the internal gateway bearer (`/rpc/*`). The `/v1/` OpenAI-compatible API requires a separate `sk-ethos-...` key created via `ethos api-key create`. This token is auto-created post-configure and stored as `ETHOS_CHAT_TOKEN` in secrets.

#### D8 — `ethos gateway adapters:[]` is expected

The `ethos gateway` process handles messaging platform adapters (Discord/Slack bots). `adapters:[]` in `/healthz` means no messaging platform is configured — this is the normal state for a fresh install. It does NOT indicate a broken LLM inference setup. `healthz` returning `"status":"degraded"` with no adapters is expected and should not block `clawctl agent start`.

### 3.6 Agent Type Comparison

| Feature | ethos | hermes | zeroclaw | openclaw |
|---|---|---|---|---|
| **Language** | TypeScript (Node.js 24+) | Python 3.11+ | Rust (statically linked) | Node.js |
| **Install** | `npm install -g @ethosagent/cli` | bash installer from GitHub | prebuilt binary (sha256) | npm |
| **Systemd units** | 1 (`run-all` supervisor) | 2 (gateway + dashboard) | 1 | 1 |
| **Chat protocol** | OpenAI HTTP `/v1/chat/completions` | OpenAI HTTP | ZeroClaw WebSocket | WebSocket |
| **Chat auth token** | `ETHOS_CHAT_TOKEN` (`sk-ethos-...`) | `API_SERVER_KEY` | gateway bearer (rotates) | session |
| **Web UI** | built-in (port 3000, same process) | separate dashboard unit (45000-46999) | built-in (gateway port) | none |
| **Web UI auth** | `web-token` via `/auth/exchange?t=` | none | none | — |
| **`gateway.port`** | 3000 (fixed upstream) | — | per-instance (40000-41999) | per-instance (40000-41999) |
| **Providers** | OpenRouter, Anthropic, OpenAI | OpenRouter, Anthropic, OpenAI | any OpenAI-compat URL | OpenAI-compat |
| **Channels** | Discord, Slack, Telegram | Discord, Slack | Discord | web, WhatsApp, Slack, Discord, Telegram |
| **Memory path** | `~/.ethos/personalities/default/` | `~/.hermes/memories/` | `~/.zeroclaw/workspace/` | `~/.openclaw/workspace/memory/` |
| **Skills path** | `~/.ethos/skills/clawrium/` | `~/.hermes/skills/clawrium/` | `~/.zeroclaw/workspace/skills/` | `~/.openclaw/skills/` |
| **Identity stage** | configure-playbook-owned | `auto_skip: true` | `auto_skip: true` | required (interactive) |
| **Health check** | SSH → `3003/healthz`, 90s | systemd `ActiveState` | systemd `ActiveState` | systemd `ActiveState` |
| **`restart.yaml`** | not needed (no bearer rotation) | not needed | yes (re-pairs bearer) | not needed |
| **Min RAM** | 2 GB | 2 GB | 512 MB (Pi 2) | 2 GB |
| **ARM support** | no | no | yes (armv7l, aarch64) | no |

### 3.7 Implementation Status

| Area | Status | Notes |
|---|---|---|
| `manifest.yaml` | ✅ Done | `port_field: gateway.port`, identity `required: true` |
| `install.yaml` | ✅ Done | Node.js 24 via NodeSource, service account user, unit dropped disabled |
| `configure.yaml` | ✅ Done | Renders `.env` + `config.yaml` + personality files; pipelining+keepalives |
| `start.yaml` | ✅ Done | Re-renders unit (upgrade-safe), 3s settle, fail-loud on inactive |
| `stop.yaml` | ✅ Done | Stops + verifies process gone via pgrep |
| `remove.yaml` | ✅ Done | Full teardown: unit, `~/.ethos/`, npm pkg, agent user |
| `exec.yaml` | ✅ Done | Dynamic `npm prefix -g` binary resolution |
| `skills_apply.yaml` | ✅ Done | Idempotent reconcile under `~/.ethos/skills/clawrium/` |
| `memory_*.yaml` | ✅ Done | Targets `~/.ethos/personalities/default/` |
| `chat_ethos.py` | ✅ Done | SSE streaming, 401 reconnect, `MAX_HISTORY_TURNS = 100` |
| `install.py` ethos block | ✅ Done | `gateway.port = 3000`, `internal_port = 43000-44999` |
| `lifecycle.py` ethos block | ✅ Done | Configure-playbook-owned identity, range check fixed, 90s health |
| `open.py` ethos block | ✅ Done | Reads `web-token` from remote host via SSH, `/auth/exchange?t=` |
| `registry.py` validator | ✅ Done | `port_field` now required (not optional alongside `default_port`) |
| Tests | ✅ Done | `test_registry_ethos.py`, `test_manifest_apply.py` |
| README | ✅ Done | `platform/registry/ethos/README.md` with full comparison table |

### 3.8 Known Gaps

| Gap | Severity | Notes |
|---|---|---|
| `clawctl delete -f fleet.yaml` does not remove remote Linux user/unit | High | Manual cleanup required; tracked as #547 |
| `clawctl agent open` doesn't re-auth on web-token rotation | Low | Token rotates on first browser use; CLI must re-read on 401 |
| `ethos serve` `/healthz` degraded status with `adapters:[]` logged as warning | Low | Expected state — informational only |
| No `restart.yaml` | Low | `stop` + `start` is the documented path |

---

## 4. Bugs Fixed During Implementation

| Bug | Root cause | Fix |
|---|---|---|
| `exec.yaml` wrong binary path | Hardcoded `/usr/local/bin/ethos`; npm installs elsewhere | Dynamic `npm prefix -g` resolution |
| Health check wrong port (3001) | Comment said "ACP_PORT_DEFAULT" | Corrected to 3003 (run-all supervisor) |
| Health check timeout (30s) | ethos `run-all` boots in 30-60s | Bumped to 90s |
| `start.yaml` no unit re-render | Stale unit on binary path change | Re-renders on every start (hermes parity) |
| `config.yaml` apiKey removed | Commented as "not needed" | REQUIRED — ethos needs it to load provider adapter |
| `gateway.port = 44410` after install | `configure_agent` range-check `43000 <= port <= 44999` rejected 3000 and picked 44410 | Range check replaced with `0 < port <= 65535` |
| `gateway.port` overwritten by configure | `lifecycle.py` had old range validation that silently repicked wrong port | Fixed validator + all three write sites in install.py |
| Identity stage error in `apply` | `_NO_DECLARATIVE_SURFACE_YET = {"identity"}` blocked ethos | Added `_CONFIGURE_PLAYBOOK_OWNED = {("ethos", "identity")}` |
| `set_instance_secret` not found | Missing from lifecycle.py imports | Added to import block |
| Python built-in `open` shadowed | `open.py` defines function named `open` | `import builtins; builtins.open(...)` |
| `ETHOS_CHAT_TOKEN` not auto-created | Ansible `set_fact` doesn't persist to artifact dir | Moved to Python post-configure SSH call |
| Ansible timeout (12s privilege escalation) | SSH connections dropping mid-playbook | Pipelining + `ServerAliveInterval=30` + `ANSIBLE_BECOME_TIMEOUT=120` |
| `IncompleteInstallationError` loop | Failed installs left `status: installing`; differ skipped | Differ now retries; executor auto-cleans on retry |
| `OnboardingNotFoundError` in configure | Fresh agent had no onboarding record | Executor initializes onboarding before `sync_agent` |
