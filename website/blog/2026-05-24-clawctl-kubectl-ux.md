---
slug: clm-to-clawctl-migration
title: "Moving to a standardized CLI interface with clawctl"
authors: [ric03uec]
tags: [announcements, breaking-changes]
---

If you've been using Clawrium with `clm`, the next install replaces it with **`clawctl`**. Same hosts, same agents, same `~/.config/clawrium/` state — a single, consistent, kubectl-style command surface across the entire fleet.

<!-- truncate -->

<p align="center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 240" width="560" height="240" role="img" aria-label="clm to clawctl command mapping">
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0 0 L10 5 L0 10 z" fill="#64748b"/>
    </marker>
  </defs>
  <rect x="10" y="10" width="220" height="220" rx="6" fill="none" stroke="#334155" stroke-width="1"/>
  <rect x="330" y="10" width="220" height="220" rx="6" fill="none" stroke="#334155" stroke-width="1"/>
  <text x="120" y="32" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="13" font-weight="600" fill="#94a3b8">clm (before)</text>
  <text x="440" y="32" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="13" font-weight="600" fill="#94a3b8">clawctl (after)</text>
  <text x="24" y="64" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#ef4444">clm ps</text>
  <text x="24" y="98" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#ef4444">clm host list</text>
  <text x="24" y="132" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#ef4444">clm agent install</text>
  <text x="24" y="166" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#ef4444">clm agent remove</text>
  <text x="24" y="200" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#ef4444">clm agent show NAME</text>
  <text x="344" y="64" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#22c55e">clawctl agent get</text>
  <text x="344" y="98" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#22c55e">clawctl host get</text>
  <text x="344" y="132" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#22c55e">clawctl agent create</text>
  <text x="344" y="166" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#22c55e">clawctl agent delete</text>
  <text x="344" y="200" font-family="ui-monospace, SFMono-Regular, monospace" font-size="14" font-weight="500" fill="#22c55e">clawctl agent describe NAME</text>
  <path d="M230 60 L330 60" stroke="#64748b" stroke-width="1.5" fill="none" marker-end="url(#arr)"/>
  <path d="M230 94 L330 94" stroke="#64748b" stroke-width="1.5" fill="none" marker-end="url(#arr)"/>
  <path d="M230 128 L330 128" stroke="#64748b" stroke-width="1.5" fill="none" marker-end="url(#arr)"/>
  <path d="M230 162 L330 162" stroke="#64748b" stroke-width="1.5" fill="none" marker-end="url(#arr)"/>
  <path d="M230 196 L330 196" stroke="#64748b" stroke-width="1.5" fill="none" marker-end="url(#arr)"/>
</svg>
</p>

## Why this matters to you

- **One grammar, six resources.** `get`, `describe`, `create`, `delete`, `apply`-style verbs work the same way across `host`, `agent`, `provider`, `channel`, `integration`, `skill`. Learn it once.
- **Pipe-friendly output.** Every `get` supports `-o yaml`, `-o json`, `-o name`, and `--no-headers`. Scripts compose; output is no longer a moving target.
- **Tab completion that works.** `clawctl completion bash` (or `zsh`/`fish`) gives you completion across every group, verb, and flag.
- **One place to see everything about an agent.** `clawctl agent describe <name>` shows attached providers, channels, skills, secrets, onboarding state, and host details in one block.
- **`agent get` reads like `kubectl get pods`.** STATUS / AGE columns, predictable sort, scriptable.
- **Channels are a real resource.** Register a Discord or Slack channel once with `clawctl channel registry create`, attach it to as many agents as you want with `clawctl agent channel attach`. No more per-agent re-entry.

## What it looks like

Three real outputs from the live fleet (no synthetic data — these are verbatim from the validation transcript).

### List your fleet

```text
$ clawctl agent get
NAME             TYPE       HOST     PROVIDER   STATUS   AGE
wolf-i           openclaw   wolf-i   -          ready    42d
espresso         hermes     wolf-i   -          ready    13d
maurice          hermes     wolf-i   -          ready    2d
clawrium-d01     zeroclaw   wolf-i   -          ready    5d
nemotron-beta    zeroclaw   wolf-i   -          ready    4d
nemotron-alpha   zeroclaw   wolf-i   -          ready    2d
```

### Look at one agent

```text
$ clawctl agent describe maurice
Name:       maurice
Kind:       agent
Type:       hermes
Version:    2026.5.7
Host:       wolf-i (wolf.<redacted>.ts.net)
Provider:   -
Status:     ready
Age:        2d
Installed:  2026-05-22T20:39:02Z

Channels (1):
  discord

Skills (0):
Integrations (0):
```

### Machine-readable

```text
$ clawctl host get -o yaml
- kind: host
  name: wolf-i
  hostname: wolf.<redacted>.ts.net
  user: xclm
  status: ready
  age_seconds: 3774446
  aliases: [wolf-i]
  addresses:
    - address: 192.168.1.Y
      is_primary: false
    - address: wolf.<redacted>.ts.net
      is_primary: true
      label: tailscale
```

## Migration

Install `clawctl` (it ships as the new binary in the same `clawrium` package). Existing agents on existing hosts keep running — `clawctl agent get` will list them immediately. The first `clawctl agent sync <agent>` you run picks up the new template names.

```bash
uv tool uninstall clm 2>/dev/null || true
uv tool install clawrium
clawctl agent get          # confirm your fleet is intact
```

The full command-by-command mapping lives in the [CLI reference docs](/docs/reference/cli) — one page per resource (`agent`, `host`, `provider`, `channel`, `integration`, `skill`).

## Breaking changes

- **No `clm` alias.** The old binary is gone; the verb grammar is different enough that an alias would mislead more than help.
- **Channels moved out of `agent configure`.** Use `clawctl channel registry create` then `clawctl agent channel attach`. The old `--stage channels` flag prints a deprecation pointer.
- **Some templates renamed** on disk (e.g. `clm-env.conf.j2` → `zeroclaw-env.conf.j2`). The first `clawctl agent sync` per agent cleans up the legacy dropin automatically.

Full migration recipe in `CHANGELOG.md` under `[Unreleased] BREAKING`.

## Where to go from here

- [CLI reference](/docs/reference/cli) — every verb, every flag
- [Installation guide](/docs/installation) — fresh install + agent quickstart
- [GitHub issues](https://github.com/ric03uec/clawrium/issues) — for migration snags
