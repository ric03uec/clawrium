# Issue #68 — Implementation Plan

User can deploy and manage `hermes-agent` (Nous Research) via `clm`, mirroring the existing `openclaw` shape in the registry.

Source of truth: GitHub issue #68 plus this file. Subsequent reconciliation comments on the issue may amend phase scope.

## Phasing strategy

The six phases below ship as **independent PRs** to keep reviews small. Each PR closes only the phase milestone; the issue stays open until Phase 6.

| Phase | Branch | PR closes |
|-------|--------|-----------|
| 1 | `issue-68-phase-1-registry` | manifest + `install.yaml` + checksum-pinned installer + smoke tests |
| 2 | `issue-68-phase-2-lifecycle` | `start`/`stop`/`remove` playbooks |
| 3 | `issue-68-phase-3-configure` | `configure.yaml` + provider env wiring (defaults only) |
| 4 | `issue-68-phase-4-memory-generic` | generalize `core/memory.py` + `cli/memory.py` to dispatch by claw type |
| 5 | `issue-68-phase-5-onboarding` | manifest `onboarding.stages` + minimal templates |
| 6 | `issue-68-phase-6-docs` | `docs/agent-support/hermes.md`, index, README |

Multi-platform gateway pairing (Discord/Slack/Telegram/WhatsApp/Signal/email), MCP server registration, Kanban dirs, OAuth, and webhook secrets are explicitly deferred to follow-up issues.

## Confirmed facts (from upstream docs)

**Installer** (`scripts/install.sh`):

- Non-interactive flag: `--skip-setup`.
- Version pinning: `--branch <git-tag>` (git-clone install; no `--version`).
- Data dir: `--hermes-home <path>` (or `HERMES_HOME` env).
- Symlink: root → `/usr/local/bin/hermes`; non-root → `~/.local/bin/hermes`. Both pass `install.yaml`'s safe-path validation.

**Env vars** (Phase 1–5 defaults only):

- Provider keys: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.
- Provider/model selection: `HERMES_INFERENCE_PROVIDER`, `HERMES_INFERENCE_MODEL`.
- Config dir override: `HERMES_HOME` (default `~/.hermes`).
- Hermes reads env from `~/.hermes/.env` (leading dot, unlike openclaw's `~/.openclaw/env`).

## Phase 1 — Registry + Install

**New files**

- `src/clawrium/platform/registry/hermes/manifest.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/install.yaml`
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

**`install.yaml` shape** — direct port of openclaw's `install.yaml` post-#163 (the version-aware skip + `--force` pattern is canonical):

1. Normalize `hermes_target_version` (strip leading `v`).
2. Create agent user.
3. **Preflight**: assert `ripgrep` and `ffmpeg` are installed system-wide; fail with clear remediation message if missing. (Treated as base requirements per scope decision.)
4. `which hermes` → `hermes --version` → compare to target → set `hermes_already_installed` skip-flag with `force_install` override (verbatim mirror of openclaw `install.yaml:31-65`).
5. `get_url` `https://raw.githubusercontent.com/NousResearch/hermes-agent/{{ hermes_target_version }}/scripts/install.sh`
   - `checksum: "sha256:{{ installer_checksum }}"` — required, no `default(omit)`.
   - `mode: 0700`, owner = agent_name.
   - `when: not hermes_already_installed`.
6. Run installer non-interactively as agent user:
   ```
   bash hermes-install.sh \
     --skip-setup \
     --branch {{ hermes_target_version }} \
     --hermes-home /home/{{ agent_name }}/.hermes \
     --dir /home/{{ agent_name }}/.hermes/code
   ```
   `become_user: {{ agent_name }}`, `creates: /home/{{ agent_name }}/.local/bin/hermes`.
7. Clean up installer script.
8. Create `~/.hermes/` (0700) and `~/.hermes/.env` (empty, 0600, `force: no` to preserve on re-install).
9. Drop systemd unit `hermes-{{ agent_name }}.service`:
   ```
   ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway start
   EnvironmentFile=/home/{{ agent_name }}/.hermes/.env
   WorkingDirectory=/home/{{ agent_name }}/workspace
   ```
   Enable + start. Exact `ExecStart` confirmed during PR testing.

**Tests (Phase 1)**

- `test_hermes_listed_in_registry` — `list_claws()` includes `"hermes"`.
- `test_hermes_manifest_validates` — `load_claw_manifest("hermes")` parses + validates.
- `test_hermes_manifest_has_installer_checksum` — every platform entry has non-empty `sha256`.

**Phase 1 acceptance**

- [ ] `make test` green
- [ ] `make lint` green
- [ ] ATX review > 3/5 with no blocking issues
- [ ] Installer SHA256 verified against tagged commit (recorded in PR body)
- [ ] Install succeeds end-to-end on clean Ubuntu 24.04 with `ripgrep` + `ffmpeg` present
- [ ] Install fails with clear remediation message when `ripgrep` or `ffmpeg` missing
- [ ] Re-running install on an already-installed host skips the binary install
- [ ] `--force` re-runs the installer

## Phase 2 — Lifecycle

`start.yaml` / `stop.yaml` / `remove.yaml` modeled on openclaw post-#163:

- `start.yaml`: re-render systemd unit (idempotent), `systemctl start`, wait for active, verify `pgrep -u {{ agent_name }} hermes`.
- `stop.yaml`: stop + disable; preserve `~/.hermes/`.
- `remove.yaml`: stop, remove unit file, remove `~/.hermes/`, remove `~/.local/bin/hermes` symlink, remove agent user.

`src/clawrium/core/lifecycle.py` is generic — no special-casing unless a hermes-specific probe is required (decided during Phase 2).

## Phase 3 — Configure + Provider Env (defaults only)

`configure.yaml` writes `~/.hermes/.env` from `templates/.env.j2`:

- `HERMES_INFERENCE_PROVIDER` ← `config.provider.type`
- `HERMES_INFERENCE_MODEL` ← `config.provider.default_model`
- One of `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` based on `config.provider.type` (mirror openclaw's per-provider verification block in `configure.yaml:186-291`).

Restart handler on `.env` changes.

## Phase 4 — Generalize Memory Module Across Claw Types

**Why this is in scope**: `src/clawrium/core/memory.py` and `src/clawrium/cli/memory.py` are hard-coded to openclaw — see the module docstring at `core/memory.py:1`, the `_resolve_openclaw_agent` filter at `core/memory.py:122-169`, and the workspace path `/home/<agent>/.openclaw/workspace` at `core/memory.py:74,423`. Without this phase, `clm agent <hermes-instance> memory show` returns the misleading error `"openclaw agent '<x>' not found"`.

**Approach**

1. **Workspace path lookup**: derive workspace path from the manifest rather than hard-coding `~/.openclaw/workspace`. Add an optional `workspace.path` field to `manifest.yaml` (e.g. `~/.openclaw/workspace` for openclaw, `~/.hermes/workspace` for hermes). Default to `~/.<agent_type>/workspace` when unset.
2. **Generalize agent resolution**: rename `_resolve_openclaw_agent` → `_resolve_agent_with_memory` and remove the `record.get("type") != "openclaw"` filter. Instead, filter by "claw types whose manifest declares memory support" (presence of `memory_*.yaml` playbooks under the type's registry dir, or an explicit `features.memory: true` manifest flag).
3. **CLI UX for unsupported types**: when invoked against a claw type without memory support, emit `"memory operations not supported for agent type '<type>'"` and exit non-zero.
4. **Hermes opt-out**: hermes manifest does NOT declare memory support in this issue — actual hermes-memory wiring is a follow-up.

**Files modified**

- `src/clawrium/core/memory.py` — generalize resolver, derive paths from manifest.
- `src/clawrium/cli/memory.py` — friendly error for unsupported claw types.
- `src/clawrium/core/registry.py` — add optional `workspace` and `features` fields to `AgentManifest`.
- `src/clawrium/platform/registry/openclaw/manifest.yaml` — add `workspace.path` and `features.memory: true`.
- `tests/test_core_memory.py` — add cases for unsupported claw type and manifest-driven path resolution.
- `tests/test_registry.py` (or new test) — assert manifest schema accepts the new fields.

**Behavioral guarantee**: existing openclaw memory CLI behavior is byte-for-byte identical — same playbook invocations, same workspace paths. Only the dispatch logic changes.

## Phase 5 — Onboarding metadata

Fill in `manifest.yaml::onboarding.stages`:

- `providers` — required, `provider_select` + `provider_test`.
- `identity` — `auto_skip: true` (no SOUL.md analogue in scope).
- `channels` — default `cli`.
- `validate` — `hermes --version` + `~/.hermes/.env` exists.

Templates land under `src/clawrium/platform/registry/hermes/templates/`.

## Phase 6 — Docs

- `docs/agent-support/hermes.md` (capability matrix + walkthrough).
- `docs/agent-support/index.md` — add hermes row + Quick Comparison column; status `🚧 In Development`.
- README mention if Quickstart lists claw types.

## Workspace layout assumed by all phases

`/home/<agent_name>/.hermes/` contains:

- `.env` — provider keys + `HERMES_INFERENCE_*` settings (mode 0600).
- `code/` — installer-managed git checkout of hermes-agent.
- `workspace/` — agent working dir (created lazily by hermes runtime).

## Out of scope (deferred follow-up issues)

- Multi-platform gateway pairing (Discord/Slack/Telegram/WhatsApp/Signal/email/Twilio/Feishu/QQ).
- Hermes memory backend wiring (`HERMES_KANBAN_*`, full-text search, daily files).
- MCP server registration.
- OAuth file (`HERMES_OAUTH_FILE`) and webhook secrets.
- Installer-checksum refresh helper script (manifest must be re-pinned every version bump — captured as separate follow-up).

## Risks / Unknowns

1. **`hermes gateway start` behavior with no gateway configured** — exact `ExecStart` confirmed during Phase 1 PR testing on a real host. Adjusted in-place if it errors.
2. **Manifest schema migration** for the new `workspace` and `features` fields (Phase 4) — backward-compatible since both are optional with defaults; existing zeroclaw / openclaw manifests continue to validate.

## Acceptance for the issue (Phase 6 close-out)

- [ ] `clm claw list` shows `hermes`.
- [ ] `clm agent install --type hermes --host <host> --name <name>` succeeds.
- [ ] `clm agent <name> start | stop | remove` all succeed.
- [ ] `clm agent <name> configure` accepts an OpenRouter / Anthropic / OpenAI provider and writes `~/.hermes/.env` correctly.
- [ ] `clm agent <name> memory show` against a hermes instance returns a clear "memory operations not supported for agent type 'hermes'" message (not a misleading openclaw error).
- [ ] `clm agent <openclaw-name> memory show` continues to behave identically to pre-change.
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

User refinements during planning:

1. "1. update the version check using checksum 2. read the docs for hermes and find out how to run a non interactive instlaltion 3. this si fine. only defaults are used here. memory,mcp et will be subsequent featuers 4. confirm evn var names againt documentation. update this plan (dontw rite yet)"
2. "1. not sure i understnad. why will this fail? 2. ripgrep and ffmpeg shoudl be in base installation modules, expect them to exist. if not, instllation fails 3. leave out for now. will be part of upgrades (add a new issue for it). update plan"
3. "bunch of new changes landed in the main branch. update this plan accordingly"
4. "ok. need the point 2 to be resolved here. memory management needs to be generic otherwise hermes will not work. pull that into the scope for this issue. create plan for this in the plan file using /itx:plan-create"

</details>
