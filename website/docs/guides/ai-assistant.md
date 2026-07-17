---
sidebar_position: 6
description: Use an AI assistant to manage your Clawrium fleet via the /clawctl skill
keywords: [ai assistant, opencode, claude code, clawctl, skill, fleet management, automation, audit log]
---

# Managing Your Fleet with an AI Assistant

Clawrium ships a built-in AI skill — `/clawctl` — that gives any
[opencode](https://opencode.ai)-compatible assistant **or** Claude Code full
knowledge of the `clawctl` CLI. Instead of context-switching to a terminal, you
can ask an AI agent to deploy, configure, and monitor your fleet in plain
language. Every mutating action it takes on your behalf is recorded in a daily
audit trail (`clawctl audit`) so you have a full reproducible history.

## How It Works

The `/clawctl` skill embeds the complete `clawctl` CLI reference — every command,
flag, sub-command, and workflow — into the assistant's context when loaded. The
assistant then issues `clawctl` commands on your behalf or explains what to run,
and writes each mutating action to the audit trail.

```
You  →  "Deploy OpenClaw on mybox and attach my OpenAI key"
AI   →  Loads /clawctl skill, plans steps, runs clawctl commands,
        appends each step to ~/.config/clawrium/changelog/<today>.jsonl
You  →  clawctl audit tail    # review what just happened
```

The skill is meant to live on your **control machine** — the machine where
`clawctl` is installed — and works from any directory. You do **not** need a
Clawrium project checked out to use it. The audit-trail tool (`clawctl audit`)
is a built-in subcommand of `clawctl` — there is no separate binary to install.

## Install (recommended: one-line script)

A single shell script handles both Ubuntu / Debian-family Linux and macOS. It
detects which AI assistants you have installed (Claude Code, opencode) and
drops the skill into the right global discovery path for each.

```bash
curl -fsSL https://raw.githubusercontent.com/ric03uec/clawrium/main/scripts/install-skill-clawctl.sh | bash
```

The script:

- Auto-detects the installed `clawctl` version (`clawctl version`) and pins the
  skill to that release. Falls back to `main` if `clawctl` is not on PATH yet.
- Installs the skill globally — same skill available in every assistant session
  on this machine, regardless of which project you have open.
- Warns if `clawctl` is not on PATH (since the skill drives audit logging
  through `clawctl audit ...`).
- Idempotent — re-run any time to update to the latest release.

### Override the version

Pin a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/ric03uec/clawrium/main/scripts/install-skill-clawctl.sh | CLAWCTL_VERSION=v26.6.3 bash
```

### What the script installs and where

| Tool | Skill path (global) | When installed |
|---|---|---|
| Claude Code | `~/.claude/skills/clawctl/SKILL.md` | If `claude` is on PATH or `~/.claude` exists |
| opencode    | `~/.config/opencode/skills/clawctl/SKILL.md` | If `opencode` is on PATH or `~/.config/opencode` exists |

The audit tool is **not** installed by this script — it's a subcommand of
`clawctl` (`clawctl audit log`, `clawctl audit show`, ...) and ships when you
install Clawrium itself (`uv tool install clawrium`).

If no AI assistant is detected, the script exits with a non-zero status and
tells you how to install one. Re-run after you install your assistant of choice.

### Verify

After running the install command, ask your assistant to list its available
skills. You should see `clawctl` in the list:

```
> List your available skills
...
- clawctl: Know the clawctl CLI and manage your Clawrium fleet ...
```

And verify the audit subcommand:

```bash
clawctl audit --help
clawctl audit stats
```

## Manual install (fallback, if the script fails)

If the install script can't run on your machine — restricted shell, no `curl`,
behind a proxy, or you'd rather see exactly what gets written — copy each
target file by hand.

<details>
<summary>Manual install commands (Claude Code + opencode)</summary>

```bash
# Pin to your installed clawctl version, or set explicitly.
VERSION="v$(clawctl version 2>/dev/null | awk '{print $2}')"
[ "$VERSION" = "v" ] && VERSION="main"

# Claude Code skill — global
mkdir -p ~/.claude/skills/clawctl
curl -fsSL \
  "https://raw.githubusercontent.com/ric03uec/clawrium/${VERSION}/.claude/skills/clawctl/SKILL.md" \
  -o ~/.claude/skills/clawctl/SKILL.md

# opencode skill — global
mkdir -p ~/.config/opencode/skills/clawctl
curl -fsSL \
  "https://raw.githubusercontent.com/ric03uec/clawrium/${VERSION}/.opencode/skills/clawctl/SKILL.md" \
  -o ~/.config/opencode/skills/clawctl/SKILL.md
```

Confirm `clawctl` is on your PATH — `clawctl audit` is the runtime
dependency:

```bash
clawctl version
clawctl audit --help
```

If `clawctl` is missing, install it first: `uv tool install clawrium`.

</details>

### Clawrium repo contributors

If you are working **inside the Clawrium repository itself**, both skill files
already live in the tree at `.claude/skills/clawctl/SKILL.md` and
`.opencode/skills/clawctl/SKILL.md`. No install step is needed. The two
`SKILL.md` files are kept byte-identical — update both in the same change.

## Prerequisites

1. `clawctl` installed and on `PATH`. The skill calls `clawctl audit ...`
   on every mutating action, so this is mandatory.
2. At least one host registered (`clawctl host get`).
3. An opencode-compatible AI assistant (e.g. opencode with Claude) **or**
   Claude Code, installed and on `PATH`.
4. The skill installed (see above).

## Using the Skill

Open a session and invoke the skill by name:

```
/clawctl
```

The assistant loads the full CLI reference and is ready to help. You can drive
it with natural language:

```
"Show me the status of all agents in my fleet"
"Add an OpenAI provider to the agent called 'myclaw'"
"Install the clawrium/tdd skill onto myclaw and sync it"
"Tail the logs for myclaw"
```

The assistant translates your request into `clawctl` commands, explains what
it is about to do, executes, and **appends each mutating step to the audit
trail** via `clawctl audit log`.

## The Audit Trail

Every mutating `clawctl` command run via the skill — whether the assistant
runs it or you do — is recorded as a JSONL line in
`~/.config/clawrium/changelog/<YYYYMMDD>.jsonl`. One file per UTC day,
append-only.

Schema per line (managed by `clawctl audit` — `type=clawctl_command`):

| Field | Meaning |
|---|---|
| `type` | Discriminator. Currently always `clawctl_command`; reserved for future entry shapes. |
| `uuid` | Stable per-entry uuid4. Use to cross-reference. |
| `parent_uuid` | Optional causal parent (e.g. `start` parented to `configure`). |
| `session_id` | Optional grouping id for multi-step workflows (set via `$CLAWCTL_AUDIT_SESSION_ID` or `--session-id`). |
| `timestamp` | ISO 8601 UTC, **millisecond precision**. |
| `cwd` | Working directory at write time. |
| `version` | `{audit, clawctl}` — schema version + clawctl version. |
| `actor` | `"user"` or `"agent"`. |
| `action` | What was done; literal command when relevant. |
| `result` | `"success"`, `"failure"`, or `"skipped"`. |
| `notes` | Free-text context — error output, prompts, confirmations. |

### Querying the trail

```bash
clawctl audit tail                              # Last 20 entries across all days
clawctl audit tail -n 100                       # Last 100
clawctl audit show --date 20260617              # One UTC day
clawctl audit show --actor agent --result failure --last 50
clawctl audit show --session-id <id>            # Replay one workflow
clawctl audit show --grep 'configure|sync'      # Regex over action + notes
clawctl audit show --json                       # Raw JSONL (for piping into jq)
clawctl audit stats                             # Summary counts + top action groups
clawctl audit path                              # Print the log directory
clawctl audit session new                       # Mint a session id
```

### Grouping a workflow with a session id

Before kicking off a multi-step workflow, mint and export a session id. Every
`clawctl audit log` invocation in that shell will tag entries with it:

```bash
export CLAWCTL_AUDIT_SESSION_ID="$(clawctl audit session new)"
# ... assistant runs configure / start / sync / etc. — all tagged with that id
clawctl audit show --session-id "$CLAWCTL_AUDIT_SESSION_ID"
```

Read-only commands (`get`, `describe`, `logs`, `chat`, `open`, `version`) are
**not** logged — they're too noisy to be useful. Only mutating commands and
their failures go into the trail.

### Why?

You can answer at any time:

- **"What did the agent do last Tuesday?"** — `clawctl audit show --date 20260610`
- **"Has anything failed in the last week?"** — `clawctl audit show --result failure --last 100`
- **"Did the assistant touch the prod host?"** — `clawctl audit show --grep prod-host`

## Example Workflows

### First Agent

```
You: I've just added a host called homelab. Help me create and start a
     ZeroClaw agent on it.

AI: I'll walk you through this step by step using clawctl...
    1. clawctl agent create zclaw --type zeroclaw --host homelab
       → clawctl audit log "clawctl agent create zclaw --type zeroclaw --host homelab" --result success
    2. clawctl agent configure zclaw
       → clawctl audit log "clawctl agent configure zclaw" --result success
    3. clawctl agent start zclaw
       → clawctl audit log "clawctl agent start zclaw" --result success
```

### Fleet Health Check

```
You: Are all my agents running?

AI: Let me check...
    clawctl agent get
    [returns status table]
    Agents on homelab (zclaw) and nuc01 (heragent) are running.
    Agent on pi-lab (edge-01) shows status=stopped — want me to start it?
```

(Read-only query — nothing is written to the audit trail.)

### Skill Management

```
You: Add the TDD skill to heragent and sync it.

AI: clawctl agent skill add heragent --from-template clawrium/tdd
    clawctl agent sync heragent
    Done — heragent now has clawrium/tdd installed and synced.
    [Both commands written to today's audit log.]
```

## Rules the Skill Enforces

The `/clawctl` skill reminds the assistant of important invariants:

- Always use `clawctl`, never `clawctl` (removed in v26.6.3).
- Always run `clawctl agent sync <name>` after configuration changes.
- Token rotation happens automatically on `configure`, `sync`, and `restart` —
  remote chat sessions will receive a 401 and must reconnect.
- Provider credentials belong in secrets (`clawctl agent secret`), not in
  plain config.
- **Every mutating action is logged via `clawctl audit log` — never hand-roll
  JSON lines with `jq`/`printf`. If `clawctl` is missing, install it with
  `uv tool install clawrium`.**

## Keeping the Skill Current

The `/clawctl` skill lives at both `.opencode/skills/clawctl/SKILL.md` and
`.claude/skills/clawctl/SKILL.md` in the repository (kept byte-identical),
and the audit-trail logic lives at `src/clawrium/cli/clawctl/audit.py`
(exposed as `clawctl audit`). They must be updated whenever the `clawctl`
CLI surface changes — new commands, renamed flags, or removed sub-commands.
This is enforced by the Maintenance Note at the bottom of the skill file
itself.

Contributors: if you add or change a `clawctl` command, update both `SKILL.md`
files in the same PR.
