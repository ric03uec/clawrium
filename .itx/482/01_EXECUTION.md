# Issue #482 — Execution Log

Parent issue: #478 (Phase 2 of 3)
Stacked on: `issue-481-manifest-web-ui` (PR #486)

## Summary of work landed

- `src/clawrium/core/install.py`:
  - Compute per-instance hermes dashboard port via
    `45000 + (md5(agent_name) % 2000)` with collision-bump (wraps within
    45000..46999) when another agent on the same host owns the slot.
  - Capture existing port BEFORE `set_installing` wipes the agent record
    (`preserved_dashboard_port`), so re-install is a no-op for the port.
  - Persist `config.dashboard = { enabled, host: 127.0.0.1, port }` to
    `hosts.json.agents.<name>` in `set_installed`.
  - Pass `dashboard_port` as an Ansible inventory var to the install
    playbook.
- `src/clawrium/platform/registry/hermes/playbooks/install.yaml`:
  - Resolve hermes interpreter from `~/.local/bin/hermes` shebang
    (rather than guessing the uv venv layout — uv has moved paths
    between releases) and `pip install --upgrade hermes-agent[web,pty]`
    into it.
  - Verify `node --version` ≥ 18; fail with an apt remediation message.
  - Drop `hermes-dashboard-<agent_name>.service` with
    `PartOf=hermes-<agent_name>.service`, `Also=` in `[Install]`,
    `ExecStart=/home/<user>/.local/bin/hermes dashboard --host 127.0.0.1
    --port {{ dashboard_port }} --no-open --tui`, and
    `Environment=HERMES_DASHBOARD_TUI=1`.
- `src/clawrium/platform/registry/hermes/playbooks/start.yaml`:
  - Re-render dashboard unit on every start (idempotent), guarded on
    `dashboard_port is defined` so legacy agents continue to start.
  - Enable + start the dashboard unit when its file exists.
- `src/clawrium/platform/registry/hermes/playbooks/stop.yaml`:
  - Stop + disable dashboard unit BEFORE the gateway unit (PartOf
    propagation also covers this, but explicit stop is robust against
    PartOf misconfiguration on existing hosts).
- `src/clawrium/platform/registry/hermes/playbooks/remove.yaml`:
  - Stop / disable / remove dashboard unit file alongside gateway unit.
- `src/clawrium/core/lifecycle.py`:
  - `_run_lifecycle_playbook` reads `config.dashboard.port` from the
    agent record and injects it as `dashboard_port` for hermes agents,
    so start/stop/remove can re-render the dashboard unit.
- Tests:
  - 4 new tests in `tests/test_install.py` covering: deterministic port
    hashing, persistence to `hosts.json` + ansible inventory, collision
    bump, re-install port preservation.
  - 9 new tests in `tests/test_hermes_playbooks.py` covering: extras
    install, shebang-based interpreter discovery, Node ≥ 18 gate,
    dashboard unit structure (PartOf, Also, ExecStart, env, loopback
    bind), and lifecycle (start/stop/remove) integration with the
    dashboard unit.
- `make test-py` → 2469 passed, 6 skipped. `make lint-py` → clean.

## Out of scope (deferred to Phase 3 / #483)

- CLI `clm agent open`, tunnel manager, GUI button, docs.

---

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-22T16:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 482 --pr-base=issue-481-manifest-web-ui
```

**Output**: Implemented hermes dashboard port persistence + companion
systemd unit + lifecycle propagation. PR opened against
`issue-481-manifest-web-ui` (stacked on top of PR #486 / Phase 1).
ATX review attempted via `mcp__atx__request_review` — not available in
this entry path; recorded as `[ENVIRONMENT]` Callout on the PR.
