# Issue #68 — Execution Scaffolding

**Mode**: multi-phase (5 phases)

## Pre-flight Outcomes (recorded 2026-05-10)

Pinned values for Phase 1+2 implementation, verified end-to-end before Phase 1 begins.

| Item | Value |
|------|-------|
| Hermes tag | `v2026.5.7` (released 2026-05-07, "The Tenacity Release") |
| Installer SHA256 | `b34368cb0628d5acbdc48fe6f4160fb6f51bb33377e8f5a7415fd790a57456e5` |
| Installer URL | `https://raw.githubusercontent.com/NousResearch/hermes-agent/v2026.5.7/scripts/install.sh` |
| Installer size | 62237 bytes |
| Hermes preflight binaries | `rg` (canonical name; `ripgrep` apt package), `ffmpeg` — verify with `command -v rg` / `command -v ffmpeg` |
| Test host | `wolf-i` (Ubuntu 24.04.4 LTS, x86_64, 8 CPU, 15.5 GiB RAM) |
| Test host SSH | clm-managed key `~/.config/clawrium/keys/wolf-i/xclm_ed25519` → user `xclm` (NOPASSWD root) |
| Test host prereqs | `rg` (14.1.0) + `ffmpeg` (6.1.1) installed and verified |
| Test agent name | `hermes-test` (used across Phase 1 + Phase 2 E2E; removed at end of each phase) |
| Phase 2 E2E provider | `local-inx` (existing clm provider, type `ollama`, endpoint `http://192.168.1.17:11434`); model `qwen3-coder:30b-128k` |

## Stacked-PR Workflow (per user direction, 2026-05-10)

- Phase 1 branch: `issue-68-phase-1-installation` from `origin/main`. PR base = `main`.
- Phase 2 branch: `issue-68-phase-2-configuration` from **`issue-68-phase-1-installation`** (NOT main). PR base = `issue-68-phase-1-installation`.
- Both PRs stay open simultaneously. User merges in sequence (Phase 1 first); GitHub auto-retargets Phase 2 PR base to `main` on Phase 1 merge.

## Phase 2 Plan Extension — Ollama / custom OpenAI-compatible endpoint

The `00_PLAN.md` Phase 2 section limits `.env.j2` to `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. To E2E test with the local DGX Spark via the existing `local-inx` provider (Ollama), Phase 2 must additionally support clm provider type `ollama` (and any other URL-based custom OpenAI-compatible endpoint).

Implementation notes (research during Phase 2 worktree work):

- Hermes upstream supports custom endpoints. Identify the canonical env var(s) — likely `OPENAI_BASE_URL` / `OPENAI_API_BASE` / `HERMES_INFERENCE_BASE_URL` — by reading `gateway/config.py` at tag `v2026.5.7`. Pin findings into the scaffold before coding.
- `.env.j2` adds an `ollama`/custom branch that emits `HERMES_INFERENCE_PROVIDER=openai` (or whatever hermes accepts) + base-url env var pointing at the clm provider's `endpoint` URL + a placeholder `OPENAI_API_KEY` if hermes requires one for the openai-compatible code path.
- `configure.yaml` per-provider verification block extends to the ollama branch (URL reachable from agent host).
- `tests/test_hermes_configure.py` adds `ollama`/custom branch coverage.
- Phase 2 acceptance criteria (`01_EXECUTION.md` + subtask #313 body) get an additional row: "ollama provider drives `.env` correctly; service comes up; `/v1/models` returns hermes-agent identity using local-inx model".

### Hermes env-var research (pinned before coding, tag v2026.5.7)

Sources read:
- `gateway/config.py` — only the API_SERVER_* gateway/platform env vars, not provider/model selection.
- `hermes_cli/config.py` — hermes runtime config layout: TWO files in `~/.hermes/`:
  - `config.yaml` — `model.provider`, `model.default`, `model.base_url` (the canonical model selection).
  - `.env` — API keys (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) + platform vars (`API_SERVER_*`).
- `hermes_cli/runtime_provider.py` — provider resolution precedence:
  1. explicit `--provider` flag (CLI only, not relevant for daemon)
  2. `model.provider` in `config.yaml`
  3. `HERMES_INFERENCE_PROVIDER` env var (read but lower-priority than config.yaml)
  4. `"auto"` (auto-detect from credentials present in env).
- `hermes_cli/providers.py` — provider catalogue.
- `cli-config.yaml.example` — default config.yaml shipped at install time.
- `plugins/model-providers/custom/__init__.py` — `custom` is the provider that backs local Ollama / vLLM / llama.cpp / any user-OpenAI-compatible URL. The aliases `ollama`, `local`, `vllm`, `llamacpp`, `llama.cpp`, `llama-cpp` all map to `custom`. `env_vars=()` (no fixed key — base_url + optional api_key come from `model.base_url` in `config.yaml`).

Findings:

| Need | Mechanism |
|------|-----------|
| Cloud provider selection | `model.provider: openrouter` (or `anthropic`, `openai`, `auto`) in `config.yaml`. Equivalent override `HERMES_INFERENCE_PROVIDER=<name>` in `.env` is honored but lower-precedence than config.yaml. |
| Model selection | `model.default: <id>` in `config.yaml`. `HERMES_INFERENCE_MODEL` is NOT honored (the env-var fallback in `runtime_provider.py` only looks at `HERMES_INFERENCE_PROVIDER`); plan's mention of `HERMES_INFERENCE_MODEL` was incorrect — model must be in `config.yaml`. |
| Cloud API key | `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in `.env` (matches plan). |
| Custom OpenAI-compatible endpoint (local Ollama, vLLM, etc.) | `model.provider: custom` (alias `ollama` works) + `model.base_url: http://host:port/v1` + `model.default: <model_id>` in `config.yaml`. No required env var. The `custom` provider's `env_vars=()` means hermes does NOT need any API key to call a local endpoint — it sends `Authorization: Bearer ` (empty) which Ollama accepts. |
| Gateway daemon (local OpenAI-compatible API on 127.0.0.1:8642) | `API_SERVER_ENABLED=1` + `API_SERVER_KEY=<token>` in `.env` (matches plan). Optional `API_SERVER_HOST=127.0.0.1`, `API_SERVER_PORT=8642`. The `/health` endpoint does NOT require the bearer header (verified during Phase 2 E2E; `/v1/*` endpoints DO). |

Decision: Phase 2 renders BOTH files:
1. `~/.hermes/.env` (mode 0600) — cloud provider API keys + `API_SERVER_*` block. `HERMES_INFERENCE_PROVIDER` ALSO emitted as a redundant safety net (low-priority anyway).
2. `~/.hermes/config.yaml` (mode 0600) — partial config containing only the `model:` block. Hermes deep-merges this with `DEFAULT_CONFIG` at load time, so omitted top-level keys retain hermes defaults. The installer's previously-written `config.yaml` is safe to overwrite (it was the example template).

Per-provider mapping:

| clm `provider.type` | rendered `model.provider` | rendered `model.base_url` | rendered `.env` key |
|---------------------|---------------------------|----------------------------|---------------------|
| `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `anthropic` | `anthropic` | (omitted; hermes default) | `ANTHROPIC_API_KEY` |
| `openai` | `openai` | (omitted; hermes default) | `OPENAI_API_KEY` |
| `ollama` | `custom` | `<provider.endpoint>/v1` (suffix `/v1` appended if missing) | (none) |



**Rationale**: Plan (`.itx/68/00_PLAN.md`) explicitly enumerates 5 independent PRs with one strict ordering edge: Phase 1 (installation primitives + manifest schema) must land before any other phase compiles meaningfully. Phase 3 (memory generalization) depends on Phase 1's manifest fields (`workspace.memory_path`, `features.memory`). Phase 2 (configuration), Phase 4 (onboarding metadata), Phase 5 (docs) depend only on Phase 1. Phases 2/3 may run in parallel after Phase 1 lands; phases 4/5 may run in parallel after their respective deps. Splitting reduces review surface (each PR ≤ ~600 LOC) and bounds blast radius — a regression in memory generalization (Phase 3) cannot block hermes lifecycle (Phases 1+2).

Source-of-truth ordering: Phase 1 → {Phase 2, Phase 3} → Phase 4 → Phase 5. Issue #68 stays open until Phase 5 merges.

---

## Phase 1: Installation primitives + manifest schema

**Branch**: `issue-68-phase-1-installation`

**Entry Criteria** (must be true to start):

- [x] `.itx/68/00_PLAN.md` exists and is current
- [ ] Hermes-agent latest release tag identified (`<TAG>`)
- [ ] `scripts/install.sh` SHA256 computed at `<TAG>` (`<INSTALLER_SCRIPT_SHA256>`)
- [ ] Working tree clean
- [ ] Branch created from `main`: `issue-68-phase-1-installation`

**Files Affected**:

| File | Change Type | Notes |
|------|-------------|-------|
| `src/clawrium/platform/registry/hermes/manifest.yaml` | Create | agent metadata; `workspace.memory_path`, `features.memory: true` declared upfront for Phase 3 schema stability; platforms entries for ubuntu 22.04 + 24.04 x86_64 |
| `src/clawrium/platform/registry/hermes/playbooks/install.yaml` | Create | Direct port of openclaw `install.yaml` post-#163 (version-aware skip + `--force`); preflight ripgrep/ffmpeg; `get_url` installer with `checksum: "sha256:..."`; non-interactive `bash install.sh --skip-setup --branch <TAG> --hermes-home ~/.hermes --dir ~/.hermes/code`; create `~/.hermes/`, `~/.hermes/.env` (empty 0600 force:no), `~/.hermes/memories/`; drop systemd unit DISABLED+STOPPED |
| `src/clawrium/platform/registry/hermes/playbooks/start.yaml` | Create | re-render unit, `systemctl start`, wait active, `pgrep` check, optional `/health` probe |
| `src/clawrium/platform/registry/hermes/playbooks/stop.yaml` | Create | stop + disable, preserve `~/.hermes/` |
| `src/clawrium/platform/registry/hermes/playbooks/remove.yaml` | Create | stop, remove unit, rm `~/.hermes/`, rm `~/.local/bin/hermes`, `userdel` |
| `src/clawrium/core/registry.py` | Modify | Extend `AgentManifest` TypedDict with optional `workspace.memory_path: str` and `features.memory: bool` (backward-compatible) |
| `src/clawrium/platform/registry/openclaw/manifest.yaml` | Modify | Add `workspace.memory_path: "~/.openclaw/workspace/memory"` and `features.memory: true` (no behavior change; schema alignment) |
| `tests/test_registry_hermes.py` | Create | listing + manifest validation + installer checksum + workspace/features fields present |
| `tests/test_registry.py` | Modify (if exists) | `test_manifest_accepts_workspace_and_features_fields`; `test_manifest_workspace_optional_for_legacy_types` (zeroclaw still validates) |

**Internal Sequencing**:

1. Pin `<TAG>` and compute `<INSTALLER_SCRIPT_SHA256>` (record in PR body).
2. Extend `core/registry.py` `AgentManifest` TypedDict with optional `workspace`/`features` blocks.
3. Add `workspace`/`features` to existing `openclaw/manifest.yaml`; verify `make test` still green (no behavior change).
4. Author `hermes/manifest.yaml` skeleton with platform entries + workspace + features.
5. Author `hermes/playbooks/install.yaml` mirroring openclaw post-#163; assert `bash install.sh --skip-setup --branch ... --hermes-home ... --dir ...` and `creates: ~/.local/bin/hermes`.
6. Author `start.yaml`/`stop.yaml`/`remove.yaml`.
7. Author `tests/test_registry_hermes.py` (4 cases per plan).
8. Verify `ansible-playbook --syntax-check` on each playbook.

**Exit Criteria** (must be true to complete):

- [ ] `make test` green (existing + new)
- [ ] `make lint` green
- [ ] Installer SHA256 verified against tagged commit (recorded in PR body)
- [ ] `clm claw list` shows `hermes`
- [ ] On a clean Ubuntu 24.04 host with `ripgrep`+`ffmpeg`: `clm agent install --type hermes --host <h> --name <n>` succeeds; `~/.local/bin/hermes` exists; systemd unit dropped, **disabled, not started**
- [ ] On a host missing `ripgrep` or `ffmpeg`: install fails with clear remediation
- [ ] Re-run install on already-installed host skips binary install (version match)
- [ ] `--force` re-runs the installer
- [ ] `clm agent start <n>` starts the unit; service exits immediately (no provider) — documented expected behavior
- [ ] `.itx/68/` directory committed alongside source changes
- [ ] Review passes per `AGENTS.md` review mode

**Dependencies**: None (foundation phase)

**Complexity**: complex (manifest schema migration + new claw type + 4 playbooks + cross-claw test impact)

---

## Phase 2: Configuration (LLM provider + api_server gateway)

**Branch**: `issue-68-phase-2-configuration`

**Entry Criteria**:

- [ ] Phase 1 merged to `main`
- [ ] Branch created from `main`: `issue-68-phase-2-configuration`

**Files Affected**:

| File | Change Type | Notes |
|------|-------------|-------|
| `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` | Create | render `.env.j2` → `~/.hermes/.env` (mode 0600); per-provider `lineinfile check_mode: true` verification; restart handler enables + starts service; probe `/health` with retries |
| `src/clawrium/platform/registry/hermes/templates/.env.j2` | Create | provider/model/key + `API_SERVER_ENABLED=1`, `API_SERVER_HOST=127.0.0.1`, `API_SERVER_PORT=8642`, `API_SERVER_KEY={{ api_server_key }}` |
| `src/clawrium/core/install.py` | Modify | Generate + persist `API_SERVER_KEY` per agent in `hosts.json` (mirror openclaw gateway-token pattern, `install.py:577-650`); idempotent on reconfigure |
| `tests/test_hermes_configure.py` | Create | `.env` rendering covers openrouter/anthropic/openai branches; `API_SERVER_KEY` persistence reused across reconfigure; provider-credential verification gating; restart handler triggers |

**Internal Sequencing**:

1. Add `API_SERVER_KEY` generation + persistence in `core/install.py` (32-byte hex, store under `hosts.json` agent record).
2. Author `templates/.env.j2`.
3. Author `playbooks/configure.yaml` (render → verify → restart → probe).
4. `/health` probe — confirm whether bearer header required on loopback (Risks #1 in plan); adjust probe if needed.
5. Tests for env rendering branches and key idempotency.

**Exit Criteria**:

- [ ] `make test` / `make lint` green
- [ ] On a real host: `clm agent configure <n> --provider openrouter --model <m> --api-key <KEY>` completes; `~/.hermes/.env` written 0600; service active; `curl http://127.0.0.1:8642/health` returns 200
- [ ] `curl http://127.0.0.1:8642/v1/models` lists `hermes-agent`
- [ ] Reconfigure with different provider rotates `.env` keys but reuses `API_SERVER_KEY` (idempotency)
- [ ] Configure without provider key fails with clear error before service start
- [ ] Review passes per `AGENTS.md`

**Dependencies**: Phase 1

**Complexity**: moderate

---

## Phase 3: Generalize memory module across claw types

**Branch**: `issue-68-phase-3-memory-generic`

**Entry Criteria**:

- [ ] Phase 1 merged (manifest schema available for `workspace.memory_path` + `features.memory`)
- [ ] Branch created from `main`: `issue-68-phase-3-memory-generic`

**Files Affected**:

| File | Change Type | Notes |
|------|-------------|-------|
| `src/clawrium/core/memory.py` | Modify | Drive workspace from `manifest.workspace.memory_path` (no hard-coded `~/.openclaw/workspace`); rename `_resolve_openclaw_agent` → `_resolve_agent_with_memory`; filter by `manifest.features.memory == true`; dispatch `memory_<op>` from agent's own registry dir |
| `src/clawrium/cli/memory.py` | Modify | Friendly error `"memory operations not supported for agent type '<type>'"` when manifest lacks `features.memory: true` |
| `src/clawrium/platform/registry/hermes/playbooks/memory_info.yaml` | Create | direct port of openclaw equivalent, target `~/.hermes/memories/` |
| `src/clawrium/platform/registry/hermes/playbooks/memory_read.yaml` | Create | slurp + return contents |
| `src/clawrium/platform/registry/hermes/playbooks/memory_write.yaml` | Create | atomic write (write → fsync → rename); validate `MEMORY.md ≤ 2200`, `USER.md ≤ 1375`; reject other filenames |
| `src/clawrium/platform/registry/hermes/playbooks/memory_delete.yaml` | Create | confirm + rm |
| `tests/test_core_memory.py` | Modify | existing openclaw cases unchanged; add `test_memory_show_hermes_lists_memory_user_files`, `test_memory_write_hermes_rejects_oversize_user_md`, `test_memory_show_unsupported_type_friendly_error` (zeroclaw target) |

**Internal Sequencing**:

1. Refactor `core/memory.py` to read `workspace.memory_path` + `features.memory` from manifest; keep openclaw paths byte-identical via the manifest fields added in Phase 1.
2. Refactor `cli/memory.py` for unsupported-type friendly error.
3. Author hermes `memory_*.yaml` playbooks (port from openclaw).
4. Add char-limit validation in `memory_write.yaml` keyed on filename.
5. Tests — verify openclaw byte-for-byte parity, hermes happy paths, zeroclaw friendly error.

**Exit Criteria**:

- [ ] `make test` / `make lint` green
- [ ] `clm agent <openclaw-name> memory show|read|write|edit|delete` byte-for-byte identical to pre-change behavior (no regression)
- [ ] `clm agent <hermes-name> memory show` lists `MEMORY.md` + `USER.md` (or empty list pre-first-write)
- [ ] `clm agent <hermes-name> memory write USER.md <≤1375 chars>` succeeds
- [ ] `clm agent <hermes-name> memory write USER.md <>1375 chars>` rejects with character-limit error
- [ ] `clm agent <zeroclaw-name> memory show` returns `"memory operations not supported for agent type 'zeroclaw'"`
- [ ] No race observed between hermes daemon writes and clm edits (atomic-write verified)
- [ ] Review passes per `AGENTS.md`

**Dependencies**: Phase 1 (manifest schema). Independent of Phase 2.

**Complexity**: complex (cross-claw refactor with backward-compat guarantee)

---

## Phase 4: Onboarding metadata

**Branch**: `issue-68-phase-4-onboarding`

**Entry Criteria**:

- [ ] Phase 1 merged
- [ ] Phase 2 merged (provider config drives `provider_select` + `provider_test`)
- [ ] Branch created from `main`: `issue-68-phase-4-onboarding`

**Files Affected**:

| File | Change Type | Notes |
|------|-------------|-------|
| `src/clawrium/platform/registry/hermes/manifest.yaml` | Modify | Add `onboarding.stages`: `providers` (required, `provider_select` + `provider_test`), `identity` (`auto_skip: true`), `channels` (default `cli`), `validate` (`hermes --version` + `.env` exists + `/health` 200) |
| `src/clawrium/platform/registry/hermes/templates/...` | Create (as needed) | Minimal templates referenced by stages |
| `tests/test_hermes_onboarding.py` | Create | manifest schema validation; stage progression; auto-skip behavior |

**Internal Sequencing**:

1. Add `onboarding.stages` block to hermes manifest.
2. Add minimal templates if stages reference any.
3. Tests — manifest validates; stage ordering correct; identity auto-skips.

**Exit Criteria**:

- [ ] `make test` / `make lint` green
- [ ] On a real host: full onboarding flow succeeds end-to-end (provider select → test → channels default cli → validate green)
- [ ] Identity stage auto-skips
- [ ] Validate stage fails when `/health` returns non-200
- [ ] Review passes per `AGENTS.md`

**Dependencies**: Phase 1, Phase 2

**Complexity**: moderate

---

## Phase 5: Documentation + issue close-out

**Branch**: `issue-68-phase-5-docs`

**Entry Criteria**:

- [ ] Phase 1, 2, 3, 4 merged
- [ ] Branch created from `main`: `issue-68-phase-5-docs`

**Files Affected**:

| File | Change Type | Notes |
|------|-------------|-------|
| `docs/agent-support/hermes.md` | Create | capability matrix, install/configure walkthrough, `curl http://127.0.0.1:8642/v1/chat/completions` example |
| `docs/agent-support/index.md` | Modify | Add hermes row + Quick Comparison column; status `🚧 In Development` |
| `docs/agent-support/memory.md` | Create | document manifest-driven memory model spanning claw types |
| `README.md` | Modify (if applicable) | Mention hermes if Quickstart enumerates claw types |

**Internal Sequencing**:

1. Author `hermes.md` capability + walkthrough.
2. Update `index.md` table + comparison column.
3. Author `memory.md` covering manifest-driven dispatch.
4. README check + minor edit if claw types listed.

**Exit Criteria**:

- [ ] `make lint` green (markdown lint if configured)
- [ ] `docs/agent-support/hermes.md` published; matrix + walkthrough accurate
- [ ] `docs/agent-support/index.md` updated; hermes status `🚧 In Development`
- [ ] `docs/agent-support/memory.md` published
- [ ] README accurate (if changed)
- [ ] Issue #68 acceptance criteria all checked off in PR body
- [ ] Review passes per `AGENTS.md`
- [ ] Issue #68 closed by PR merge

**Dependencies**: Phase 1, 2, 3, 4

**Complexity**: simple

---

## Risks Carried Forward From Plan

1. **`/health` auth on loopback** — confirmed during Phase 2 testing; if bearer header required, probe must include `Authorization: Bearer $API_SERVER_KEY`.
2. **Concurrent write race** between hermes daemon and clm memory CLI — mitigated by atomic-write pattern (`write → fsync → rename`) in `memory_write.yaml`.
3. **Memory dir absent on fresh install** — Phase 1 creates `~/.hermes/memories/` so `memory show` returns empty list, not "not found".
4. **Manifest schema migration** — backward-compatible (optional fields); zeroclaw still validates without `workspace`/`features`.
5. **Phase 1 service exits immediately if started before configure** — documented expected behavior; not a bug. Acceptance test asserts this.
6. **Hermes tag → installer-script SHA drift** — manifest must be re-pinned every version bump. Tracked as separate follow-up issue.

---

## Manual Verification Checklist (deferred to owner; per-phase, not part of CI)

After Phase 5 merges, on a real host:

- [ ] `clm claw list` shows `hermes`
- [ ] `clm agent install --type hermes --host <h> --name <n>` succeeds; unit dropped, disabled, not started
- [ ] `clm agent configure <n> --provider openrouter --model <m> --api-key <KEY>` succeeds; `/health` returns 200
- [ ] `clm agent start | stop | remove <n>` all succeed
- [ ] `curl http://127.0.0.1:8642/v1/models` returns `hermes-agent`
- [ ] `clm agent <n> memory show` lists `MEMORY.md` + `USER.md`
- [ ] `clm agent <n> memory write USER.md <≤1375>` succeeds; `>1375` rejects
- [ ] Existing openclaw memory CLI behavior unchanged
- [ ] zeroclaw `memory show` returns friendly unsupported-type error
- [ ] `docs/agent-support/hermes.md` published; index updated

---

<details>
<summary>Prompt Log</summary>

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-10T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 68
```

---

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-10T17:50:00Z
**Model**: claude-opus-4-7
**Subtask**: #312 (Phase 1)
**Branch**: `issue-68-phase-1-installation`

```prompt
/itx:execute 312
```

E2E findings worth carrying into Phase 2:

1. The hermes `--version` output uses TWO triples: a python-package version (e.g. `v0.13.0`) followed by the upstream tag in parentheses (e.g. `(2026.5.7)`). Manifest pins on the parenthesised tag, so the install playbook's regex parses `\(([0-9]+\.[0-9]+\.[0-9]+)\)` rather than the leading triple.

2. `git tag` for hermes is always `v`-prefixed (e.g. `v2026.5.7`), but `clm`'s manifest stores versions WITHOUT the `v` prefix to satisfy `packaging.version.Version`. The install playbook synthesises the tag with `hermes_target_branch: "v{{ hermes_target_version }}"` rather than passing `claw_version` straight through (which would yield `vv2026.5.7`).

3. The hermes installer writes `~/.hermes/.env` itself (mode 0644). `force: no` on our `copy` task preserves it but does NOT update permissions. A subsequent `file:` task enforces 0600 unconditionally so any provider keys placed there in Phase 2 are not world-readable.

4. The hermes runtime install (uv venv, pip install, npm install, playwright) takes 10+ minutes and was failing with `Shared connection ... closed`. Wrapping it in `async: 1800, poll: 30` reuses the SSH connection per-poll instead of holding it open for the entire install.

5. Hermes calls `loginctl enable-linger` on first start, which keeps a per-user systemd manager + dbus running even after we stop the system unit. `userdel` then fails with "user is currently used by process". `remove.yaml` now runs `loginctl disable-linger` + `pkill -KILL -u <user>` before `userdel`.

6. Per-host start/stop via `clm agent <name>` is gated by onboarding state (`pending_onboard`). Phase 1 leaves the agent in PENDING state by design (no `onboarding.stages` declared yet); Phase 2 / Phase 4 unblock the start path. Direct `systemctl start hermes-<name>.service` confirms the documented "service exits immediately, status 1, log says 'Gateway service is not installed'" behavior.

---

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-10T18:30:00Z
**Model**: claude-opus-4-7
**Subtask**: #313 (Phase 2)
**Branch**: `issue-68-phase-2-configuration` (stacked on `issue-68-phase-1-installation`)

```prompt
/itx:execute 313 (sub-agent invocation)
```

Implementation outcomes:

1. Hermes uses TWO config files (research finding pinned above): `config.yaml` for `model.provider` / `model.default` / `model.base_url`, and `.env` for API keys + `API_SERVER_*`. Phase 2 renders both. `HERMES_INFERENCE_MODEL` is NOT a recognized env var (the plan mentioned it incorrectly) — model selection happens via `model.default` in `config.yaml` only.

2. `model.provider: custom` with `model.base_url: <endpoint>/v1` drives the local Ollama / vLLM / llama.cpp / any OpenAI-compatible endpoint. clm `provider.type=ollama` maps to it. The hermes `custom` provider has `env_vars=()` so no API key is required for local endpoints.

3. **Phase 1 carryover bug discovered during E2E and fixed in Phase 2**: Phase 1's install.yaml dropped a systemd unit with `ExecStart=... hermes gateway start`, but `hermes gateway start` delegates to a per-user systemd unit installed via `hermes gateway install` (which we don't run). It exits 1 with "Gateway service is not installed". The correct foreground-supervisor command is `hermes gateway run`. Phase 2's `configure.yaml` re-renders the unit with `gateway run` before the restart handler fires. Phase 1's unit file remains as a placeholder until configure runs (which is the expected lifecycle: install → configure → ready). Filing a follow-up suggestion to update Phase 1's `install.yaml` and `start.yaml` to use `gateway run` directly is recommended; tracked in PR description.

4. Configure timeout in `core/lifecycle.py` was 60s — too short for hermes (service restart + 20×3s `/health` retries). Bumped to 240s for `resolved_type == "hermes"`.

5. `lineinfile` in `check_mode` does NOT correctly verify a credential is present — it always reports `changed=true` when the regexp matches a value-bearing line that differs from the placeholder. (This pattern is also broken in openclaw's `configure.yaml`; out-of-scope to fix here.) Phase 2 uses `command: grep -q '^KEY='` instead, which gives a clean rc=0/1 contract.

6. `/health` endpoint on the hermes API server is **unauthenticated** (verified during E2E: `curl http://127.0.0.1:8642/health` returns 200 without bearer header). `/v1/*` endpoints DO require `Authorization: Bearer $API_SERVER_KEY`.

7. `API_SERVER_KEY` generation moved to `core/install.py` (not `core/lifecycle.py::configure_agent` as one reading of the plan suggested). This mirrors openclaw's gateway-token pattern: install generates the secret, persists it in `hosts.json`, and configure reuses it. Idempotency comes from re-using the persisted key when an existing 64-char hex value is found in the agent record at install time (covers re-install scenarios) and from `configure_agent` hydrating from `hosts.json` on every reconfigure.

E2E results on wolf-i (192.168.1.36) against `local-inx` provider (Ollama @ 192.168.1.17:11434, model `qwen3-coder:30b-128k`):

- `clm agent install --type hermes --host wolf-i --name hermes-test` succeeded; `API_SERVER_KEY` persisted in `hosts.json`.
- `clm agent configure hermes-test --stage providers` (with `local-inx` selected) succeeded; service active+running.
- `~/.hermes/.env` rendered 0600, contains `API_SERVER_KEY` + `HERMES_INFERENCE_PROVIDER=custom`.
- `~/.hermes/config.yaml` rendered 0600 with `model: {provider: custom, base_url: http://192.168.1.17:11434/v1, default: qwen3-coder:30b-128k}`.
- `curl http://127.0.0.1:8642/health` → `{"status": "ok", "platform": "hermes-agent"}` (200, no auth).
- `curl http://127.0.0.1:8642/v1/models -H "Authorization: Bearer ..."` → `[{"id": "hermes-agent", ...}]`.
- `curl -X POST http://127.0.0.1:8642/v1/chat/completions -H "Authorization: Bearer ..." -d '{"model":"hermes-agent","messages":[{"role":"user","content":"Say only the word OK and nothing else."}],"max_tokens":16}'` → `{"choices":[{"message":{"role":"assistant","content":"OK"}}], ...}`. Full hermes-via-clm-via-ollama-via-DGX-Spark roundtrip works.
- Reconfigure with `local-inx.default_model` rotated to `gpt-oss:20b-128k` succeeded; `API_SERVER_KEY` byte-identical across reconfigures (idempotency contract verified); `model.default` rotated; service still active.
- `clm agent remove hermes-test --force` cleaned up: user removed, `~/.hermes/` deleted, systemd unit removed, `~/.local/bin/hermes` symlink removed, `hosts.json` agent record (with `api_server.key`) removed.

---

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-10T19:30:00Z
**Model**: claude-opus-4-7
**Subtask**: #314 (Phase 3)
**Branch**: `issue-68-phase-3-memory-generic` (base: `main`)

```prompt
/itx:execute 314 (sub-agent invocation)
```

Implementation outcomes:

1. `core/memory.py` refactored to dispatch by manifest. New `_resolve_agent_with_memory()` returns a 3-tuple `(host, unix_name, claw_type)` and filters candidates by `claw_supports_memory(claw_type)` (which reads `features.memory: true` from each manifest) rather than the old hard-coded `record.get("type") == "openclaw"` check. The legacy `_resolve_openclaw_agent()` is preserved as a backward-compat function for code/tests that pre-date the refactor (no external CLI surface still calls it on the public path).

2. `_PLAYBOOK_DIR` module-global preserved (points at openclaw playbooks) as a fallback for `_get_playbook_dir("openclaw")`. The runner now selects the registry playbook directory dynamically from `claw_type`, so hermes' four `memory_*.yaml` playbooks ship in `registry/hermes/playbooks/` and are picked up automatically.

3. Per-claw filename allowlist + character limits enforced client-side in `write_memory_file()`. Hermes: only `MEMORY.md` and `USER.md` accepted; `MEMORY.md ≤ 2200` chars, `USER.md ≤ 1375` chars. Mismatches return the explicit error string ahead of any Ansible dispatch, so the user sees an immediate, actionable error.

4. `memory_write.yaml` for hermes uses a stage-then-atomic-rename pattern (write to `.<file>.tmp`, then `mv -f` in the same directory). Since `mv` within a filesystem is `rename(2)`, the hermes daemon never observes a partial write. The per-file char limit is also enforced in the playbook as defense-in-depth.

5. `cli/memory.py`: `_resolve_openclaw_for_cli` renamed to `_resolve_agent_for_memory_cli` and now gates on `claw_supports_memory(actual_type)`. Unsupported types emit `"memory operations not supported for agent type '<type>'"` and exit non-zero. The old name is kept as a thin shim returning the legacy 2-tuple. `edit_cmd` now passes the resolved claw_type to `restart_agent()` instead of the hard-coded `"openclaw"` string.

6. Two existing `tests/test_cli_memory.py` cases (`test_show_rejects_non_openclaw_agent`, `test_edit_rejects_non_openclaw_agent`) were updated to match the new error wording. All other openclaw test paths in `tests/test_core_memory.py` continue to assert identical behavior — they were updated to patch the renamed resolver and return the 3-tuple, which is a mechanical change with zero behavior delta.

7. `make test` → 1508 passed. `make lint` → clean.

E2E results on wolf-i (192.168.1.36) — captured after the next "E2E" log entry below.

</details>
