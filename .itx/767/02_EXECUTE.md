# Issue #767 — Phase 1: openclaw workspace overlay end-to-end on Ubuntu

Execution log for subtask #767 of parent #760. Drives the shared
foundation (workspace_sync module, manifest loader, CLI flags, install
scaffold) alongside the openclaw-specific manifest entry and Ansible
playbook.

Source plan: [`../760/00_PLAN.md`](../760/00_PLAN.md). Execution
scaffold: [`../760/01_EXECUTION.md`](../760/01_EXECUTION.md).

## What landed

**Code:**

- `src/clawrium/core/workspace_sync.py` — NEW. Enumerator + stager +
  push_workspace_phase helper. No paramiko, no OS literals; OS seam is
  `core/playbook_resolver.py`. Secret-pattern files (`*.key`, `*.pem`,
  `*.env`, `.env`, `*credentials*`, `*secret*`, `*token*`,
  `*password*`) floor to mode 0600. NDJSON state field is the frozen
  enum `{queued, pushed, excluded, skipped, failed, complete}`. All
  operator-controlled strings pass through
  `cli/output/_sanitize.py:sanitize_passthrough` before emission (W4
  iter-1, W3 iter-3).
- `src/clawrium/core/registry.py` — typed `WorkspaceOverlayConfig`
  TypedDict added to `FeaturesConfig`; `_validate_workspace_overlay`
  handles missing / null-excludes / trailing-slash / malformed entries
  (U31 iter-2).
- `src/clawrium/core/lifecycle_canonical.py` —
  `CanonicalSyncResult` carries `workspace_files_pushed` /
  `workspace_files_excluded`. `sync_agent_canonical` gained
  `push_workspace`, `workspace_only`, `dry_run` kwargs. Phase order
  matches §1.4: workspace push lands between canonical write loop and
  restart; workspace failure short-circuits before restart (W2 iter-1,
  I8). `--workspace-only` short-circuits before render and intentionally
  does NOT transition state (W5 iter-3).
- `src/clawrium/core/lifecycle.py:configure_agent` — workspace push
  fires after the configure playbook succeeds and `update_host`
  commits, so non-CLI callers (install retries, GUI integration,
  programmatic flows) inherit the overlay through this layer
  (W3 iter-3). Workspace failure here logs a warning rather than
  failing the configure (canonical configure already succeeded; next
  sync will surface the workspace error with full diagnostics).
- `src/clawrium/core/install.py` — opportunistic local workspace dir
  scaffold under
  `~/.config/clawrium/agents/<type>/<name>/workspace/`. Mode 0700.
  Idempotent on pre-existing scaffolds (U18). Non-fatal on failure.
- `src/clawrium/cli/clawctl/agent/sync.py` —
  - `--workspace-only` (push overlay only) and `--no-restart`
    (canonical + overlay, no restart) added.
  - `--workspace` is a HARD ERROR (BREAKING) routed through
    `emit_error` with exit code 2 (U32, W6 iter-2).
  - `--workspace-only --diff` mutex (I7).
  - Phase pre-emission updated to skip restart/verify when
    `--workspace-only` or `--no-restart`.
- `src/clawrium/cli/clawctl/agent/__init__.py` — short-help string
  updated to mention workspace overlay (W10 iter-2).
- `src/clawrium/platform/registry/openclaw/manifest.yaml` —
  `features.workspace_overlay.destination_root: ~/.openclaw/workspace`,
  empty excludes.
- `src/clawrium/platform/registry/openclaw/playbooks/workspace.yaml`
  — NEW. `become_user: {{ agent_name }}`. Asserts agent_name slug,
  workspace_dest_root starts with `/home/{{ agent_name }}/`,
  staging_dir under clawrium staging tree, each `item.rel` is a safe
  relative path. NEVER references `ansible_user_dir` (B1 iter-3).
  `ansible.builtin.copy` with `mode: "{{ item.mode }}"`, `follow: no`.
- `src/clawrium/platform/registry/openclaw/playbooks/workspace_macos.yaml`
  — NEW stub. Single Ansible `fail:` task; macOS support deferred to
  follow-up subtasks (#760 #4–#6) (W9 iter-3 — single error surface).

**Docs:**

- `AGENTS.md` — new **Workspace Overlay (issue #760)** section
  documents the manifest contract, per-type destinations,
  Ansible-only architecture, secret-pattern floor, and trust boundary.
- `CHANGELOG.md` — `### BREAKING` entry for `--workspace` removal and
  `### Added` entry for the workspace overlay feature (W1 iter-3 hook
  reminder: BREAKING lands in THIS PR, not deferred).

**Tests (47 new pass; 3712 total green):**

- `tests/test_workspace_sync.py` — 30 unit tests covering openclaw
  subset of plan §3.1 (U2/U4/U6/U7/U9/U10/U12/U13/U14/U15/U19/U20/U21/
  U22/U23/U24/U35).
- `tests/test_manifest_workspace_overlay.py` — 11 tests covering U31
  iter-2 (parser edge cases), U2/U4 (openclaw pins).
- `tests/cli/clawctl/test_workspace_bidi_safety.py` — bidi
  spoofing regression (W3 iter-3). Centralised sanitiser already
  exists at `cli/output/_sanitize.py:sanitize_passthrough`.
- `tests/cli/clawctl/agent/test_sync_workspace_flags.py` — CLI
  contract: `--workspace` hard error (U32), mutex (I7),
  `--workspace-only` short-circuits (I4), workspace-phase failure
  exits non-zero (S-cli-ux iter-3 hook).
- `tests/cli/clawctl/agent/test_sync.py` — updated two existing tests
  to match the renamed flag (`--workspace` → `--no-restart`) and the
  new `sync_agent_canonical` kwargs.

## Out of scope for this subtask (deferred to siblings under #760)

- **zeroclaw vertical (Phase 2)** — bearer-rotation invariant on top
  of the shared foundation. The `workspace_only` short-circuit in
  `sync_agent_canonical` carries a `NOTE(zeroclaw bearer rotation)`
  comment marking where Phase 2 wires the unconditional
  `_zeroclaw_repair_after_start` call. Openclaw has no bearer to
  rotate.
- **hermes vertical (Phase 3)** — hermes manifest entry + workspace
  playbook + the full exclude list (`config.yaml`, `.env`,
  `auth.json`, `state.db*`, `sessions/`, `logs/`, `skills/clawrium/`).
  U3 / U33 / I3 / I14 land with that subtask.
- **macOS verticals (Phases 4–6)** — the `workspace_macos.yaml` stub
  here makes the dispatcher contract live; the stubs are replaced as
  each macOS subtask lands.
- **E2E on wolf-i** — captured in
  `.itx/760/02_E2E_openclaw_wolf-i.md`; this PR ships the unit +
  integration coverage. Real-host E2E is a separate run.

## Lint + tests

- `make lint-py` → All checks passed!
- `make test-py` → 3712 passed, 2 skipped.

## ATX iteration log

See `atx-session.json` in this directory.
