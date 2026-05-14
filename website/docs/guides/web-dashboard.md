---
sidebar_position: 5
description: Walk through the Clawrium web dashboard - fleet overview, topology, providers, agent detail, and settings.
keywords: [gui, web dashboard, ui, fleet, topology, providers, chat]
---

# Web Dashboard

Clawrium ships with a local web dashboard that mirrors most of the CLI but renders it visually. Launch it with one command, and use it instead of the CLI when you'd rather click than type.

```bash
clm gui
```

The server binds to `127.0.0.1:36000` only — it is **never reachable from the network**. Your browser opens to the dashboard automatically. Press <kbd>Ctrl+C</kbd> to stop.

> Prefer the terminal? `clm tui` gives you the same fleet overview without leaving the shell.

## Dashboard

The landing page at `/` is the fleet at a glance: total agents, running count, configured providers, 24-hour token usage, estimated cost, and a token-usage chart. A table at the bottom lists each agent with status, type, host, model, and uptime.

![Clawrium dashboard with fleet overview cards and agent table](/img/gui/dashboard.png)

Click any agent name in the table to drop into [Agent Detail](#agent-detail).

## Topology

The topology view renders the control plane (your machine running `clm`) and every fleet host as nodes, connected by SSH edges. Each host card lists the agents running on it with status dots that match the rest of the UI.

![Network topology showing the control machine connected by SSH to a host running three agents](/img/gui/topology.png)

Click a host to see its configuration; click an agent dot to jump to its detail page.

## Providers

The providers page lists every configured LLM provider with the model it defaults to and whether an API key is on file. Below the configured list, a searchable model catalog covers the providers Clawrium ships support for, so you can pick a model before wiring up a new provider.

![Providers page with four configured providers and a model catalog below](/img/gui/providers.png)

Use **+ Add Provider** to register a new provider; **Edit** to rotate API keys or change the default model.

## Agent Detail

Click any agent to land on its detail page. The header shows status, host, model, version, and `Restart` / `Stop` controls. Tabs below switch between Chat, Configuration, Skills & Tools, Memory, and Logs.

![Agent detail page with chat tab active and "Start a conversation" prompt](/img/gui/agent-detail.png)

- **Chat** streams responses from the agent (OpenAI-compatible HTTP for hermes, WebSocket for openclaw — all proxied server-side; credentials never reach the browser).
- **Configuration** mirrors `clm agent show <name>`: provider, gateway URL, device ID, onboarding state, version.
- **Memory** lets you read and edit the agent's memory files in place (saves over SSH).
- **Logs** tails `journalctl --user -u <agent-type>-<agent-name>` from the host.

## Settings

The settings page surfaces install paths, the token-tracking SQLite location, and a Danger Zone for destructive actions.

![Settings page with About, Token Tracking, GUI Preferences, and a Danger Zone section](/img/gui/settings.png)

- **Token Tracking** — Export usage as CSV or clear the usage DB.
- **GUI Preferences** — Documents the CLI flags that drive GUI behavior (`--port`, `--no-open`).
- **Danger Zone** — Reset is intentionally disabled in this release. Until the reset wiring lands, use `clm host` / `clm agent` / `clm provider` to remove config from the CLI.

## When to use the GUI vs. the CLI

| Task | Best surface |
|------|--------------|
| Quick "what's running where?" | GUI dashboard or `clm ps` |
| Visual topology, especially with many hosts | GUI topology |
| Browsing the model catalog | GUI providers |
| Chatting with an agent without SSHing | GUI agent detail |
| Bulk install / configure / start | CLI — automatable and scriptable |
| CI, headless servers, SSH-only boxes | CLI — the GUI server is local-only by design |

The GUI is a read-leaning convenience layer; the CLI remains the source of truth for lifecycle operations.

## Troubleshooting

See the [`clm gui` CLI reference](../reference/cli/gui.md#troubleshooting) for symptom / fix pairs (port-in-use, missing extras, dev-vs-prod port confusion).
