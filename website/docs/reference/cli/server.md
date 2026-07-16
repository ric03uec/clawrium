---
sidebar_position: 9
description: Command reference for managing the local GUI server lifecycle
keywords: [cli, server, gui, dashboard, web ui, start, stop, status, command reference]
---

# clawctl server

Manage the local GUI server lifecycle.

> **Breaking change in v26.7.2:** `clawctl gui` has been removed. Use `clawctl server start` to launch the dashboard in the background. See the migration notes below.

## Synopsis

```bash
clawctl server {start|stop|status|run} [options]
```

The `clawctl server` command group manages the local web GUI dashboard server. Unlike the legacy `clawctl gui` (which ran in the foreground), the new commands support both detached background mode and foreground supervisor mode.

> **Note:** `clawctl server` is **Linux-only** in this release. macOS support ships in a follow-up.

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl server start`](#clawctl-server-start) | Start the GUI server in the background (detached) |
| [`clawctl server stop`](#clawctl-server-stop) | Stop the running GUI server |
| [`clawctl server status`](#clawctl-server-status) | Show whether the server is running |
| [`clawctl server run`](#clawctl-server-run) | Run the GUI server in the foreground (systemd/Docker) |

---

## clawctl server start

Start the GUI server detached from the current shell.

```bash
clawctl server start
```

Runs uvicorn on `127.0.0.1:36000` and records PID + URL to `~/.config/clawrium/server.json`. Idempotent: a second invocation while the server is already running prints the live URL and exits 0. The command fails with exit 1 if port `:36000` is held by another process.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Server started successfully, or already running (idempotent) |
| 1 | Port in use by foreign process, startup failure, or unsupported platform |

### Example

```bash
$ clawctl server start
Server started at http://127.0.0.1:36000 (pid 48291)

# Second invocation (idempotent)
$ clawctl server start
Server already running at http://127.0.0.1:36000
```

---

## clawctl server stop

Stop the running GUI server.

```bash
clawctl server stop
```

Reads the PID from `~/.config/clawrium/server.json` and sends a termination signal. No-op with a clear message if no server is running.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Server stopped successfully, or not running (no-op) |
| 1 | Stop failed (e.g., PID belongs to a process owned by another user) |

### Example

```bash
$ clawctl server stop
Server stopped (pid 48291, http://127.0.0.1:36000)

$ clawctl server stop
Server is not running
```

---

## clawctl server status

Show whether the GUI server is running.

```bash
clawctl server status
```

Prints running/stopped state, URL, host, port, PID, and start timestamp.

### Example

```bash
$ clawctl server status
Status:    running
URL:       http://127.0.0.1:36000
Host:      127.0.0.1
Port:      36000
PID:       48291
Started:   2026-07-13T14:56:00Z
```

---

## clawctl server run

Run the GUI server in the foreground (blocking).

```bash
clawctl server run
```

Intended for systemd, Docker, or other process-supervisor deployments. Does not write the state file — the process manager owns lifecycle. Press <kbd>Ctrl+C</kbd> to stop.

### Example

```bash
$ clawctl server run
Serving GUI at http://127.0.0.1:36000 — press Ctrl+C to stop
INFO:     Started server process [48291]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:36000 (Press CTRL+C to quit)
```

---

## Migration from `clawctl gui`

If you were using `clawctl gui`, replace it as follows:

| Old command | New command |
|-------------|-------------|
| `clawctl gui` | `clawctl server start` |
| `clawctl gui --port 38000` | Not yet supported — port is fixed at 36000 |
| `clawctl gui --no-open` | `clawctl server start` (no browser auto-open) |
| `Ctrl+C` to stop | `clawctl server stop` |

State is stored in `~/.config/clawrium/server.json` (PID, URL, host, port, start time).

---

## What you get

The dashboard surfaces the same data as the CLI, with a few interactive niceties:

- **Dashboard** — fleet counts, 24h token usage, recent agent activity
- **Topology** — visual map of hosts and the agents running on them, with per-host hardware badges (architecture, GPU vendor)
- **Providers** — list of configured LLM providers + a searchable model catalog
- **Integrations** — manage GitHub / GitLab / Atlassian / Linear / Notion integrations and credentials (counterpart to [`clawctl integration`](./integration.md))
- **Agent detail** — chat with a running agent, view logs, edit memory, inspect config
- **Settings** — version info, usage DB controls (export / clear), Danger Zone

A walkthrough with screenshots lives in the [Web Dashboard guide](../../web-dashboard.md).

---

## Security notes

- The server **never binds** to `0.0.0.0`. Multi-machine access is out of scope; use SSH port-forwarding if you need to view the dashboard from another machine.
- API responses do not include credentials. Agent gateway tokens stay in the secrets store and are only used server-side when proxying chat requests.
- Log fetching over SSH uses each host's registered key (`-i`) with strict host-key checking; hostnames coming from `hosts.json` are validated before they reach the SSH argv.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `port already in use` | Port 36000 taken by another process | `lsof -ti :36000` to find the conflict, then kill or stop it |
| Server starts but browser shows 404 | Frontend bundle not staged | Re-install Clawrium; the bundle ships inside the wheel. If running from source, `make build-ui` builds and stages it. |
| Page renders, every API call 404s | You're hitting `next dev` on :3000 instead of the server on :36000 | Open `http://127.0.0.1:36000`, not `:3000` |
