# Issue #734 — `feat(integrations): brave web-search API key`

GitHub: https://github.com/ric03uec/clawrium/issues/734

This file is just the prompt log for the issue-creation stage. Full body lives on the issue. A detailed implementation plan can be appended here as `## Plan` when `/itx-plan-create 734` runs.

## Issue creation

**Stage**: issue-creation
**Skill**: /itx-issue-new
**Timestamp**: 2026-06-16T00:00:00Z
**Model**: claude-opus-4-7

```prompt
add a github tiket to add brave api key integration for all agents (openclaw, hermes and zeroclaw). this will be part of integrations similar to github. resarch docs for each of the these agents and create different sections for these. use /itx-issue-new for this
```

**Followups during this turn:**

- Title confirmed via `AskUserQuestion` → `feat(integrations): brave web-search API key` (option 1, conventional-commit style consistent with #705 / #723).
- User pointed me at hermes upstream PR for cross-reference; first lookup was `#21137` (Anytype, unrelated) — user corrected to `#21337` (merged 2026-05-07: `feat(web): add Brave Search (free tier) and DDGS search providers`).
- User pushed back: zeroclaw + openclaw sections weren't cross-checked with docs. Re-researched directly from upstream source. Issue body rewritten with source line refs.
- Final per-agent picture:
  - **hermes** — env `BRAVE_SEARCH_API_KEY` (NOT `BRAVE_API_KEY`), name mapping required. Source: `hermes_cli/config.py:3076` + PR #21337.
  - **zeroclaw** — env `BRAVE_API_KEY` works at boot; `[web_search] brave_api_key` TOML fallback. CRITICAL: `search_provider = "brave"` (or alias) must also be set or routing stays on duckduckgo. Recommendation: write both `BRAVE_API_KEY=` and `ZEROCLAW_web_search__search_provider=brave` to `.zeroclaw/env` using the documented env-prefix override convention. Live verification step pinned in AC. Sources: `.env.example`, `web_search_tool.rs:88-107`, `web_search_provider_routing.rs:33`.
  - **openclaw** — npm package `@openclaw/brave-plugin`, plugin id `brave`, env fallback `BRAVE_API_KEY` declared first-class in plugin manifest. Canonical JSON path `plugins.entries.brave.config.webSearch.apiKey` source-verified. minHostVersion `>=2026.4.10` (clawrium pins 2026.5.28 OK; wolf-i on 2026.3.13 needs upgrade). Recommendation: env-only path, no JSON-render growth. Plugin install hook required. Sources: `openclaw.plugin.json`, `web-search-shared.ts:12`, `package.json`.

**Output**: GitHub issue #734 created and revised after cross-check pushback.

---

# Plan

## Overview

Add a single `brave` integration type to the clawrium control plane. Operator stores the Brave API key once in the secrets store, attaches it to any supported agent via existing `clawctl agent integration attach` / GUI flow, and `clawctl agent sync` writes the agent-specific shape — env var (hermes name-mapped to `BRAVE_SEARCH_API_KEY`; zeroclaw via systemd `Environment=` lines; openclaw native env) — through the existing canonical renderer per agent. Openclaw additionally needs a pinned plugin install on the host and a min-version preflight. No GUI fan-out math — a single `brave` integration record attaches to N agents independently, matching the github pattern.

## Lifecycle Invariants — explicit anchors

- **#437 — gateway bearer re-pair**: any sync that touches `.zeroclaw/env`, `~/.hermes/.env`, or `~/.openclaw/env` goes through `lifecycle_canonical.sync_agent_canonical`. `_do_pair()` MUST run unconditionally — no `--no-rotate`, no "skip if env unchanged" branching. Existing call path is reused; the brave branch does NOT add a second restart path.
- **#622 — hermes single render path**: `BRAVE_SEARCH_API_KEY` is written exclusively by `render_hermes()` via `hermes-env.canonical.j2`. `configure.yaml` continues to use `ansible.builtin.copy` (lines 111, 126) to push the pre-rendered bytes. No `lineinfile` / Ansible-side `template:` patching is introduced. Byte-lock test pins parity.
- **dispatcher-only OS fork**: macOS branching stays in `playbook_resolver.py`. No `when: ansible_os_family == 'Darwin'` inside existing playbooks. Where needed, a `*_macos.yaml` sibling is added.

## Files to Modify

### Core registry + secret/render
- `src/clawrium/core/integrations.py` — add `INTEGRATION_TYPES["brave"]` with one required credential `BRAVE_API_KEY`.
- `src/clawrium/core/render.py`:
  - `_HERMES_SUPPORTED_INTEGRATIONS` (~line 888): add `brave`.
  - `_ZEROCLAW_SUPPORTED_INTEGRATIONS` (~line 1117): add `brave`.
  - `_OPENCLAW_SUPPORTED_INTEGRATIONS` (~line 1317): add `brave`.
  - `render_hermes` integration view builder (~line 1418): include `brave` view with `BRAVE_API_KEY` credential pass-through.
  - `render_zeroclaw` integration view builder: include `brave` view with the credential value plus the static `search_provider` flag (see zeroclaw section).
  - `render_openclaw` integration view builder (~line 1413+): include `brave` view.
- `src/clawrium/platform/registry/hermes/templates/hermes-env.canonical.j2` (after line ~117): new `{% elif intg.type == 'brave' %}` branch writing `BRAVE_SEARCH_API_KEY={{ intg.creds.get('BRAVE_API_KEY', '') | shq }}` — **name mapping in the template, not in the operator-facing credential**.
- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-env.conf.j2` (after the final `{% endif %}` of the existing integration loop): new branch writing TWO `Environment=` lines:
  - `Environment=BRAVE_API_KEY={{ systemd_quote(_integration.BRAVE_API_KEY) }}`
  - `Environment=ZEROCLAW_web_search__search_provider="brave"`
- `src/clawrium/platform/registry/openclaw/templates/openclaw-env.canonical.j2` (after line ~`integration.type == 'notion'`): new `{% elif integration.type == 'brave' %}` branch writing `BRAVE_API_KEY={{ integration.brave_api_key | shq }}`.

### Playbooks — openclaw plugin install (Linux + macOS siblings)
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml`: NEW task block, `no_log: true`, idempotent install of `@openclaw/brave-plugin@<pinned-version>` ONLY when an attached integration is of type `brave`. Sentinel file `~/.openclaw/.brave-plugin-installed.<pinned-version>` used as the idempotency guard (`creates:`). Step ordering: plugin install runs BEFORE the config bytes copy, so a freshly-installed plugin sees the env on its first boot.
- `src/clawrium/platform/registry/openclaw/playbooks/configure_macos.yaml`: parallel macOS sibling using the same `npm` path but adjusted for `nvm` / Homebrew Node when present. No `when:` inside `configure.yaml` — dispatcher routes.
- Pinned version: `@openclaw/brave-plugin@2026.6.8` (current main; verified against `extensions/brave/package.json`). Stored as a single constant in `src/clawrium/platform/registry/openclaw/manifest.yaml` under `plugins.brave.version` so a future bump is a single-line change.

### Lifecycle — openclaw preflight + secrets cleanup
- `src/clawrium/core/lifecycle_canonical.py` — `sync_agent_canonical` (openclaw branch only): if any attached integration is type `brave`, run preflight that reads the on-host openclaw version (cached from `agent get` or fresh `openclaw --version`) and fails fast with `typer.Exit(1)` + actionable message if `< 2026.4.10`. Failure message: `"openclaw on <host> is <ver>; brave plugin requires >= 2026.4.10. Run 'clawctl agent upgrade <agent>' first."`
- `src/clawrium/core/lifecycle_canonical.py` — `remove_agent`: purge any per-agent secrets-store entries keyed `integration:brave:*` so a re-create of the agent does not inherit a stale credential. Mirrors the existing pattern for github/atlassian removal.

### CLI surface — reuse, do NOT add new commands
- `src/clawrium/cli/clawctl/integration.py` (`integration registry create` at ~line 179): no new subcommand. Existing `create` already accepts `--credential KEY=VALUE` repeatable. Verify `BRAVE_API_KEY` is the credential key the user passes. Add a `--api-key` convenience flag (mapped to `BRAVE_API_KEY`) and `--api-key-stdin` for non-TTY pipelines. **Positional credential is NOT accepted** for brave (W1 — shell-history / `ps` leak).
- `src/clawrium/cli/clawctl/agent/integration.py` (`agent integration attach` at ~line 55): no change to signature. The openclaw version preflight bites in `lifecycle_canonical`, not here, so attach stays cheap (no SSH).
- `--api-key-stdin` path: if `sys.stdin.isatty()` is False, the command MUST read from stdin and exit cleanly with non-zero if stdin is empty. No interactive `typer.prompt(..., hide_input=True)` in non-TTY contexts.
- `integration rotate` — alias for `integration registry edit --credential BRAVE_API_KEY=<new>` chained with a re-sync on every agent currently bound to the integration. New top-level subcommand. Confirmation prompt unless `--yes`.
- `integration registry delete <name>` — already exists. Verify it blocks deletion when any agent has the integration attached (existing pattern for github/linear). If `--force`, all attached agents are detached and re-synced as part of the same call. No silent leaks.

### GUI surface (W5)
- `src/clawrium/gui/routes/integrations.py` — add `brave` to the integration-kind registry mirror, including the credential schema (`BRAVE_API_KEY`, single field, `password=True`).
- `src/clawrium/gui/frontend/integrations.html` + Next.js source under `gui/web/`: add the brave card to the "Add integration" modal. Form field: one text input labeled "API key", masked, with the help text "Brave Search API subscription token (https://brave.com/search/api/)". Per-agent attach UI reuses the existing github attach component — no new wiring.
- API contract: `POST /api/integrations` accepting `{kind: "brave", credentials: {BRAVE_API_KEY: "..."}}` — same shape as github. The fan-out is N attachments on N agents from a SINGLE integration record. No GUI logic clones the secret per attach.
- The GUI MUST not log or return the raw key in any response payload. `describe` returns `Credentials: set` only.

### Secrets store + redaction (W1, W2)
- `src/clawrium/core/secrets.py` — no schema change; existing `secrets.json` (file mode 0600, owner = current user) accepts arbitrary integration keys.
- All Ansible tasks that touch the rendered env files or plugin install: `no_log: true`.
- Per-agent rendered env files on the host: file mode 0600, owner = agent service user (e.g. `wolf-i`). Already the convention; verify in tests.
- Event emission: `lifecycle_canonical` emits a structured `brave_integration_configured` event with `agent`, `host`, `integration_name`, `version_satisfied: bool`. **No** secret value. Mirrors the `gateway_token_rotated` event pattern (#437).
- `clawctl agent get`, `clawctl agent describe`, `clawctl integration registry describe`: all show `Credentials: set` only — never the value. Existing pattern; verify via unit test that prints/dumps don't leak.

### CHANGELOG (W9)
- `CHANGELOG.md` `## [Unreleased]` → `### Added`: single entry summarizing the new integration type, the per-agent matrix (incl. the `BRAVE_SEARCH_API_KEY` hermes name mapping), the openclaw plugin install + min-version constraint, and the GUI surface.

### Docs (mirror rule per AGENTS.md)
- `docs/agent-support/{hermes,zeroclaw,openclaw}.md` — add brave row to the integrations support matrix.
- `docs/agent-support/integrations/brave.md` — new page mirroring `integrations/github.md`. Include the name-mapping table, the zeroclaw `search_provider` constraint, the openclaw `minHostVersion ">=2026.4.10"`, and a "rotate the key" example.
- `website/docs/...` mirrors of all of the above.

## Test Strategy

### Unit — render layer (`tests/core/test_render.py`)
- **hermes byte-lock**: `render_hermes` with a single brave attachment produces `.hermes/.env` body that ends with `BRAVE_SEARCH_API_KEY=<value>`. Assert on the **rendered bytes** from `render_hermes`, not a mock. Existing fixture pattern (e.g. openclaw + litellm in #723) is the template.
- **zeroclaw byte-lock**: rendered `.zeroclaw/env` contains BOTH `Environment=BRAVE_API_KEY=...` AND `Environment=ZEROCLAW_web_search__search_provider="brave"`. Negative test: one without the other is not a valid render output.
- **openclaw byte-lock**: rendered `.openclaw/env` contains `BRAVE_API_KEY=<value>`.
- **Existing integrations byte-locks**: github / linear / notion / gitlab / atlassian byte-locks must remain byte-identical after the brave branch is added. Pinned to prevent silent drift.
- **Multi-integration**: a single agent with brave + github attached: both env vars present, in the documented order (existing template loop is stable).
- **Unsupported provider rejection** for each agent type: attaching `brave` to a `git`-typed integration on a clawrium-internal test agent (or other unrelated type) raises `AgentConfigError` with the existing message format.

### Unit — CLI (`tests/cli/clawctl/integration/test_*.py`)
- `CliRunner` tests for `integration registry create my-brave --type brave --api-key sk-xxx` — assert `_set_integration_credential` was called with `assert_called_once_with(exact_args)`.
- `--api-key-stdin` with isatty()=False and empty stdin → non-zero exit, clear error.
- `--api-key-stdin` with piped value → succeeds.
- Positional credential is rejected with usage error (not accepted as `BRAVE_API_KEY=...` shorthand).
- `integration rotate my-brave --api-key sk-new` re-syncs every bound agent; assert each `sync_agent_canonical` call.
- `integration registry delete` blocks when attached; `--force` detaches + re-syncs all.

### Unit — lifecycle (`tests/core/test_lifecycle_canonical.py`)
- Openclaw version preflight: stub `_get_host_openclaw_version` to return `"2026.3.13"` → `sync_agent_canonical` raises `typer.Exit(1)` with the documented message. Stub to `"2026.4.10"` → succeeds. Stub to `"2026.5.28"` → succeeds.
- Bearer rotation on brave attach/change (#437 invariant): every sync that touches `.zeroclaw/env` or `~/.openclaw/env` calls `_do_pair` and overwrites `hosts.json.gateway.auth`. Assert via mock on `_do_pair`.
- `remove_agent` purges `integration:brave:*` secret entries.

### Unit — GUI (`tests/gui/test_routes_integrations.py`)
- `POST /api/integrations` with `{kind: "brave", credentials: {BRAVE_API_KEY: "..."}}` → 201, integration registered, raw key absent from response body.
- `GET /api/integrations/my-brave` → returns `credentials_set: true` only.

### Integration — playbooks
- `tests/platform/test_openclaw_configure.py`: dry-run of the configure playbook with the new brave task; assert the install step runs ONLY when a brave-typed integration is attached AND the sentinel file is absent.
- `no_log: true` is asserted on every brave-touching task (lint check; reuse existing pattern).

### Live verification (manual, per agent)
- **hermes** (`espresso` on wolf-i): attach `my-brave`, `agent sync`, fire `web_search` tool through a chat turn, confirm Brave-routed result (Brave-specific result attribution or `BRAVE_SEARCH_API_KEY` log line).
- **zeroclaw** (`clawrium-d01`): attach, sync, fire `web_search`. The crucial assertion: `web_search` was actually routed via brave, not silently fell back to duckduckgo. If env-prefix override doesn't apply, the fallback plan kicks in (TOML deep-update of `[web_search]` section — bigger renderer change, separate PR if needed).
- **openclaw** (`wolf-i` after `clawctl agent upgrade wolf-i` to >=2026.4.10, OR a fresh openclaw install on another host): attach, sync clean, fire `openclaw agent --message "search the web for clawrium"`, confirm Brave-routed.

## Steps (sequencing for atomic single-PR landing — #723 precedent)

1. **Registry + render allow-lists** (1 commit). `INTEGRATION_TYPES["brave"]`, three `_*_SUPPORTED_INTEGRATIONS` sets. Tests pass without code changes elsewhere.
2. **Per-agent env template branches** (1 commit). hermes + zeroclaw + openclaw template edits. Byte-lock tests added in same commit (red → green).
3. **render_hermes / render_zeroclaw / render_openclaw view-builders** (1 commit). The integration view dict gets a `brave` branch in each. Hermes name-maps `BRAVE_API_KEY` → `BRAVE_SEARCH_API_KEY` here, not in the template Jinja conditional.
4. **CLI** — `--api-key` / `--api-key-stdin` convenience flags + `rotate` subcommand + isatty guards. CliRunner tests.
5. **Lifecycle** — openclaw version preflight, secrets cleanup on remove, event emission. Unit tests with mocked `_do_pair`.
6. **Openclaw playbook** — `configure.yaml` + `configure_macos.yaml` plugin install task, sentinel guard, `no_log: true`.
7. **GUI** — route + frontend card.
8. **Docs + CHANGELOG**.
9. **Live verification** (per agent), screenshots / logs attached to PR.

## Risks

- **Zeroclaw env-prefix override may not apply to web-search boot scope.** The `.env.example` documents the convention for channels/storage/gateway; web-search is in a different crate (`zeroclaw-tools`) and its boot-time config-load order may not pick up the prefix. If the live smoke shows routing still on duckduckgo even with the env set, fallback is a TOML deep-update of `[web_search]` in `zeroclaw-config.toml.j2`. Documented in the issue body. The fallback would grow the renderer surface (writing to TOML) and bumps complexity — worth tracking as a separate sub-issue if it lands.
- **Openclaw plugin npm install network dependency.** `npm install @openclaw/brave-plugin@2026.6.8` requires registry access from the agent host. On air-gapped hosts this breaks. Mitigation: idempotency sentinel makes re-runs safe; failure surfaces with a clear "plugin install failed; provide an offline mirror or install manually" message. Not blocking for v1 landing.
- **Min-version preflight + existing fleet.** Fleet members on openclaw < 2026.4.10 (e.g. wolf-i at 2026.3.13) will fail attach. Operator must `clawctl agent upgrade <agent>` first. This is intentional friction — silently working with a missing plugin is worse.
- **Single render path for hermes (#622).** If any reviewer suggests "just template the env at Ansible time", the answer is no — that reintroduces the #622 bug class. Plan pins `ansible.builtin.copy` of pre-rendered bytes.

## Subtasks

None. Single contained PR matching the #723 precedent. The work spans 3 agent types but the changes are symmetric and the test matrix is single-PR-sized. If the openclaw plugin-install playbook integration drifts in scope (live verification surfaces unexpected install path issues on macOS, etc.), spin off as a follow-up; do not preemptively split.

## Prompt log

### Plan

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-16T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 734
```

Triggered after an ATX review of the earlier prompt-log-only `.itx/734/00_PLAN.md` flagged 7 blockers (B1–B7) and 10 warnings (W1–W10). The plan above addresses each blocker explicitly:

- **B1** (no plan) — this section.
- **B2** (#437 bearer re-pair) — Lifecycle Invariants section explicit; CLI `attach` reuses `sync_agent_canonical` which calls `_do_pair()` unconditionally. No new restart path.
- **B3** (#622 hermes single render path) — Lifecycle Invariants pin `ansible.builtin.copy` of pre-rendered bytes; byte-lock test in Test Strategy.
- **B4** (test plan) — Test Strategy section enumerates per-agent render byte-locks, CLI CliRunner tests, lifecycle preflight tests, GUI tests, playbook dry-run, live smoke. Including secrets-redaction assertions.
- **B5** (CLI command surface) — CLI surface section: `--api-key` + `--api-key-stdin` (TTY-guarded), `rotate`, `delete` blocking, no positional credential, openclaw version preflight in `lifecycle_canonical`.
- **B6** (Ansible + OS fork) — Files to Modify lists Linux `configure.yaml` and `configure_macos.yaml` siblings with dispatcher-only routing; pinned plugin version in `manifest.yaml`.
- **B7** (plugin install lifecycle stage) — Files to Modify routes the plugin install through `configure.yaml` (idempotent, post-attach, pre-restart), NOT `install.yaml` (one-shot).

Warnings W1–W10 are each addressed in the Secrets, GUI, Lifecycle, or CHANGELOG sections.
