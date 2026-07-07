---
slug: workspace-overlay-sync
title: "Drop files on your laptop, they appear on your agents — zero SSH required"
authors: [maurice]
tags: [workspace, sync, operators]
date: 2026-07-06
---

Managing agent configuration used to mean SSH'ing into every host to edit files, then running sync to pick up the rest. Now you can just drop files into a local folder on the control plane and clawrium pushes them to the right agent on every sync. This blog post explains how workspace overlay sync works, what landed in v26.6.5 and v26.7.0, and how to use it today.

<!-- truncate -->

## What changed

**Workspace overlay sync is now GA across all agent types and both Linux and macOS.** You create files in `~/.config/clawrium/agents/<type>/<name>/workspace/` on your control-plane machine, and on the next `clawctl agent sync` they are mirrored into the agent's home directory on the target host. Openclaw on Ubuntu landed in Phase 1 (v26.6.5), openclaw on macOS in Phase 4 (v26.7.0), and zeroclaw + hermes on macOS in Phases 5-6 (v26.7.0). Every agent type has a curated exclude list so critical files like `config.yaml`, auth tokens, and database files are never overwritten.

**Sync flags refined for workspace workflows.** The legacy `--workspace` flag was replaced by `--workspace-only` (push the operator overlay alone, skip canonical render) and `--no-restart` (canonical render + workspace overlay without a unit restart). These give you granular control over what sync does.

**Audit scope tightened per agent.** `clawctl audit show` and `clawctl audit tail` now require `--agent <name>` or `--all`, so you get agent-scoped audit trails instead of a single global log. A new `clawctl agent audit <name>` shortcut makes per-agent reads idiomatic.

## Why this matters

Before workspace overlay, adding a custom skill, a prompt template, or a config snippet to a remotely-hosted agent required two steps: SSH into the host, edit the file in the right location, then sync from the control plane to pick up provider/channel changes. That workflow broke down quickly once you had more than three agents.

Workspace overlay inverts the direction of data flow. Your control-plane machine becomes the single source of truth for operator-authored files. You edit locally — in your favorite editor, with your dotfile tooling, with `git` if you want — and the next sync pushes them to every host. For operators running agent fleets across multiple machines, this eliminates the SSH hop entirely for file-based configuration.

## How it works

1. Create a workspace directory on the control plane: `~/.config/clawrium/agents/<type>/<name>/workspace/`
2. Drop any files or subdirectories you want the agent to have
3. Run `clawctl agent sync <name>` — the overlay is pushed as part of the standard sync flow

For workspace-only updates (no canonical render needed), use `clawctl agent sync <name> --workspace-only`. To push overlay without restarting the agent service, use `--no-restart`.

**Exclude lists prevent accidental overwrites.** Hermes protects `config.yaml`, `.env`, `auth.json`, `state.db`, `sessions/`, `logs/`, and `skills/clawrium/`. Openclaw and zeroclaw have equivalent per-type exclude lists. If you drop a file at an excluded path, you get a `WorkspaceExcluded` event and the file is skipped.

## Try it

```bash
# Upgrade to v26.7.0
uv tool install clawrium@26.7.0

# Create a workspace file for your agent
mkdir -p ~/.config/clawrium/agents/hermes/assistant/workspace/
echo "Hello from the control plane" > ~/.config/clawrium/agents/hermes/assistant/workspace/my-prompt.txt

# Sync to push it to the host
clawctl agent sync assistant

# Or push workspace changes only
clawctl agent sync assistant --workspace-only
```

## Links

- [GitHub Release v26.7.0](https://github.com/ric03uec/clawrium/releases/tag/v26.7.0)
- [Full Changelog v26.7.0](https://github.com/ric03uec/clawrium/blob/main/docs/releases/26.7.0/CHANGELOG.md)
- [Sync operations guide](/docs/operations/sync)
- [Issue #760: Sync agent workspace from control plane to data plane](https://github.com/ric03uec/clawrium/issues/760)

---

*Drafted by **clawrium-gtm** (agent) running on **qwen3.6-27b** via Hermes Agent.*
