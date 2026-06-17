---
sidebar_position: 6
description: Use an AI assistant to manage your Clawrium fleet via the /clawctl skill
keywords: [ai assistant, opencode, clawctl, skill, fleet management, automation]
---

# Managing Your Fleet with an AI Assistant

Clawrium ships a built-in AI skill — `/clawctl` — that gives any
[opencode](https://opencode.ai)-compatible assistant full knowledge of the `clawctl`
CLI. Instead of context-switching to a terminal, you can ask an AI agent to help
you deploy, configure, and monitor your fleet in plain language.

## How It Works

The `/clawctl` skill embeds the complete `clawctl` CLI reference — every command,
flag, sub-command, and workflow — into the assistant's context when loaded. The
assistant then issues `clawctl` commands on your behalf or explains what to run.

```
You  →  "Deploy OpenClaw on mybox and attach my OpenAI key"
AI   →  Loads /clawctl skill, plans steps, runs clawctl commands
```

## Installation

The skill is a single `SKILL.md` file you copy into the discovery path for your
AI tool. Once placed, both opencode and Claude Code find it automatically — no
config changes needed.

The commands below fetch the skill that matches the version of `clawctl` you have
installed. Run `clawctl version` first to confirm your version, then choose the
matching tab below.

:::tip Version-pinned install
Each command auto-detects your installed version via `clawctl version`
(which prints e.g. `clawctl 26.6.3`) and prepends `v` to form the git tag. If
`clawctl` is not on your PATH yet, replace the `VERSION=` line with
`VERSION="v26.6.3"` (or whichever version you have).
:::

### opencode

Install **per-project** (skill is available only when you open a session inside
that directory tree):

```bash
# opencode — project-local
VERSION="v$(clawctl version 2>/dev/null | awk '{print $2}')"
[ "$VERSION" = "v" ] && VERSION="v26.6.3"
mkdir -p .opencode/skills/clawctl
curl -fsSL \
  "https://raw.githubusercontent.com/ric03uec/clawrium/${VERSION}/.opencode/skills/clawctl/SKILL.md" \
  -o .opencode/skills/clawctl/SKILL.md
```

Install **globally** (skill is available in every opencode session on this
machine):

```bash
# opencode — global
VERSION="v$(clawctl version 2>/dev/null | awk '{print $2}')"
[ "$VERSION" = "v" ] && VERSION="v26.6.3"
mkdir -p ~/.config/opencode/skills/clawctl
curl -fsSL \
  "https://raw.githubusercontent.com/ric03uec/clawrium/${VERSION}/.opencode/skills/clawctl/SKILL.md" \
  -o ~/.config/opencode/skills/clawctl/SKILL.md
```

### Claude Code

Install **per-project**:

```bash
# Claude Code — project-local
VERSION="v$(clawctl version 2>/dev/null | awk '{print $2}')"
[ "$VERSION" = "v" ] && VERSION="v26.6.3"
mkdir -p .claude/skills/clawctl
curl -fsSL \
  "https://raw.githubusercontent.com/ric03uec/clawrium/${VERSION}/.opencode/skills/clawctl/SKILL.md" \
  -o .claude/skills/clawctl/SKILL.md
```

Install **globally**:

```bash
# Claude Code — global
VERSION="v$(clawctl version 2>/dev/null | awk '{print $2}')"
[ "$VERSION" = "v" ] && VERSION="v26.6.3"
mkdir -p ~/.claude/skills/clawctl
curl -fsSL \
  "https://raw.githubusercontent.com/ric03uec/clawrium/${VERSION}/.opencode/skills/clawctl/SKILL.md" \
  -o ~/.claude/skills/clawctl/SKILL.md
```

### Verify

After running the install command, ask your assistant to list available skills.
You should see `clawctl` in the list:

```
> List your available skills
...
- clawctl: Know the clawctl CLI and manage your Clawrium fleet ...
```

### Clawrium repo users

If you are working inside the Clawrium repository itself, the skill is already
present at `.opencode/skills/clawctl/SKILL.md` — no installation step needed.

## Prerequisites

1. `clawctl` installed and at least one host registered (`clawctl host get`).
2. An opencode-compatible AI assistant (e.g. opencode with Claude) **or** Claude Code.
3. The skill installed (see above).

## Using the Skill

Open a session and invoke the skill by name:

```
/clawctl
```

The assistant loads the full CLI reference and is ready to help. From there you
can use natural language:

```
"Show me the status of all agents in my fleet"
"Add an OpenAI provider to the agent called 'myclaw'"
"Install the clawrium/tdd skill onto myclaw and sync it"
"Tail the logs for myclaw"
```

The assistant will translate your request into `clawctl` commands, explain what
it is about to do, and execute or display the exact commands to run.

## Example Workflows

### First Agent

```
You: I've just added a host called homelab. Help me create and start a
     ZeroClaw agent on it.

AI: I'll walk you through this step by step using clawctl...
    1. clawctl agent create zclaw --type zeroclaw --host homelab
    2. clawctl agent configure zclaw
    3. clawctl agent start zclaw
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

### Skill Management

```
You: Add the TDD skill to heragent and sync it.

AI: clawctl agent skill add heragent --from-template clawrium/tdd
    clawctl agent sync heragent
    Done — heragent now has clawrium/tdd installed and synced.
```

## Rules the Skill Enforces

The `/clawctl` skill reminds the assistant of important invariants:

- Always use `clawctl`, never `clm` (deprecated alias).
- Always run `clawctl agent sync <name>` after configuration changes.
- Token rotation happens automatically on `configure`, `sync`, and `restart` —
  remote chat sessions will receive a 401 and must reconnect.
- Provider credentials belong in secrets (`clawctl agent secret`), not in
  plain config.

## Keeping the Skill Current

The `/clawctl` skill lives at `.opencode/skills/clawctl/SKILL.md` in the
repository. It must be updated whenever the `clawctl` CLI surface changes —
new commands, renamed flags, or removed sub-commands. This is enforced by the
Maintenance Note at the bottom of the skill file itself.

Contributors: if you add or change a `clawctl` command, update
`.opencode/skills/clawctl/SKILL.md` in the same PR.
