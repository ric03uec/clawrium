# Issue #1071 — Agents: remove chat / memory / exec / audit / secret / apply / diff / workspace_sync / nemoclaw; gate web UI tunnel

## Overview

End-to-end deletion milestone that follows the #1072 skills-removal pattern. One bundled PR (not a subtask tree) — the surfaces are tightly coupled (CLI → core → GUI → registry → docs), and #1072 shipped the same shape in a single PR. The plan below is the execution order a single PR walks through.

**Delivery slot:** D3 of v26.11.0 — merges after #1075 (GUI shell) and alongside #1072 (skills; already merged at `d65f581e`). #1076 (channels→integrations) is separate (D8).

## Scope summary

| Area | Delete | Edit |
|---|---|---|
| CLI | `cli/clawctl/agent/{chat,memory,exec,audit,secret}.py`, `cli/clawctl/{apply,diff,audit}.py`, `cli/clawctl/doctor/nemoclaw.py` | `cli/clawctl/agent/__init__.py`, `cli/clawctl/__init__.py`, `cli/clawctl/agent/{open,port_forward,configure}.py` (gate + drop stages), `cli/clawctl/doctor/__init__.py` |
| Core | `core/chat*.py` (all), `core/memory.py`, `core/agent_exec.py`, `core/workspace_sync.py`, `core/nemoclaw.py` | `core/lifecycle.py`, `core/lifecycle_canonical.py`, `core/install.py`, `core/secrets.py` (keep provider/integration paths), `core/web_ui.py`, `core/web_ui_tunnel.py`, `core/registry.py`, `core/manifest/{schema,parser,differ,state}.py` |
| GUI | Chat/Exec/Memory tab components, sidebar Scheduled Jobs + Agent Builder stubs | `gui/routes/agents.py` (drop chat/exec/memory handlers; add chat-moved help screen), `gui/routes/__init__.py`, Next.js shell under `gui/` (tab nav, sidebar, page routes) |
| Registry | per-agent `playbooks/{workspace,workspace_macos,exec,exec_macos,memory_*}.yaml`, hermes `filter_plugins/`, openclaw `install_nemoclaw*.yaml` + `nemoclaw_*.yaml`, `playbooks/filter_plugins/` under zeroclaw/hermes | per-agent `manifest.yaml` (drop `features.workspace_overlay`; openclaw drops nemoclaw role from manifest) |
| Docs | `docs/agent-support/memory.md` | `README.md`, `docs/agent-onboarding.md`, `docs/index.md`, `docs/agent-support/channels/cli.md`, per-agent docs, `CHANGELOG.md` |
| Tests | all `test_chat_*`, `test_core_memory`, `test_agent_exec`, `test_workspace_sync`, nemoclaw tests, exec-related manifest tests | `tests/cli/clawctl/agent/test_{open,port_forward}.py` (new gating assertions), registry/manifest tests |
| Pyproject | — | `pyproject.toml` (drop wheel force-includes for removed trees) |

## Execution phases (same PR)

### Phase 1 — CLI surfaces

Delete the top-level command modules and stub registrations.

**Delete:**
- `src/clawrium/cli/clawctl/agent/chat.py`
- `src/clawrium/cli/clawctl/agent/memory.py`
- `src/clawrium/cli/clawctl/agent/exec.py`
- `src/clawrium/cli/clawctl/agent/audit.py`
- `src/clawrium/cli/clawctl/agent/secret.py`
- `src/clawrium/cli/clawctl/audit.py`
- `src/clawrium/cli/clawctl/apply.py`
- `src/clawrium/cli/clawctl/diff.py`
- `src/clawrium/cli/clawctl/doctor/nemoclaw.py`

**Explicitly kept (adjacent / disambiguation):**
- `src/clawrium/cli/clawctl/agent/delete.py` — per-agent `clawctl agent delete <name>` CRUD. Never in scope.
- `src/clawrium/cli/clawctl/delete_file.py` — `clawctl delete -f fleet.yaml` declarative delete. Issue text removes only `apply` + `diff`; the file-driven delete stays.

**Edit:**
- `src/clawrium/cli/clawctl/agent/__init__.py` — drop Typer subcommand registrations for `chat`, `memory`, `exec`, `audit`, `secret`.
- `src/clawrium/cli/clawctl/__init__.py` — drop registrations for `apply`, `diff`, `audit`.
- `src/clawrium/cli/clawctl/doctor/__init__.py` — drop `nemoclaw` subcommand.
- `src/clawrium/cli/clawctl/agent/configure.py` — remove `memory` stage from any wizard / help text.

### Phase 2 — Web UI tunnel gating (CLI + core)

`clawctl agent open` + `clawctl agent port-forward` must reject the daemonless install-only runtimes (Claude Code, Codex, Pi) and continue working for OpenClaw, Hermes, ZeroClaw.

**Edit:**
- `src/clawrium/cli/clawctl/agent/open.py` — look up manifest `features.web_ui` via `core.web_ui.resolve_web_ui` (already the gate); add explicit refusal for agent_types ∈ {`claude`, `codex`, `pi`} with exit-code-1 help message pointing to SSH.
- `src/clawrium/cli/clawctl/agent/port_forward.py` — same gate.
- `src/clawrium/core/web_ui.py` — if `features.web_ui` is absent AND agent_type is one of the three install-only runtimes, return a typed "not supported" result so the CLI messages match.
- `src/clawrium/core/web_ui_tunnel.py` — no change to the SSH forwarder itself; gating lives above it.

### Phase 3 — Core module deletions

Delete the chat / memory / exec / workspace / nemoclaw modules and their test files.

**Delete (core):**
- `src/clawrium/core/chat.py`, `chat_claude.py`, `chat_codex.py`, `chat_hermes.py`, `chat_pi.py`, `chat_zeroclaw.py`, `chat_ethos.py`
- `src/clawrium/core/memory.py`
- `src/clawrium/core/agent_exec.py`
- `src/clawrium/core/workspace_sync.py`
- `src/clawrium/core/nemoclaw.py`

**Edit (core — no full delete):**
- `src/clawrium/core/lifecycle.py` — drop any call to `workspace_sync.push_workspace_phase`; drop `memory` / `exec` lifecycle stages if present. Preserve the inline `_cleanup_agent_state_dir` pattern from #1072.
- `src/clawrium/core/lifecycle_canonical.py` — drop workspace-overlay phase entirely (both the `push_workspace_phase` call and the pre-phase staging dir setup). Zeroclaw's gateway-bearer rotation (issue #437) must still run — scope the delete to the overlay path only.
- `src/clawrium/core/install.py` — drop the `workspace`/`secrets.agent` entries from the #816 attachment-preserve snapshot; keep `providers`, `channels`, `integrations` survival paths. Follow the `skills` removal shape in #1072 (test a snapshot regression).
- `src/clawrium/core/secrets.py` — remove agent-level secret put/get/list paths wired to the `clawctl agent secret` CLI. Keep provider-credential and integration-credential paths (grep for the exact shared helpers in use by `core/provider_attachments.py` and `core/integrations.py`).
- `src/clawrium/core/registry.py` — drop `WorkspaceOverlayConfig` dataclass, `_validate_workspace_overlay`, and `features.workspace_overlay` schema recognition. Any workspace-overlay block in a third-party manifest becomes an unknown-feature warning.
- `src/clawrium/core/manifest/schema.py`, `parser.py`, `differ.py`, `state.py` — drop fields analogous to the #1072 `skills` strip: anywhere `AgentSpec`, `ActualAgent`, `AttachOp.resource_kind` mention `workspace` / `memory` / `secrets.agent`, drop them. Mirror #1072's scope — not the provider / integration fields.

### Phase 4 — NemoClaw doctor surface strip (openclaw infra stays)

**Scope correction** (2026-11-27): NemoClaw is openclaw's upstream
runtime sandbox and MUST stay installed/onboarded on openclaw hosts.
The removal is narrow — only the operator-facing doctor surface and
the Python pin module. The install playbook, onboarding helper, and
openclaw manifest's `runtime.nemoclaw` block all stay.

**Delete:**
- `src/clawrium/core/nemoclaw.py` — the pin module
  (`NEMOCLAW_VERSION`, `INSTALL_SH_SHA256`, `install_sh_url()`).
  Doctor probe at `cli/clawctl/doctor/nemoclaw.py` already removed
  in Phase 1 (whole `doctor` group deleted).

**Edit:**
- `src/clawrium/platform/registry/openclaw/playbooks/install_nemoclaw.yaml`
  (and `_macos` sibling) — keep the runbook; make its `vars:`
  self-contained by inlining the `nemoclaw_version` and
  `nemoclaw_install_sh_sha256` literals that previously rode via
  `core/nemoclaw.py` constants.
- `tests/cli/clawctl/agent/test_create.py` — rewrite the pin
  lockstep assertion to read the playbook YAML directly instead of
  importing `core.nemoclaw.NEMOCLAW_VERSION`.
- Any other Python caller of `clawrium.core.nemoclaw` surfaced by
  grep.

**Explicitly kept (do not touch):**
- `install_nemoclaw.yaml`, `nemoclaw_onboard.yaml`,
  `nemoclaw_status.yaml`, `install_nemoclaw_macos.yaml` — the
  openclaw install + onboard + status playbooks.
- `_openclaw_nemoclaw_onboard` in
  `src/clawrium/core/lifecycle_canonical.py` — the sync-time onboard
  helper that openclaw agents rely on.
- `runtime.nemoclaw` block in
  `src/clawrium/platform/registry/openclaw/manifest.yaml`.
- Every openclaw-side `_openclaw_nemoclaw_*` playbook + manifest
  wiring.

### Phase 5 — Registry manifests + per-agent playbooks

**Delete per-agent playbooks (hermes, openclaw, zeroclaw):**
- `playbooks/workspace.yaml`, `playbooks/workspace_macos.yaml`
- `playbooks/exec.yaml`, `playbooks/exec_macos.yaml`
- `playbooks/memory_delete.yaml`, `memory_info.yaml`, `memory_read.yaml`, `memory_write.yaml`
- `playbooks/filter_plugins/` (hermes + zeroclaw — these host the `workspace_excluded` Jinja filter; dead without the overlay).

**Edit:**
- `src/clawrium/platform/registry/hermes/manifest.yaml` — drop `features.workspace_overlay` block.
- `src/clawrium/platform/registry/openclaw/manifest.yaml` — drop `features.workspace_overlay` block.
- `src/clawrium/platform/registry/zeroclaw/manifest.yaml` — drop `features.workspace_overlay` block.

### Phase 6 — GUI

Agent-detail Tabs reduce to **Overview, Configuration, Logs**. Chat URL redirects to a static "chat moved to host" screen. Sidebar drops the two coming-soon stubs.

**Edit (Python routes):**
- `src/clawrium/gui/routes/agents.py` — delete `/agents/<key>/chat`, `/agents/<key>/exec`, `/agents/<key>/memory` endpoints and WebSocket handlers; keep overview / configuration / logs / open-UI / pairing handlers. Replace the chat-URL handler with a static help response ("chat moved to host; see `clawctl agent shell`").
- `src/clawrium/gui/routes/_common.py` — remove chat-backend factories, memory helpers.
- `src/clawrium/gui/routes/fleet.py` — remove the `_PAIRING_AGENT_TYPES` branches that exist only to support the removed chat flow; keep the openclaw bearer-token / `connection-token` surface (still needed for `clawctl agent open`).
- `src/clawrium/gui/server.py` — remove dead route imports after the above.

**Edit (Next.js source under `gui/`):**
- Remove Chat / Exec / Memory tab components from the agent-detail shell.
- Replace chat-page route with the static help screen.
- Remove the sidebar entries `Scheduled Jobs` and `Agent Builder`. Delete `coming-soon-modal` component if no remaining consumer.
- Rebuild the Next.js static output into `src/clawrium/gui/frontend/` (same path `make`/`pyproject.toml` already packages).

### Phase 7 — Docs

**Delete:**
- `docs/agent-support/memory.md`.
- Any mirror under `website/docs/` if one exists (the installation/host-setup convention in AGENTS.md implies there may be mirrored memory docs).

**Edit:**
- `README.md` — strip `agent chat`, `agent exec`, `agent memory`, `agent audit`, `agent secret`, top-level `apply` / `diff` mentions. Keep install + `agent configure/start/stop/sync/shell/open/port-forward` usage.
- `docs/agent-onboarding.md` — remove chat/exec/memory/audit/secret/apply/diff examples.
- `docs/index.md` — remove the removed-subsystem links.
- `docs/agent-support/channels/cli.md` — all `clawctl agent chat` examples out.
- `docs/agent-support/<agent>.md` — remove per-agent chat/exec/memory sections for all agents.
- `CHANGELOG.md [Unreleased]` — single `### BREAKING` block documenting every removal (CLI commands, core modules, workspace overlay, agent-level secrets, nemoclaw, GUI tabs, web-UI gating). State explicitly: pre-v26.11.0 on-disk state for chat / memory / workspace / agent-secrets / audit is **ignored on upgrade; wipe stance** (matches issue DoD). This is non-negotiable per AGENTS.md changelog rules.

### Phase 8 — Tests + pyproject

**Delete whole test files:**
- `tests/**/test_chat_*.py` and `tests/test_core_chat.py` (every chat variant)
- `tests/**/test_core_memory.py`, `tests/test_tui/test_tui_chat.py`
- `tests/**/test_agent_exec.py`, `tests/test_exec_binary_discovery.py`, `tests/test_gui_agent_exec_route.py`
- `tests/test_workspace_sync.py`
- `tests/**/test_nemoclaw*.py`, `tests/cli/clawctl/doctor/test_nemoclaw.py`
- `tests/cli/clawctl/agent/test_{chat,memory,exec,audit,secret}.py`
- `tests/cli/clawctl/{audit,apply,diff}/` trees and loose `test_apply.py` / `test_diff.py`
- `tests/core/test_secrets_keying.py` **only** for the agent-secrets paths — keep provider/integration key tests (split-file if needed).

**Edit / add:**
- `tests/cli/clawctl/agent/test_open.py` — add assertion that Claude Code / Codex / Pi agents get exit-code-1 + "chat moved to host"-style help; OpenClaw / Hermes / ZeroClaw continue to work.
- `tests/cli/clawctl/agent/test_port_forward.py` — same gating assertion.
- `tests/core/test_install_attachments.py` (or the equivalent file touched by #1072 / #816) — add a regression test that `workspace` and agent-level `secrets` keys in a pre-v26.11.0 `hosts.json` are **dropped** on re-install (not silently preserved). Mirror the #1072 `skills`-drop regression test.
- `tests/core/test_registry.py` — assert `features.workspace_overlay` in a third-party manifest emits an unknown-feature warning.

**pyproject.toml:** drop wheel force-includes for the removed trees (skills tree is already gone from #1072 — mirror that edit, this time removing anything that forces `core/chat*` / per-agent `memory_*.yaml` / per-agent `workspace*.yaml` into the wheel). Verify `uv build` still produces a wheel that imports.

## Acceptance-criteria → verification map

| Acceptance criterion | How we verify |
|---|---|
| Grep for `clawctl agent chat / exec / memory / audit / secret`, `clawctl apply`, `clawctl diff` zero-hits in `src/` and `tests/` at v26.11.0 tag | `scripts/` one-liner grep recorded in PR body; add a unit test that greps the compiled Typer command tree. |
| GUI agent-detail tabs reduced to Overview / Configuration / Logs | Playwright or existing GUI smoke test under `gui/e2e/`. |
| `clawctl agent configure` has no `memory` or chat stages; `--help` reflects | Typer help snapshot test. |
| `clawctl agent open` / `port-forward` fails for Claude Code / Codex / Pi, works for OpenClaw / Hermes / ZeroClaw | New tests in Phase 8. |
| `core/workspace_sync.py` deleted; no code path pushes workspace files; BREAKING entry in `CHANGELOG.md [Unreleased]` | Grep + changelog review. |
| `core/nemoclaw.py` and `cli/clawctl/doctor/nemoclaw.py` deleted; nemoclaw absent from `clawctl agent registry` | Grep + CLI output test. |
| Sidebar does not render Scheduled Jobs / Agent Builder; `coming-soon-modal` removed if no consumer | Playwright smoke + grep. |
| Every AC has a passing test or recorded grep/CLI transcript | PR body records grep transcripts for the removal-only ACs (no test is cheaper than a grep assertion). |

## Risks & non-negotiables

- **CHANGELOG `BREAKING` block.** Per AGENTS.md changelog rules, an undocumented breaking change is a release blocker. This PR's single biggest failure mode is shipping without the wipe-stance callout. Treat the changelog as part of the code review, not an afterthought.
- **Zeroclaw gateway bearer rotation (#437) must still fire on `clawctl agent sync`.** The `lifecycle_canonical.sync_agent_canonical` surgery in Phase 3 scopes to the overlay path; don't touch the bearer-mint call.
- **Secrets split is the trickiest edit.** `core/secrets.py` backs the agent-level `secret` CLI AND the provider / integration credential layer. The issue explicitly says keep the latter. Before deleting any helper, grep callers from `core/provider_attachments.py`, `core/integrations.py`, `cli/clawctl/provider.py`, `cli/clawctl/integration.py`. Split-file if cleaner than threading a kill-list.
- **Hermes workspace-overlay excludes include daemon SQLite WAL files.** AGENTS.md flags that overlaying the SQLite state while the daemon holds the WAL corrupts the DB. The overlay is going away entirely, so the risk reverses: on first `sync` after upgrade, operators must not be writing to `~/.hermes/` via the (now-deleted) overlay path. Zero code path pushes workspace files post-removal — belt-and-suspenders grep `push_workspace_phase` and `workspace_sync` across the repo.
- **GUI frontend is Next.js built into `src/clawrium/gui/frontend/`.** The source tree is `gui/` at repo root. Both the source edit AND the rebuild commit need to land — the `pyproject.toml` includes the built HTML, not the source. Verify `make` / `uv build` picks up the new static output.
- **Real-host UAT required pre-merge** per saved feedback: no PR without real-host end-to-end UAT. Pick one wolf-i or mac-test host with openclaw + hermes already installed; verify `agent sync` doesn't error on the vanished overlay phase, `agent open` still tunnels, `agent shell` works, `agent chat` / `agent exec` / `agent memory` / `agent audit` / `agent secret` exit with command-not-found. Record in PR body.
- **ATX review is not skippable** per saved feedback. Deletion diffs still need Rating > 3/5 and B-item resolution.

## Subtasks

None — single bundled PR, following the #1072 shape and matching the saved preference for bundled refactors.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-11-26T22:30:00Z
**Model**: claude-opus-4-7[1m]

```prompt
plan 1071
```

**Output**: `.itx/1071/00_PLAN.md` — 8-phase single-PR execution plan for the v26.11.0 chat/memory/exec/audit/secret/apply/diff/workspace_sync/nemoclaw/web-UI-gate removal milestone.

</details>
