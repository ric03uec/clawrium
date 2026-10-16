---
sidebar_position: 6
description: Install and operate Pi as a no-daemon, isolated per-agent command environment.
keywords: [pi, coding agent, install-only, openrouter, bedrock, codex oauth]
---

# Pi Support

Clawrium supports `pi` as an **isolated, per-agent Pi coding-agent
environment** with scoped OpenRouter provisioning and finite, on-demand CLI
and GUI chat. It is not a daemon-backed assistant: Clawrium prepares an
isolated account and command environment, then runs a finite Pi process only
for each chat turn or native command.

**Pinned version:** `0.73.1` (npm package `@mariozechner/pi-coding-agent`)

**Supported targets:** Ubuntu 24.04 on x86_64; macOS 14+ on Apple Silicon.
The host needs Node.js 20.6 or later with a trusted `npm`
(`/usr/local/bin/npm` or `/usr/bin/npm`).

## No-daemon install contract

Create an isolated environment with the normal agent command:

```bash
clawctl agent create <name> --type pi --host <host>
```

`create` creates the dedicated agent account and home, installs the pinned
package into that account's owned `~/.local/pi` prefix, records the agent, and
stops. It does **not** invoke Pi, request provider access, log in, start a
service, allocate a port, establish a tunnel, create a native web UI, or start
a persistent chat backend.

The installed record is shown by `clawctl agent get` and `clawctl agent
describe`. Its ready state means the installation completed; it is not a
process-health result.

`agent start`, `stop`, `restart`, and `logs` are not Pi operations, and
`agent open` is unavailable because Pi has no native dashboard.

## Provider provisioning

Pi supports **one provider at a time**, from three provider types: an
existing registered **OpenRouter** provider, an **AWS Identity Center
Bedrock** provider, or a single **`openai-codex`** provider with one model
from Pi's pinned `0.73.1` catalog.

### OpenRouter

Attach an existing registered OpenRouter provider with an unprefixed
OpenRouter `default_model`, then sync:

```bash
clawctl agent provider attach <provider> --agent <name>
clawctl agent sync <name>
```

Equivalently, configure with the providers stage:

```bash
clawctl agent configure <name> --stage providers --provider <provider>
```

Clawrium writes the provider activation only to that Pi account's private
environment file (`~/.pi/agent/clawrium-provider.env` on Linux,
`/Users/<name>/.pi/agent/clawrium-provider.env` on macOS); Pi consumes it on
demand and never requests a grant. The model ID must be a supported
OpenRouter ID **without** the `openrouter/` provider prefix — prefixed or
malformed model IDs are rejected with an actionable error. The attach/sync
path validates the provider before touching the host, and a failed
provisioning attempt is rolled back so the agent is never left with a
partially written credential.

### Bedrock (AWS Identity Center SSO)

Create a `bedrock` provider with its model, region, and complete `--sso-*`
profile metadata, attach it, and sync. Clawrium writes only an isolated AWS
profile/configuration to the Pi account — it never copies a controller
`~/.aws`, an SSO token cache, or static Bedrock keys. Before chat, run
`aws sso login --profile <profile>` as the dedicated Pi account (the fleet
host needs AWS CLI v2); an expired login produces a recoverable error rather
than falling back to another credential source.

**Bedrock cleanup boundary.** Detaching Bedrock or switching the Pi agent to
another provider removes Clawrium-managed AWS files and attempts to clear the
dedicated Pi account's local AWS SSO and CLI caches. This is best-effort
local file cleanup, not upstream AWS Identity Center session revocation. It
cannot invalidate credentials already copied or held in memory, or prevent
concurrent Pi processes running as the same account from recreating cache
files. If needed, separately expire or revoke the upstream AWS session.

### Codex OAuth (`openai-codex`)

Create a single `openai-codex` provider **without an API key**, with one
model from Pi's pinned `0.73.1` catalog, attach and sync it, then run
`clawctl agent provider login <provider> --agent <name>` from an interactive
terminal. That command opens Pi under only the dedicated agent account;
complete Pi's native `/login` → `openai-codex` flow there. Pi owns the
resulting private OAuth document and refreshes it locally; on expiry or
revocation, rerun the same command. Never export an OAuth bearer, set
`OPENAI_API_KEY`, or copy a controller `~/.pi` directory.

Switching a Pi agent from Codex OAuth to another provider revokes the
dedicated account's OAuth state before the new credential activates; a
provider switch always restarts Pi with a clean environment.

### Shared behavior

`agent exec` also receives the same isolated environment, so finite native
commands run with the provisioned credential.

Check key names and metadata without revealing values:

```bash
clawctl agent secret get --agent <name>
```

## Chat on demand

After provisioning one OpenRouter provider, use the standard chat surfaces:

```bash
clawctl agent chat <name>
clawctl agent chat <name> --once "Summarize the current workspace"
```

Each turn runs a finite Pi print-mode invocation as the dedicated agent Unix
user with a bounded runtime; it does not start a daemon, gateway, port,
tunnel, or native UI. Later turns in the same conversation continue the Pi
session; starting a new conversation (or the GUI **New chat** action) resets
it. The **Chat** tab on the agent page in the web dashboard
([`clawctl server`](/docs/reference/cli/server)) uses this same backend — it
does not create a gateway, tunnel, or a second Pi invocation path.

## Run a finite native command

Use the standard native-exec path for Pi:

```bash
clawctl agent exec <name> -- --version
```

`agent exec` runs the dedicated account's pinned Pi binary (not a binary found
in a shared shell) as that agent Unix user with each supplied argument as
a separate argv value. It starts in the agent home, has no TTY, and has a hard
120-second remote runtime bound. Standard output, standard error, and the
native exit code are returned after the command exits. The provisioned
credential is redacted from returned output; the command transport and runner
logs never receive a credential value.

## Removal

```bash
clawctl agent delete --yes <name>
```

Removes the dedicated account, home directory, and pinned install prefix from
the host and clears the local fleet record and secret scope.

## See also

- [CLI reference](/docs/reference/cli/agent)
- [Agent secret commands](/docs/reference/cli/secret)
- [OpenRouter providers](/docs/agent-support/providers/openrouter)
- [Installation](/docs/installation)
