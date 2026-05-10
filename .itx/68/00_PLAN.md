# Issue #68 — Implementation Plan

User can deploy and manage `hermes-agent` (Nous Research) via `clm`, mirroring the existing `openclaw` shape in the registry.

Source of truth: GitHub issue #68 plus this file. Subsequent reconciliation comments on the issue may amend phase scope.

## Phasing strategy

Five independent PRs. Issue stays open until Phase 5. Phase 1 (installation) is a strict prerequisite; phases 2–5 may be reordered by reviewers if scope demands it.

| Phase | Branch | PR closes |
|-------|--------|-----------|
| 1 | `issue-68-phase-1-installation` | manifest + `install.yaml` + `start`/`stop`/`remove` playbooks (lifecycle primitives, service unit dropped but **disabled and not started**) |
| 2 | `issue-68-phase-2-configuration` | `configure.yaml` writes `~/.hermes/.env` with LLM provider + `API_SERVER` gateway; auto-starts the service via restart handler |
| 3 | `issue-68-phase-3-memory-generic` | generalize `core/memory.py` + `cli/memory.py`; manifest-driven workspace path; hermes `memory_*.yaml` playbooks targeting markdown backend |
| 4 | `issue-68-phase-4-onboarding` | manifest `onboarding.stages` + minimal templates |
| 5 | `issue-68-phase-5-docs` | `docs/agent-support/hermes.md`, index, README |

## End-to-end flow

The diagram below shows the user-facing operations and the system state after each step. Phase numbers in parentheses indicate which PR delivers that step.

```
                    ┌─────────────────────────────────────────────┐
                    │ clm agent install --type hermes -h H -n N   │  (Phase 1)
                    └──────────────────────┬──────────────────────┘
                                           ▼
                    Preflight: ripgrep + ffmpeg installed system-wide?
                                ──── no ──> ABORT (clear remediation msg)
                                           │ yes
                                           ▼
                    Already installed at <TAG>?  ── yes ──> skip binary install
                                           │ no              (unless --force)
                                           ▼
                    get_url + sha256-verify install.sh @ <TAG>
                    Run as agent user:
                      bash install.sh --skip-setup --branch <TAG> \
                        --hermes-home ~/.hermes --dir ~/.hermes/code
                                           ▼
                    Create ~/.hermes/         (mode 0700, owner=N)
                    Create ~/.hermes/.env     (empty,  mode 0600, force=no)
                    Create ~/.hermes/memories/(mode 0700, owner=N)
                    Drop systemd unit hermes-N.service (DISABLED, NOT started)
                                           ▼
            ╔══════════════════════════════════════════════════════╗
            ║ STATE: binary present, no provider, service inert.   ║
            ║        ~/.hermes/.env empty. Memory dir empty.       ║
            ╚══════════════════════════════════════════════════════╝
                                           │
                                           ▼
                    ┌─────────────────────────────────────────────┐
                    │ clm agent configure N \                     │  (Phase 2)
                    │   --provider openrouter --model <m> \       │
                    │   --api-key <KEY>                           │
                    └──────────────────────┬──────────────────────┘
                                           ▼
                    Generate API_SERVER_KEY once (random hex32);
                    persist in clm hosts.json (idempotent on reconfig)
                                           ▼
                    Write ~/.hermes/.env from .env.j2:
                      HERMES_INFERENCE_PROVIDER=openrouter
                      HERMES_INFERENCE_MODEL=<m>
                      OPENROUTER_API_KEY=<KEY>
                      API_SERVER_ENABLED=1
                      API_SERVER_HOST=127.0.0.1
                      API_SERVER_PORT=8642
                      API_SERVER_KEY=<persisted token>
                                           ▼
                    Verify provider credential present (lineinfile check_mode)
                                           ▼
                    Enable + start hermes-N.service (restart handler)
                                           ▼
                    Probe http://127.0.0.1:8642/health  ── retries 10/3s
                                           ▼
            ╔══════════════════════════════════════════════════════╗
            ║ STATE: hermes daemon running under systemd.          ║
            ║        Local OpenAI-compatible API at 127.0.0.1:8642 ║
            ║        (POST /v1/chat/completions, GET /v1/models).  ║
            ║        No external messaging gateways enabled.       ║
            ║        clm ps shows agent N as healthy.              ║
            ╚══════════════════════════════════════════════════════╝
                                           │
            ┌──────────────────────────────┼──────────────────────────────┐
            │                              │                              │
            ▼                              ▼                              ▼
  ┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
  │ clm agent start N│          │ clm agent stop N │          │ clm agent remove │
  │     (Phase 1)    │          │     (Phase 1)    │          │  N  (Phase 1)    │
  └────────┬─────────┘          └────────┬─────────┘          └────────┬─────────┘
           ▼                             ▼                             ▼
  systemctl start;              systemctl stop+disable;       systemctl stop;
  re-render unit;               preserve ~/.hermes/           rm unit;
  wait /health 200              and ~/.hermes/memories/       rm ~/.hermes/;
                                                              rm ~/.local/bin/hermes;
                                                              userdel N

                                           │
                                           ▼  (orthogonal to lifecycle)
                    ┌─────────────────────────────────────────────┐
                    │ clm agent N memory show|read|write|         │  (Phase 3)
                    │                  edit|delete [<file>]       │
                    └──────────────────────┬──────────────────────┘
                                           ▼
                    Resolve agent type from hosts.json (= "hermes")
                                           ▼
                    Manifest declares features.memory: true?
                                ──── no ──> friendly error
                                            "memory not supported for type 'X'"
                                           │ yes
                                           ▼
                    Look up manifest.workspace.memory_path:
                      hermes:    ~/.hermes/memories/
                      openclaw:  ~/.openclaw/workspace/memory/
                                           ▼
                    Dispatch memory_<op>.yaml from the agent's
                    registry dir (each claw ships its own playbooks):

  show:   list *.md in memory_path
            hermes  → MEMORY.md, USER.md (fixed two-file model)
            openclaw → YYYY-MM-DD.md (daily files)
  read:   slurp <file>; print to stdout
  write:  validate char limit (hermes only: 2200 MEMORY / 1375 USER);
            atomic write (write → fsync → rename) to avoid races
            with the running daemon
  edit:   open <file> in $EDITOR; on save, atomic write
  delete: confirm; rm <file>

            ╔══════════════════════════════════════════════════════╗
            ║ STATE: memory CRUD works for both hermes and         ║
            ║        openclaw. Identical CLI surface.              ║
            ║        Holographic / Honcho / Mem0 backends still    ║
            ║        invisible to clm — tracked as follow-up.      ║
            ╚══════════════════════════════════════════════════════╝
```

## Confirmed facts (from upstream source)

**Installer** (`scripts/install.sh`):

- Non-interactive flag: `--skip-setup`.
- Version pinning: `--branch <git-tag>` (git-clone install; no `--version`).
- Data dir: `--hermes-home <path>` (or `HERMES_HOME` env).
- Symlink: root → `/usr/local/bin/hermes`; non-root → `~/.local/bin/hermes`.

**Local-only boot** (`gateway/platforms/api_server.py`, `gateway/config.py:1373-1397`):

- `API_SERVER_ENABLED=1` + `API_SERVER_KEY=<token>` in `~/.hermes/.env` registers the OpenAI-compatible HTTP server platform.
- Default bind: `127.0.0.1:8642`. Hermes refuses non-loopback bind without `API_SERVER_KEY`.
- Endpoints: `GET /health`, `GET /health/detailed`, `POST /v1/chat/completions`, `GET /v1/models`, `POST /v1/responses`, `POST /v1/runs`.
- No Discord/Slack/Telegram/etc. needed — `hermes gateway start` runs the api_server platform alone.

**Memory** (`website/docs/user-guide/features/memory.md`, cli-config example):

- Default backend stores plain markdown: `~/.hermes/memories/MEMORY.md` (agent notes, ≤2200 chars), `~/.hermes/memories/USER.md` (user profile, ≤1375 chars).
- `~/.hermes/state.db` holds session/transcript history — explicitly NOT memory; out of scope for `memory` CLI.
- Identity files (`SOUL.md`, `AGENTS.md`) are explicitly excluded from memory by hermes itself; managed by configure/onboarding.

**Env vars** (Phase 1–5 defaults only):

- Provider keys: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.
- Provider/model selection: `HERMES_INFERENCE_PROVIDER`, `HERMES_INFERENCE_MODEL`.
- Config dir override: `HERMES_HOME` (default `~/.hermes`).

## Phase 1 — Installation

**New files**

- `src/clawrium/platform/registry/hermes/manifest.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/install.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/start.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/stop.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/remove.yaml`
- `tests/test_registry_hermes.py`

**Manifest skeleton**

```yaml
agent:
  type: hermes
  description: "Nous Research self-improving AI agent (Python)"

secrets:
  required: []
  optional:
    - key: OPENROUTER_API_KEY
      description: "OpenRouter API key (200+ models)"
    - key: ANTHROPIC_API_KEY
      description: "Anthropic API key"
    - key: OPENAI_API_KEY
      description: "OpenAI API key"

# Workspace + features fields consumed by Phase 3 memory dispatcher.
# Declared in Phase 1 so the manifest schema is stable from the start.
workspace:
  memory_path: "~/.hermes/memories"

features:
  memory: true

platforms:
  - version: "<TAG>"
    os: ubuntu
    os_version: "24.04"
    arch: x86_64
    sha256: "<INSTALLER_SCRIPT_SHA256>"
    requirements:
      min_memory_mb: 2048
      gpu_required: false
      dependencies:
        python: ">=3.11"
        ripgrep: "*"
        ffmpeg: "*"
  - version: "<TAG>"
    os: ubuntu
    os_version: "22.04"
    arch: x86_64
    sha256: "<INSTALLER_SCRIPT_SHA256>"
    requirements:
      min_memory_mb: 2048
      gpu_required: false
      dependencies:
        python: ">=3.11"
        ripgrep: "*"
        ffmpeg: "*"
```

`<TAG>` and `<INSTALLER_SCRIPT_SHA256>` pinned in the actual PR — `<TAG>` from latest release on `nousresearch/hermes-agent`; `<SHA256>` computed from the installer at that tag.

**`install.yaml`** — direct port of openclaw's `install.yaml` post-#163 (the version-aware skip + `--force` pattern is canonical). Flow:

1. Normalize `hermes_target_version` (strip leading `v`).
2. Create agent user.
3. Preflight: assert `ripgrep` and `ffmpeg` installed system-wide; fail with clear remediation if missing.
4. `which hermes` → `hermes --version` → compare to target → set `hermes_already_installed` skip-flag with `force_install` override (verbatim mirror of openclaw `install.yaml:31-65`).
5. `get_url` `https://raw.githubusercontent.com/NousResearch/hermes-agent/{{ hermes_target_version }}/scripts/install.sh` with `checksum: "sha256:{{ installer_checksum }}"` (required, no `default(omit)`).
6. Run installer non-interactively as agent user:
   ```
   bash hermes-install.sh --skip-setup --branch {{ hermes_target_version }} \
     --hermes-home /home/{{ agent_name }}/.hermes \
     --dir /home/{{ agent_name }}/.hermes/code
   ```
   `creates: /home/{{ agent_name }}/.local/bin/hermes`.
7. Clean up installer script.
8. Create `~/.hermes/` (0700), `~/.hermes/.env` (empty, 0600, `force: no`), `~/.hermes/memories/` (0700) — all owned by agent user.
9. Drop systemd unit `hermes-{{ agent_name }}.service`:
   ```
   ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway start
   EnvironmentFile=/home/{{ agent_name }}/.hermes/.env
   WorkingDirectory=/home/{{ agent_name }}/.hermes
   ```
   **Disabled and not started.** Configure (Phase 2) starts it.

**`start.yaml`/`stop.yaml`/`remove.yaml`** modeled on openclaw post-#163:

- `start.yaml`: re-render systemd unit (idempotent), `systemctl start`, wait for `ActiveState == active`, verify `pgrep -u {{ agent_name }} hermes`, probe `/health` if `.env` configured.
- `stop.yaml`: stop + disable; preserve `~/.hermes/`.
- `remove.yaml`: stop, remove unit file, remove `~/.hermes/`, remove `~/.local/bin/hermes` symlink, remove agent user.

**Tests (Phase 1)**

- `test_hermes_listed_in_registry` — `list_claws()` includes `"hermes"`.
- `test_hermes_manifest_validates` — `load_claw_manifest("hermes")` parses + validates.
- `test_hermes_manifest_has_installer_checksum` — every platform entry has non-empty `sha256`.
- `test_hermes_manifest_declares_memory_workspace` — `workspace.memory_path` and `features.memory: true` present (Phase 3 prerequisite).

**Phase 1 acceptance**

- [ ] `make test` green
- [ ] `make lint` green
- [ ] ATX review > 3/5 with no blocking issues
- [ ] Installer SHA256 verified against tagged commit (recorded in PR body)
- [ ] Install succeeds end-to-end on clean Ubuntu 24.04 with `ripgrep` + `ffmpeg` present
- [ ] Install fails with clear remediation when `ripgrep` or `ffmpeg` missing
- [ ] Re-running install on an already-installed host skips binary install
- [ ] `--force` re-runs the installer
- [ ] After install, `clm agent start N` brings the unit up but service immediately exits since no provider configured — documented expected behavior; Phase 2 fixes it

## Phase 2 — Configuration (LLM + api_server gateway)

**New files**

- `src/clawrium/platform/registry/hermes/playbooks/configure.yaml`
- `src/clawrium/platform/registry/hermes/templates/.env.j2`

**Modified**

- `src/clawrium/core/install.py` — generate and persist `API_SERVER_KEY` per agent (mirroring openclaw gateway-token persistence at `install.py:577-650`).

**`configure.yaml`** writes `~/.hermes/.env` from `templates/.env.j2`:

```
HERMES_INFERENCE_PROVIDER={{ config.provider.type }}
HERMES_INFERENCE_MODEL={{ config.provider.default_model }}
{% if config.provider.type == 'openrouter' %}
OPENROUTER_API_KEY={{ provider_api_key }}
{% elif config.provider.type == 'anthropic' %}
ANTHROPIC_API_KEY={{ provider_api_key }}
{% elif config.provider.type == 'openai' %}
OPENAI_API_KEY={{ provider_api_key }}
{% endif %}
API_SERVER_ENABLED=1
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_KEY={{ api_server_key }}
```

Per-provider `lineinfile check_mode: true` verification block (mirrors openclaw `configure.yaml:186-291`). After `.env` write, restart handler enables + starts the service. Probe `http://127.0.0.1:8642/health` to confirm running.

**Idempotency**: `API_SERVER_KEY` generated once on first configure and stored in clm `hosts.json`; subsequent reconfigures reuse the same value. Mirrors openclaw gateway-token handling.

**Out of scope (deferred follow-ups)**: messaging gateway pairing (Discord/Slack/Telegram/WhatsApp/Signal/email/Teams/Google Chat), MCP server registration, hermes memory backend selection (`memory.provider`), session reset tuning.

## Phase 3 — Generalize Memory Module Across Claw Types

**Why**: `core/memory.py:1` docstring + `_resolve_openclaw_agent` filter at `core/memory.py:122-169` hard-code openclaw. Without generalization, `clm agent <hermes-instance> memory show` returns the misleading `"openclaw agent '<x>' not found"` error.

**Approach** (default-backend only — markdown files):

1. Generalize `core/memory.py`:
   - Drive workspace path from `manifest.workspace.memory_path` instead of hard-coded `/home/<agent>/.openclaw/workspace`.
   - Rename `_resolve_openclaw_agent` → `_resolve_agent_with_memory`. Filter agents by `manifest.features.memory == true`, not by `record.get("type") == "openclaw"`.
   - Dispatch `memory_<op>` playbooks from the agent's registry dir, not openclaw's specifically.

2. Generalize `cli/memory.py`:
   - When invoked against a claw type whose manifest lacks `features.memory: true`, emit `"memory operations not supported for agent type '<type>'"` and exit non-zero.

3. Update `core/registry.py`:
   - Add optional `workspace.memory_path: str` and `features.memory: bool` to `AgentManifest` TypedDict.
   - Backward-compatible: existing zeroclaw manifest (no memory) continues to validate.

4. Update `openclaw/manifest.yaml`:
   - Add `workspace.memory_path: "~/.openclaw/workspace/memory"` and `features.memory: true`.
   - Behavior unchanged — paths match current hard-coded values.

5. New hermes playbooks:
   - `src/clawrium/platform/registry/hermes/playbooks/memory_info.yaml`
   - `src/clawrium/platform/registry/hermes/playbooks/memory_read.yaml`
   - `src/clawrium/platform/registry/hermes/playbooks/memory_write.yaml`
   - `src/clawrium/platform/registry/hermes/playbooks/memory_delete.yaml`
   - Direct port of openclaw equivalents, targeting `~/.hermes/memories/`.
   - `memory_write.yaml` validates character limit by file (`MEMORY.md` ≤2200, `USER.md` ≤1375); other filenames reject with "hermes memory accepts only MEMORY.md and USER.md".

**Behavioral guarantee**: existing openclaw memory CLI behavior is byte-for-byte identical. Same playbook invocations, same workspace paths. Only the dispatch logic and manifest schema change.

**Tests (Phase 3)**

- `tests/test_core_memory.py`:
  - existing openclaw cases continue to pass.
  - new: `test_memory_show_hermes_lists_memory_user_files`.
  - new: `test_memory_write_hermes_rejects_oversize_user_md`.
  - new: `test_memory_show_unsupported_type_friendly_error` (e.g. against zeroclaw).
- `tests/test_registry.py`:
  - `test_manifest_accepts_workspace_and_features_fields`.
  - `test_manifest_workspace_optional_for_legacy_types` (zeroclaw still validates).

## Phase 4 — Onboarding metadata

Fill `manifest.yaml::onboarding.stages`:

- `providers` — required, `provider_select` + `provider_test`.
- `identity` — `auto_skip: true` (no SOUL.md analogue managed by clm in this iteration).
- `channels` — default `cli` (the api_server platform is the local-CLI-equivalent endpoint).
- `validate` — `hermes --version` + `~/.hermes/.env` exists + `/health` returns 200.

Templates land under `src/clawrium/platform/registry/hermes/templates/`.

## Phase 5 — Docs

- `docs/agent-support/hermes.md` — capability matrix, install/configure walkthrough, local-only API usage example (`curl http://127.0.0.1:8642/v1/chat/completions`).
- `docs/agent-support/index.md` — add hermes row + Quick Comparison column; status `🚧 In Development`.
- README mention if Quickstart lists claw types.
- `docs/agent-support/memory.md` (new) — document the manifest-driven memory model now that it spans claw types.

## Workspace layout (per-host)

```
/home/<agent_name>/.hermes/
├── code/                # installer-managed git checkout of hermes-agent
├── .env                 # provider keys + API_SERVER_*  (mode 0600)
├── SOUL.md              # identity (managed by configure, not memory CLI)
├── memories/
│   ├── MEMORY.md        # agent notes, ≤2200 chars
│   └── USER.md          # user profile, ≤1375 chars
└── state.db             # session/transcript history (NOT memory; out of scope)
```

## Out of scope (deferred follow-up issues)

- Multi-platform messaging gateways (Discord/Slack/Telegram/WhatsApp/Signal/email/Teams/Google Chat/Matrix/Mattermost/QQBot/Feishu/DingTalk).
- Hermes pluggable memory backends (Holographic/Honcho/Hindsight/Mem0/Byterover/OpenViking) — clm's `memory` CLI only sees the default markdown backend until this follow-up.
- MCP server registration.
- `~/.hermes/state.db` (session/transcript history) inspection via clm.
- OAuth file (`HERMES_OAUTH_FILE`) and webhook secrets.
- Installer-checksum refresh helper script (manifest must be re-pinned every version bump).

## Risks / Unknowns

1. **`/health` auth on loopback** — hermes refuses non-loopback bind without `API_SERVER_KEY`, but it's unclear whether `/health` requires the bearer header even on `127.0.0.1`. Confirmed during Phase 2 PR testing on a real host. Worst case: probe with `Authorization: Bearer $API_SERVER_KEY`.

2. **Hermes daemon writes to `MEMORY.md`/`USER.md` while clm edits.** Race possible. Mitigation: openclaw memory_write playbook already uses atomic write (write → fsync → rename); replicate verbatim. Verified safe under concurrent reader.

3. **`~/.hermes/memories/` may not exist on a fresh install** until the agent writes its first memory. Phase 1 install creates the dir explicitly so `memory show` returns an empty listing rather than a "not found" error.

4. **Manifest schema migration** — adding `workspace` and `features` fields. Backward-compatible since both are optional with defaults; existing zeroclaw / openclaw manifests continue to validate.

5. **Phase 1 service starts but exits immediately if user runs `clm agent start N` before configure.** Hermes gateway with no platforms enabled and no provider key effectively no-ops + exits. Documented as expected — not a bug. UX guidance: "configure before start". Acceptance test asserts this exact behavior.

6. **Hermes tag→installer-script SHA drift on version bumps** — manifest must be re-pinned every version bump. Tracked as separate follow-up issue.

## Acceptance for the issue (Phase 5 close-out)

- [ ] `clm claw list` shows `hermes`.
- [ ] `clm agent install --type hermes --host <host> --name <name>` succeeds; service unit dropped, disabled, not started.
- [ ] `clm agent configure <name> --provider openrouter --model <m> --api-key <KEY>` succeeds and brings the service up; `/health` returns 200.
- [ ] `clm agent start | stop | remove <name>` all succeed.
- [ ] `curl http://127.0.0.1:8642/v1/models` (after port-forward or local exec) returns `hermes-agent`.
- [ ] `clm agent <hermes-name> memory show` lists `MEMORY.md` + `USER.md`.
- [ ] `clm agent <hermes-name> memory write USER.md <content>` succeeds for ≤1375 chars; rejects >1375.
- [ ] `clm agent <openclaw-name> memory show` continues to behave identically to pre-change.
- [ ] `clm agent <zeroclaw-name> memory show` returns `"memory operations not supported for agent type 'zeroclaw'"`.
- [ ] `docs/agent-support/hermes.md` published; index updated.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-10T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:plan-create 68
```

User refinements during planning (chronological):

1. "1. update the version check using checksum 2. read the docs for hermes and find out how to run a non interactive instlaltion 3. this si fine. only defaults are used here. memory,mcp et will be subsequent featuers 4. confirm evn var names againt documentation. update this plan (dontw rite yet)"
2. "1. not sure i understnad. why will this fail? 2. ripgrep and ffmpeg shoudl be in base installation modules, expect them to exist. if not, instllation fails 3. leave out for now. will be part of upgrades (add a new issue for it). update plan"
3. "bunch of new changes landed in the main branch. update this plan accordingly"
4. "ok. need the point 2 to be resolved here. memory management needs to be generic otherwise hermes will not work. pull that into the scope for this issue. create plan for this in the plan file using /itx:plan-create"
5. "merge phase 1 and 2 and 3. the outcome of this should be a successfully running hermes agent. it wont have any way of communicating but it should boot up successfully. give me updated plan. any risks?"
6. "1. verify tif there are flags to boot this without channels? if nto can i configure discord or simple chat bot locally? do a research, read the docs 2. same as 1 3. fine. break it down into installation and configuration. but configuration shoudl be both gateay and llm and anything else 4. needs to be fixed. this should show hermes memory for this agent, not some random openclaw memory 5. yes its a hard prereq. user needs to add aprovider to install the agent anway. that part of the workflow for openclaw as well 6. correct. this is the same as opecnlaw flow, no changes. idepmpotency needs to be presevered 7. already addrssed. real key will be provided and state will be checked. read the docs to understand whats the right way to cehck status of the gent."
7. "for phase 1, use approach A, use sqlite but standardize the interfaces. but im not sure why the write/delete cannot be supported? does hermes not use soul.md identity.md etc fiels? even if they're stored in sqlite, can they not be edited the same way as openclaw? im ok with other memory fiels not being editable. do more releasech on this phase. do this first, no pr update yet"
8. "yes, thsi looks good. update the plan and pr. create a flow diagram in the plan as well to articulate the steps and outcomes at each step"

Key research outcomes that shaped this plan:

- `gateway/platforms/api_server.py` provides a local OpenAI-compatible HTTP server, eliminating the need for any external messaging gateway during Phase 1+2 boot.
- `API_SERVER_ENABLED=1` + `API_SERVER_KEY=<token>` in `~/.hermes/.env` is the auto-discovery trigger (`gateway/config.py:1373-1397`).
- Default hermes memory backend is markdown-based (`~/.hermes/memories/MEMORY.md`, `USER.md`), not SQLite. SQLite (`state.db`, holographic plugin) is for transcript history and optional pluggable backends respectively — both out of scope for this issue.
- Identity files (`SOUL.md`, `AGENTS.md`) are explicitly distinct from memory in hermes's own documentation; managed by configure/onboarding rather than the `memory` CLI.

</details>
