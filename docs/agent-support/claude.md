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

Claude OAuth is a first-class provider type. On a Linux Clawrium
controller, register and select it through the normal provider workflow:

```bash
clawctl provider registry get --types
clawctl provider registry create local-claude-oauth --type claude-oauth
clawctl agent provider attach local-claude-oauth --agent <name>
clawctl agent sync <name>
```

Attach imports the controller user's locally validated Claude Code OAuth
access token from Claude Code 2.1.139's private `~/.claude/.credentials.json`
artifact. The reader is a narrow, Linux-only reader: the artifact must be a
current-user-owned regular file with no group or world permissions (mode
`0600`), at most 64 KiB, and it accepts only the documented
`claudeAiOauth.accessToken` field. No value other than that field escapes the
reader; it is never printed, logged, copied, or included in errors. Failure is
reported as a fixed, secret-free category (for example
`credentials_artifact_unavailable` or `credentials_artifact_insecure`) rather
than as a message that could echo credential material. After the import, the
normalized token is stored only as `CLAUDE_CODE_OAUTH_TOKEN` in that selected
agent's encrypted per-instance secret scope; the next sync uses the existing
private activation path to write it on the selected host. This does **not**
require `CLAUDE_CODE_OAUTH_TOKEN` to be pre-exported by the caller.

The supported reader is currently Linux-controller-only. A controller on any
other platform fails closed with a clear unsupported-reader error; it does not
search, copy, or enumerate `~/.claude`, a keychain, a browser profile, or a
credential database — it reads exactly the one documented artifact above.
Re-attaching the same provider re-imports the current local token and refreshes
the agent's secret scope without showing its value. If the artifact is absent,
a controller user who holds a subscription must first authorize Claude Code on
the controller (for example by running Claude Code once locally); Clawrium
does not start or drive the browser authorization itself.

Do not retain both keys in the agent secret scope. If both are present,
configure and sync fail rather than choose an undocumented precedence. Check
key names and metadata without revealing values:

```bash
clawctl agent secret get --agent <name>
```

A successful configure or sync atomically writes an agent-owned, mode-`0600`
credential environment file containing only the selected variable; the other
variable is explicitly unset. Credential values are not written to
`hosts.json`, `settings.json`, sync diffs, command output, logs, or events.
Do not print or copy the remote credential file to diagnose a configuration.

### i-wolf E2E evidence

The `wolf-i` (i-wolf) validation proved install-only behavior, exclusive
remote API-key environment propagation with a generated **dummy** value, and
owned-resource cleanup. It did **not** authenticate to Anthropic with that
dummy value. The real OAuth E2E (PASS, 2026-10-03) exercised the normal
provider registration, attach, and sync path against the supported local
reader on a Linux controller: agent-owned mode-`0600` credential activation,
redacted shell assertions, owned-resource cleanup, and preservation of
pre-existing fleet records. The run never printed, copied, or persisted the
local credential artifact's contents; ordinary provider selection and sync
remain covered by fake-reader unit/integration tests.

## Run a finite command

Use the normal command-shell path for Claude Code:

```bash
clawctl agent shell <name> -- 'claude --version'
```

`agent shell` runs the supplied command as the dedicated agent Unix user in a
finite, non-interactive login shell. It activates the managed credential hook
for that command only. Every command must terminate: no TTY, interactive
shell, prompt, or Claude Code chat session is created.

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
agent-home `~/.claude` directory (including the credential environment file),
managed shell-startup snippet, ownership marker, local per-agent secrets, and
fleet record. It does not remove an independently installed global Claude Code
distribution or project `.claude` settings outside that agent home.

If remote cleanup fails, Clawrium keeps the local secret scope and fleet record
so the operator can retry safely.

## See also

- [CLI reference](../reference/cli/agent.md)
- [Agent secret commands](../reference/cli/secret.md)
- [Agent onboarding](../agent-onboarding.md)
