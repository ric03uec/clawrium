# Issue #478 — Execution Scaffolding

**Mode:** multi-phase (3 phases, strict A → B → C dependency chain)

Plan reference: [`.itx/478/00_PLAN.md`](./00_PLAN.md).

## Phase Topology

```
Phase 1 (478-A) ──► Phase 2 (478-B) ──► Phase 3 (478-C) ──► hermes "Open Agent UI" lands
```

Phases run **sequentially**. Each lands as its own PR so review surface stays small.

- Phase 1 is pure mechanism (manifest schema + resolver, no UI, no playbook, no lifecycle).
- Phase 2 changes the agent host (install playbook + systemd) and requires Phase 1's schema in place.
- Phase 3 wires the user-visible surfaces (CLI + GUI + tunnel manager + docs) and requires both prior phases.

No two phases touch the same files in conflicting ways, but the runtime dependency is real: Phase 3's CLI/GUI calls into Phase 2's persisted `dashboard.port` and Phase 1's `features.web_ui` field. Do not parallelise.

---

### Phase 1 — Manifest schema + resolver (subtask 478-A)

**Complexity:** simple
**Dependencies:** None

**Entry Criteria:**
- `main` is green (`make test`, `make lint`).
- Issue #478 is in `ready` state.

**Files Affected:**
- `src/clawrium/core/registry.py` — extend `FeaturesConfig` TypedDict + `_validate_features` to recognize `web_ui` block. Closed enum on `bind` (`loopback` only in this iteration). Validate `default_port` is a positive int; `port_field` is a non-empty string.
- `src/clawrium/platform/registry/hermes/manifest.yaml` — add `features.web_ui` block (`enabled: true`, `bind: loopback`, `default_port: 9119`, `port_field: dashboard.port`).
- `src/clawrium/core/web_ui.py` *(new)* — small resolver: given `(agent_key) -> ResolvedUI{ host, remote_port, bind, ssh_config } | None`. No URL construction here. Returns `None` for agents whose manifest lacks `features.web_ui`.
- `tests/test_registry.py` — manifest validation: accept valid `web_ui`, reject invalid `bind`, reject missing `default_port`, reject non-bool `enabled`.
- `tests/test_web_ui_resolver.py` *(new)* — hermes returns expected `ResolvedUI`; openclaw/zeroclaw return `None`; missing/stopped agent returns `None`.

**Exit Criteria:**
- `make test` green (new tests included).
- `make lint` clean.
- `load_manifest("hermes")` returns a manifest with `features.web_ui.enabled == True`.
- `load_manifest("openclaw")` and `load_manifest("zeroclaw")` continue to work unchanged.
- Hermes manifest validator round-trip is byte-stable (no field reorder regression).
- No behavior change visible to existing CLI/GUI surfaces (zero runtime users of `features.web_ui` exist yet).

---

### Phase 2 — Hermes install / systemd / port persistence (subtask 478-B)

**Complexity:** moderate
**Dependencies:** Phase 1 (478-A) merged to `main`

**Entry Criteria:**
- Phase 1 merged; `features.web_ui` schema available.
- A real hermes host is available for manual install verification (homelab box reachable via SSH).
- Existing hermes agents (if any) are stopped or the operator is OK with restart during validation.

**Files Affected:**
- `src/clawrium/platform/registry/hermes/playbooks/install.yaml` — after the existing upstream installer step:
  - Add task to install `hermes-agent[web,pty]` extras into the same interpreter the upstream installer uses. Verify the exact venv/python path during execution (do **not** guess — read what the installer outputs).
  - Verify `node --version` ≥ 18; fail with remediation message if absent (Node is needed for the dashboard SPA build on first launch).
  - Drop a second systemd unit at `/etc/systemd/system/hermes-dashboard-<agent_name>.service` with `PartOf=hermes-<agent_name>.service`, `Also=hermes-<agent_name>.service` in `[Install]`, and `ExecStart=/home/<agent_name>/.local/bin/hermes dashboard --host 127.0.0.1 --port <dashboard_port> --no-open --tui`. `Environment=HERMES_DASHBOARD_TUI=1`.
- `src/clawrium/core/install.py` — compute `dashboard_port = 45000 + (hash(agent_name) % 2000)`; check collision against other agents on the same host and bump by +1 until free. Persist to `hosts.json.agents.<name>.config.dashboard = { enabled: true, host: "127.0.0.1", port: <int> }`. On re-install / reconfigure, preserve existing port from `hosts.json` rather than recompute.
- `src/clawrium/core/lifecycle.py` — wherever `start_agent` / `stop_agent` / `restart_agent` invoke the gateway systemd unit, add a parallel call for `hermes-dashboard-<agent_name>.service`. `PartOf` should propagate stop/restart automatically but we still need explicit `systemctl enable` of the dashboard unit on first start. Idempotent: if already enabled, no-op.
- `src/clawrium/platform/registry/hermes/playbooks/start.yaml` / `stop.yaml` / `remove.yaml` — extend to also enable/start, stop, and clean up the dashboard unit file alongside the gateway unit.
- `tests/test_install.py` — new tests: dashboard port computed deterministically; collision bumps; port persisted to `hosts.json`; re-install preserves existing port.
- `tests/test_hermes_playbooks.py` *(new or existing)* — render the install playbook with sample vars; assert the rendered systemd unit string for the dashboard contains expected `ExecStart`, `PartOf`, `Also`, env vars.

**Exit Criteria:**
- `make test` green (new tests included).
- `make lint` clean.
- Manual verification on a real hermes host (homelab):
  - `clm agent install --type hermes --host <host> --name testdash` succeeds.
  - `hosts.json.agents.testdash.config.dashboard.port` is set and unique on the host.
  - `clm agent configure testdash` succeeds; both `hermes-testdash.service` and `hermes-dashboard-testdash.service` are `active (running)`.
  - `ss -tlnp` on the host shows the dashboard port bound to `127.0.0.1` only (never `0.0.0.0`).
  - `clm agent stop testdash` stops both units; `clm agent start testdash` starts both.
  - `clm agent remove testdash` removes both unit files and the persisted dashboard config.
- No regression: existing hermes installs continue to work; `clm chat <existing-hermes>` still succeeds.

---

### Phase 3 — CLI `clm agent open` + GUI button + tunnel manager + docs (subtask 478-C)

**Complexity:** moderate
**Dependencies:** Phase 2 (478-B) merged to `main`

**Entry Criteria:**
- Phase 2 merged; at least one real hermes host has the dashboard unit running.
- Local control machine has `ssh` on PATH and a working private key for the agent host (the same key Ansible uses).

**Files Affected:**
- `src/clawrium/core/web_ui_tunnel.py` *(new)*:
  - `ensure(agent_key) -> int` — idempotent. State file at `~/.config/clawrium/tunnels/<agent_key>.json` carries `{pid, local_port, started_at, ssh_cmdline_signature}`. On call: read state, verify pid alive + `/proc/<pid>/cmdline` matches stored signature + local port still bound; if all true, reuse. Otherwise kill any stale pid we own (cmdline-guarded), pick free local port via `socket.bind((127.0.0.1, 0))`, spawn `ssh -N -L <local>:127.0.0.1:<remote> -i <key> -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes <user>@<host>`, poll connect (5s timeout), persist state.
  - `close(agent_key)` — kill pid (cmdline-guarded), remove state file.
  - `is_idle(agent_key, threshold=1800)` — for the GUI reaper.
  - `atexit` hook closes all tunnels owned by current process.
- `src/clawrium/cli/agent.py` — new `@agent_app.command()` named `open`:
  - `clm agent open <name>`:
    - Hard error for non-hermes agent: `"Native UI not supported for agent type '<type>'. Only hermes is supported in this release."` Non-zero exit.
    - Verify gateway + dashboard units running (via existing health probe). If not: error with `clm agent start <name>` suggestion.
    - Local-agent shortcut: if host resolves to loopback / local IP, skip tunnel; `webbrowser.open(f"http://127.0.0.1:{remote_port}/")`.
    - Otherwise: `local = tunnel.ensure(agent_key)`. Print `Local port: <p>`. `webbrowser.open(f"http://127.0.0.1:{local}/")`. Block on the SSH subprocess; SIGINT → `tunnel.close()` → exit 0.
  - `clm agent open <name> --print` — print `http://<host>:<remote-port>/` and exit. No tunnel, no browser.
- `src/clawrium/gui/routes/fleet.py` — new endpoint `GET /api/fleet/agents/{agent_key}/web-ui` returning `{ available: bool, local_url: str | null, reason: str | null }`. Server-side: resolve agent, check running, call `web_ui_tunnel.ensure()`, return `local_url`. 404 if agent not found. Record last-access timestamp per agent_key.
- `src/clawrium/gui/server.py` — background reaper in lifespan: every 5 min, `for k, ts in last_access: if now - ts > 30*60: tunnel.close(k)`. Shutdown closes all tunnels.
- `gui/src/lib/types.ts` — add `WebUIResponse` interface.
- `gui/src/components/agent-detail/agent-header.tsx` — fetch `/api/fleet/agents/{key}/web-ui` on mount and on agent status change. Render "Open Agent UI" button:
  - `available: true` → enabled, `onClick={() => window.open(local_url, '_blank')}`.
  - `available: false` for hermes → disabled with tooltip = `reason`.
  - `available: false` for non-hermes → button hidden entirely.
- `docs/agent-support/hermes.md` — new "Native dashboard" section: how to open from GUI/CLI, what the SSH tunnel does, why no token setup is needed (loopback + SSH-tunnel-as-auth-boundary).
- `AGENTS.md` — short subsection under hermes describing the lifecycle (`PartOf` gateway) and SSH-tunnel-as-auth-boundary model.
- `tests/test_web_ui_tunnel.py` *(new)* — idempotency:
  - existing healthy tunnel reused.
  - stale pid evicted (mocked `/proc/<pid>/cmdline`).
  - cmdline guard prevents killing unrelated pid.
  - SSH spawn path mocked; local port picked via `socket.bind((127.0.0.1, 0))`.
- `tests/test_cli_agent_open.py` *(new)* — non-hermes hard error, `--print` does not spawn ssh, SIGINT closes tunnel cleanly.
- `tests/test_gui_routes_fleet.py` — `/web-ui` endpoint: `available: true`/`false`/404 paths; idle reaper closes after threshold (mocked clock).

**Exit Criteria:**
- `make test` green (all new tests).
- `make lint` clean.
- Frontend type-check + lint clean (`cd gui && npm run lint && npm run typecheck`).
- Manual verification on a real hermes host:
  - `clm agent open <hermes-name>` opens the user's default browser at `http://127.0.0.1:<random>/`. Dashboard loads. Chat tab works.
  - `clm agent open <hermes-name>` a second time while the first is still alive reuses the same local port (idempotent — verified via state file).
  - SIGINT on the first invocation cleanly removes the tunnel; running it again establishes a new one.
  - `clm agent open <hermes-name> --print` prints `http://<host>:<port>/` without spawning ssh.
  - `clm agent open <openclaw-name>` returns the hard-error message.
  - GUI: "Open Agent UI" button appears on hermes agent dashboards; click opens the dashboard in a new tab. Same button absent on openclaw/zeroclaw dashboards.
  - Tunnel reaper: leave GUI running 35 min without clicking; verify tunnel process is gone (`ps aux | grep ssh`).
- Docs updated in `docs/agent-support/hermes.md` and `AGENTS.md`.
- All acceptance criteria from issue #478 checked off.

---

## Closing #478

Once all three subtasks (478-A / B / C) merge:
- Verify acceptance criteria from #478 against the merged main.
- Close #478 with a comment linking to the three merged PRs and the manual-verification notes.
- Update `docs/agent-support/hermes.md` Status badge from "🚧 In Development" if appropriate (separate decision — out of scope for this issue).

---

<details>
<summary>Prompt Log</summary>

**Stage**: scaffolding
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-05-22T14:40:57Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 478
```

</details>
