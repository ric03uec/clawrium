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

</details>
