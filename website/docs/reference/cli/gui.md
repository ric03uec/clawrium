---
sidebar_position: 8
description: Command reference for launching the local web dashboard
keywords: [cli, gui, dashboard, web ui, command reference]
---

# clm gui

Launch the local web GUI dashboard.

## Synopsis

```bash
clm gui [options]
```

`clm gui` starts a small FastAPI server on the management machine and opens your default browser to the Clawrium dashboard. The server binds to `127.0.0.1` only — it is **never reachable from the network**.

Running in the foreground; press <kbd>Ctrl+C</kbd> to stop. For a terminal-based equivalent, use `clm tui`.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port`, `-p` | `36000` | Local TCP port to bind. Must be 1–65535. |
| `--no-open` | `false` | Skip auto-opening the browser. Useful for headless / SSH sessions. |

## Examples

```bash
# Default: bind 127.0.0.1:36000 and open the browser
clm gui

# Custom port (useful when 36000 is taken)
clm gui --port 38000

# Run the server without opening a browser (SSH / tmux / CI)
clm gui --no-open
```

## What you get

The dashboard surfaces the same data as the CLI, with a few interactive niceties:

- **Dashboard** — fleet counts, 24h token usage, recent agent activity
- **Topology** — visual map of hosts and the agents running on them, with per-host hardware badges (architecture, GPU vendor)
- **Providers** — list of configured LLM providers + a searchable model catalog
- **Integrations** — manage GitHub / GitLab / Atlassian / Linear / Notion integrations and credentials (counterpart to [`clm integration`](./integration.md))
- **Agent detail** — chat with a running agent, view logs, edit memory, inspect config
- **Settings** — version info, usage DB controls (export / clear), Danger Zone

A walkthrough with screenshots lives in the [Web Dashboard guide](../../web-dashboard.md).

## Installation requirement

The GUI ships in the default install of Clawrium — no extra steps. If you installed with `--no-extras`, install with the GUI extra:

```bash
uv tool install --force 'clawrium[gui]'
```

Without the GUI dependencies, `clm gui` exits with a clear remediation message.

## Security notes

- The server **never binds** to `0.0.0.0`. Multi-machine access is out of scope; use SSH port-forwarding if you need to view the dashboard from another machine.
- API responses do not include credentials. Agent gateway tokens stay in the secrets store and are only used server-side when proxying chat requests.
- Log fetching over SSH uses each host's registered key (`-i`) with strict host-key checking; hostnames coming from `hosts.json` are validated before they reach the SSH argv.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Error: GUI requires extra dependencies` | Installed without `[gui]` extra | `uv tool install --force 'clawrium[gui]'` |
| `address already in use` | Port 36000 taken by another process | `clm gui --port 38000` or `lsof -ti :36000` to find the conflict |
| Browser opens then 404 | Frontend bundle not staged | Re-install Clawrium; the bundle ships inside the wheel. If you're running from source, `make build-ui` builds and stages it. |
| Page renders, every API call 404s | You're hitting `next dev` on :3000 instead of the FastAPI server on :36000 | Open `http://127.0.0.1:36000`, not `:3000` |
