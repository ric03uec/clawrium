---
slug: clawctl-kubectl-ux
title: "From clm to clawctl: a kubectl-style sweep across the whole CLI"
authors: [ric03uec]
tags: [announcements, breaking-changes]
---

If you've been using Clawrium since the early `clm` days, the next
release is going to feel different the moment you type a command.

```text
$ clawctl agent get
NAME           TYPE      PROVIDER     HOST      STATUS    AGE
wolf-i         openclaw  bedrock      wolf-i    Running   17d
espresso       hermes    ollama       wolf-i    Running   12d
clawrium-d01   zeroclaw  openrouter   wolf-i    Running    9d
```

The binary is now `clawctl`. Every command has been re-rooted under a
small, consistent verb grammar. There is no `clm` alias, no
deprecation warning, no shim — just a clean cutover.

<!-- truncate -->

## Why this changed

The original `clm` surface grew organically. `clm ps` here, `clm host
list` there, `clm agent install` somewhere else, with a handful of
interactive prompts that you couldn't script around. The result was a
CLI that worked, but didn't *teach* you what to type next.

`kubectl` solved that problem for containers by enforcing a tiny verb
vocabulary across a large noun space:

```text
kubectl <verb> <resource> [name] [flags]
```

That's it. Once you've internalized `get` / `describe` / `create` /
`delete` / `edit`, the whole tool unfolds — `kubectl get pods` and
`kubectl get nodes` look the same because they *are* the same.

Clawrium now does that for AI agents.

## The new shape

```text
clawctl <group> <verb> [name] [flags]
```

Where `<group>` is one of:

- `host` — machines in your fleet
- `agent` — AI assistant instances running on hosts
- `provider` — inference backends (OpenAI, Anthropic, Bedrock, Ollama, …)
- `integration` — external service bindings (GitHub, Linear, Atlassian, …)
- `channel` — chat surfaces (Discord, Slack)
- `skill` — repo-bundled skills you can attach to agents
- `service` — system-level lifecycle (init, snapshot)

And `<verb>` is one of the kubectl-style five — `get`, `describe`,
`create`, `delete`, `edit` — plus the lifecycle action verbs where
they actually mean something (`start`, `stop`, `restart`, `sync`,
`configure`, `logs`, `open`, `chat`, `attach`, `detach`).

## A few examples

**Yesterday.**

```bash
clm host init 192.168.1.10 --user me
clm host add 192.168.1.10 --alias wolf
clm agent install --type openclaw --host wolf --name claude
clm agent configure claude  # prompts you through 4 stages
clm ps
```

**Today.**

```bash
clawctl host create 192.168.1.10 --user me --bootstrap
clawctl host create 192.168.1.10 --alias wolf
clawctl agent create claude --type openclaw --host wolf
clawctl agent configure claude  # flag-driven, scriptable
clawctl agent get
```

## What `channel` looks like now

Discord and Slack used to live inside the interactive `clm agent
configure` flow — you'd answer a prompt, paste a token, and Clawrium
would write the channel config into the agent's hosts.json entry.

That meant: no `--from-file`, no per-channel CRUD, no way to share a
channel registration across multiple agents.

Channels are now first-class attachables, sibling to `provider` and
`integration`:

```bash
# Register a Discord channel once
clawctl channel registry create eng-support \
    --type discord \
    --bot-token "$DISCORD_BOT_TOKEN"

# Attach to as many agents as you want
clawctl agent channel attach eng-support --agent claude
clawctl agent channel attach eng-support --agent espresso
```

The interactive prompt is gone. `configure` runs to completion with
flags alone — perfect for CI, Ansible playbooks, or just hitting
**up-arrow → enter** without thinking about which stage you're in.

## `sync` finally means something

In the old surface, `clm agent sync` was a soft re-render — sometimes
it picked up changes, sometimes you had to chase it with a manual
restart. The semantics depended on which file you'd edited.

`clawctl agent sync <name>` is now a **drift-to-zero flush**:

1. Re-render every template the agent owns.
2. If anything changed on disk, restart the daemon and wait for it to
   converge.
3. Time-out after 2 minutes (override with `--timeout`).
4. Exit non-zero if the agent didn't reach a healthy state.

Use it as the single command after any config edit. No more "did that
take effect?"

## Output you can pipe

Every `get` now emits kubectl-style padded columns by default and
supports `-o table | json | yaml | wide | name` plus `--no-headers`
and `-l KEY=VALUE` label selectors:

```bash
$ clawctl agent get -o name
agent/wolf-i
agent/espresso
agent/clawrium-d01

$ clawctl agent get -l env=prod -o json | jq '.items[].status'
"Running"
"Running"
```

Action commands stream line-oriented progress events by default and
NDJSON with `-o json`, so wrapping them in shell scripts or CI logs
is straightforward.

## Migration

There's no script. The expected path is:

```bash
# For each agent on each host
clawctl agent sync <agent-name>
```

That re-renders the new templates (the zeroclaw and hermes templates
moved to agent-type prefixes) and rotates the zeroclaw gateway bearer
so the GUI's WebSocket chat picks up the fresh token transparently.

Templates that drifted:

- `zeroclaw/clm-env.conf.j2` → `zeroclaw/zeroclaw-env.conf.j2`
- `zeroclaw/config.toml.j2` → `zeroclaw/zeroclaw-config.toml.j2`
- `hermes/config.yaml.j2` → `hermes/hermes-config.yaml.j2`
- `hermes/.env.j2` → `hermes/hermes.env.j2`
- Systemd drop-in destination: `10-clm-env.conf` → `10-zeroclaw-env.conf`

A guard test (`tests/platform/test_template_naming.py`) prevents the
old `clm-` prefix from coming back by accident.

## The full BEFORE → AFTER mapping

The complete table is in
[`.itx/435/00_PLAN.md` §5](https://github.com/ric03uec/clawrium/blob/main/.itx/435/00_PLAN.md);
the [CHANGELOG](https://github.com/ric03uec/clawrium/blob/main/CHANGELOG.md)
captures it on every release.

If a command you used to type isn't listed there, please open an issue
— the goal of this sweep is to leave no muscle-memory unsupported, and
gaps in the map are bugs.

## Why no alias?

A `clm`→`clawctl` alias would have been one line. We deliberately chose
not to ship it.

Aliases age badly: tutorials get screenshots of the old name, blog
posts paste the wrong help text, contributors copy the alias into new
scripts. A hard cutover is louder for a week, and then it's done.

The next two weeks are the loud part. We're happy to take that trade.
