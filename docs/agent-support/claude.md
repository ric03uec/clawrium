# Claude Code Support

Clawrium supports `claude` as an **install-only, per-agent Claude Code environment**. It is not a daemon-backed assistant: Clawrium prepares an isolated account and command environment, while an operator chooses when to run a finite Claude Code command.

**Pinned version:** `2.1.100`

**Supported targets:** Ubuntu 22.04 or 24.04 on x86_64; macOS 14+ on Apple Silicon.

## Install-only contract

Create an isolated environment with the normal agent command:

```bash
clawctl agent create <name> --type claude --host <host>
```

`create` creates the dedicated agent account and home, installs the pinned
package into that account's owned `~/.local/claude` prefix, records the agent,
and stops. It does **not** invoke `claude`, sign in, create authentication
state, start a service, gateway, or HTTP listener, allocate a port, establish
a tunnel, create a native web UI, start a chat backend, or pair a device.

The installed record is shown by `clawctl agent get` and `clawctl agent
describe`. Its ready state means the installation completed; it is not a
process-health result.

## Herdr runtime

Claude installs the pinned, host-shared [Herdr](https://herdr.dev/) binary at
`/usr/local/bin/herdr` on Linux and macOS. The verified runtime is shared with
Hermes agents on that host and remains after this Claude agent is removed.
Claude receives **no** Herdr plugin or configuration integration.

Herdr is not provisioned for OpenClaw, ZeroClaw, or Ethos agents.

## Configuration and settings ownership

`clawctl agent configure <name>` and `clawctl agent sync <name>` reconcile the
same bounded, global settings file for the dedicated account:

- Linux: `/home/<name>/.claude/settings.json`
- macOS: `/Users/<name>/.claude/settings.json`

Clawrium manages only these settings keys:

- `model`
- `effortLevel`
- `permissions.ask`
- `permissions.deny`
- `permissions.additionalDirectories`

No arbitrary settings pass-through is supported. In particular, Clawrium never
writes a repository's `.claude/settings.json` or `.claude/settings.local.json`;
those project settings remain owned by the repository and its users.

Configure and sync also never invoke Claude Code or restart a process. They
require one selected credential mode so the next supported shell command can
receive it.

## Credentials and safe sync

A Claude agent has exactly one active credential mode:

| Mode | Active remote variable |
|------|------------------------|
| Claude OAuth | `CLAUDE_CODE_OAUTH_TOKEN` |
| Anthropic API key | `ANTHROPIC_API_KEY` |

For an API key, prefer stdin rather than a command-line value:

```bash
printf '%s' "$ANTHROPIC_API_KEY" | \
  clawctl agent secret create ANTHROPIC_API_KEY --agent <name> --value-stdin --yes
clawctl agent sync <name>
```

Creating either reserved Claude credential key through `agent secret create`
selects that mode atomically and removes the other local mode from the
agent's encrypted secret scope. Do not attach an ordinary `anthropic`
provider to a Claude agent; API-key mode is agent-scoped rather than a shared
provider attachment.

Claude OAuth is a first-class provider type. On a Linux Clawrium
controller, register and select it through the normal provider workflow:

```bash
clawctl provider registry get --types
clawctl provider registry create local-claude-oauth --type claude-oauth
clawctl agent provider attach local-claude-oauth --agent <name>
clawctl agent sync <name>
```

Attach reads the current controller's exact native Claude credential artifact,
`~/.claude/.credentials.json`, through a private, Linux-controller-only reader.
It validates and imports only the allowlisted native OAuth document into the
selected agent's encrypted per-instance secret scope. It never invokes
`claude`, prints the document, reads a keychain, browser profile, or credential
database, or scans a directory. A controller on another platform fails closed
with a clear unsupported-reader error. Re-attaching the same provider refreshes
the selected agent's OAuth document without showing its value.

Do not retain both keys in the agent secret scope. If both are present,
configure and sync fail rather than choose an undocumented precedence. Check
key names and metadata without revealing values:

```bash
clawctl agent secret get --agent <name>
```

A successful configure or sync writes one private, agent-owned mode-`0600`
artifact and clears the stale other-mode artifact only after the replacement is
durable:

- OAuth writes native `~/.claude/.credentials.json` and clears the API-key
  environment file.
- API-key mode writes `~/.claude/clawrium-credentials.env`, which contains only
  shell-safe `ANTHROPIC_API_KEY` activation, and clears native OAuth state.

Cleanup verifies that the inactive artifact is absent. If cleanup cannot
complete, configure or sync fails closed and restores the prior selected
artifact; when there was no prior selected artifact, it removes the newly
introduced one. This avoids leaving both credential sources available.

Credential values are not written to `hosts.json`, `settings.json`, sync
diffs, command output, logs, or events. Do not print or copy either remote
credential artifact to diagnose a configuration.

## Run a finite command

Use the normal command-shell path for Claude Code:

```bash
clawctl agent shell <name> -- 'claude --version'
```

`agent shell` runs the supplied command as the dedicated agent Unix user in a
finite, non-interactive login shell. For Claude it clears inherited credential
variables, then sources the private API-key artifact only when it exists;
OAuth remains native Claude Code state. Every command must terminate: no TTY,
interactive shell, prompt, or Claude Code chat session is created.

`clawctl agent exec <name> ...` does not support `claude`; use `agent shell`
with an explicit command after `--` instead.

## Available and unavailable operations

| Operation | Claude Code behavior |
|-----------|----------------------|
| `create`, `get`, `describe`, `delete` | Supported as an installed-agent record. |
| `configure`, `sync` | Supported for bounded global settings and selected-credential activation; never run Claude or restart a daemon. |
| `shell <name> -- <command>` | Supported finite, non-interactive command path. |
| `status` | Use `agent get` or `agent describe`; there is no runtime daemon probe. |
| `start`, `stop`, `restart`, `logs` | Not applicable: Claude Code has no Clawrium-managed daemon or service. |
| `open`, native web UI, tunnel, port, pairing | Unavailable: the manifest declares no web UI. |
| `chat` and GUI chat | Unavailable: there is no Clawrium chat backend for Claude Code. |
| `exec` | Unavailable for Claude Code; use `agent shell`. |

## Removal ownership

Remove an instance with:

```bash
clawctl agent delete --yes <name>
```

After remote cleanup succeeds, Clawrium removes only resources owned by that
agent: its dedicated account and home, owned install prefix, complete
agent-home `~/.claude` directory (including either private credential
artifact), ownership marker, local per-agent secrets, and fleet record. It
does not remove an independently installed global Claude Code
distribution or project `.claude` settings outside that agent home.

If remote cleanup fails, Clawrium keeps the local secret scope and fleet record
so the operator can retry safely.

## See also

- [CLI reference](../reference/cli/agent.md)
- [Agent secret commands](../reference/cli/secret.md)
- [Agent onboarding](../agent-onboarding.md)
