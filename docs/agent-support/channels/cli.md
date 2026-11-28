# CLI

**Status:** ✅ Supported (All Agents, SSH-based as of v26.11.0)

> **Changed in v26.11.0 (#1071).** `clawctl agent chat` was removed.
> Operators now SSH to the agent host and invoke the agent's native
> CLI directly. `clawctl agent shell <name> -- <cmd>` wraps a
> one-shot command for scripted use.

CLI interaction with a Clawrium-managed agent lives on the agent host.
Clawrium prepares the per-agent account, installs the agent binary at
a pinned version, wires provider credentials + channels + integrations
into the agent's canonical config, and brings up the daemon (for
daemon-backed agents). The actual interactive session happens over SSH.

## Usage

```bash
# One-shot command through Clawrium's shell wrapper — handy for
# scripted runs, scheduled jobs, or CI.
clawctl agent shell my-agent -- 'ls -la ~/'
clawctl agent shell my-agent -- 'cat ~/.hermes/config.yaml'
clawctl agent shell my-agent --timeout 600 -- 'make test'

# Longer interactive sessions: SSH directly to the agent host as the
# agent's unix user. The host alias is the `--host` value you used at
# `clawctl host create` time.
ssh xclm@<host-alias>
sudo -u <agent-name> -i   # switch to the agent account
# ... then invoke the native CLI (openclaw / hermes / codex / claude
# / pi / ethos / zeroclaw) as that account.
```

## Agent-type notes

- **OpenClaw / Hermes / ZeroClaw** — daemon-backed. The daemon is
  what channels (Discord, Slack, Web) talk to. The CLI is for
  operators reading daemon logs, tailing conversations, or invoking
  the native agent CLI alongside the daemon.
- **Claude Code / Codex / Pi** — daemonless, install-only. The CLI
  IS the primary interface; there's no daemon to attach channels to.
  SSH to the host and invoke the native binary as the agent account.

## Removed commands

| Pre-v26.11.0 verb | Replacement |
|---|---|
| `clawctl agent chat <name>` | SSH to the host; invoke the native CLI. `clawctl agent shell <name> -- <cmd>` for one-shot runs. |
| `clawctl agent exec <name> -- <args...>` | `clawctl agent shell <name> -- <cmd>` (one-shot) or SSH directly. |
| `clawctl agent memory ...` | Operator memory lives on the host; manage with the agent's native tooling. |

See [CHANGELOG.md](../../../CHANGELOG.md) for the full removal set
and rationale.
