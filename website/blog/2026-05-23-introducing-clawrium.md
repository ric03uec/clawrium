---
slug: introducing-clawrium
title: "Introducing Clawrium: An aquarium for *claws"
authors: [ric03uec]
tags: [announcements]
---

I installed my first [Openclaw][openclaw] on an old Ubuntu box. Smooth.
Then I dug up a Raspberry Pi and put [Zeroclaw][zeroclaw] on it. A week
later I was spending more time on SSH gymnastics than actually using the
agents — upgrading one, swapping a model on another, debugging logs on a
third, rotating a token on the fourth. The agents were fine. The
orchestration around them was the problem.

<!-- truncate -->

That's when it clicked: this is a standardization and orchestration
problem, and it looks a lot like what Kubernetes solved for containers.
Running one agent is easy. Running five across your network while
juggling SSH keys, model configs, personas, and channel integrations is
where it falls apart.

So I built **Clawrium** — an aquarium for *claws. A single CLI (`clm`)
that treats your AI agents as a fleet.

## What `clm` does today

- Deploy multiple agent types ([openclaw][openclaw], [zeroclaw][zeroclaw],
  [hermes][hermes]) across hosts on your local network or cloud
- Normalized configuration, secrets, and integrations across every
  supported agent type
- Swap models, rotate secrets, update personas without SSH-ing anywhere
- Install reusable [skills][skills] onto agents from a shared registry
- One status pane (`clm ps`) for the whole fleet

The aspiration is broader — backups, cost guardrails, central log
aggregation, drift remediation, agent cloning — and I'm building it in
the open as the use cases sharpen.

## Why now

The agents I talk to teams about are no longer hobby projects. They're
solving real work — but every team I've spoken to manages more than one,
and once you cross that threshold, the operational burden eats the
productivity gain. One org I talked to runs a separate Openclaw per
engineering team. The 90% of configuration that's shared (Linear, Slack,
Confluence) is duplicated and managed differently in each instance.
Clawrium pulls those agents under one umbrella.

In the pets-vs-cattle framing, Clawrium agents are still pets. They're
just pets that are well-trained, on a leash, and play well with each
other.

## What I'm building it with

Two real use cases drive the roadmap:

1. **A project assistant for Clawrium itself** — an agent on my local
   network that I talk to over Discord. It files issues, gives status
   updates, captures notes. The bot's name is Maurice; if you join the
   Discord, be nice to it.
2. **Team assistants at work** — one agent per team, tuned to their
   domain and ownership. Reduces the logistics tax on humans.

## Architecture, briefly

Four layers, each with a single responsibility:

- **Transport** — Ansible, for idempotency, host management, and drift.
- **Configuration** — normalized config (helm-chart-style) across agent
  types.
- **Execution** — merging, templating, workflows, domain models.
- **UX** — CLI and TUI. Kept deliberately thin.

## Try it

```bash
uv tool install clawrium
clm host init <ip> --user <user>
clm agent install --type openclaw --host <alias>
```

Full walkthrough in the [installation docs][install] and
[quickstart][quickstart].

- **GitHub:** [github.com/ric03uec/clawrium][repo]
- **Issues / feature requests:** [open one here][issues]

Clawrium is the control plane for a fleet of specialized agents working
together. More posts coming as the project finds its shape.

[openclaw]: https://github.com/ric03uec/clawrium/tree/main/src/clawrium/platform/registry/openclaw
[zeroclaw]: https://github.com/ric03uec/clawrium/tree/main/src/clawrium/platform/registry/zeroclaw
[hermes]: https://github.com/ric03uec/clawrium/tree/main/src/clawrium/platform/registry/hermes
[skills]: https://github.com/ric03uec/clawrium/tree/main/skills
[install]: /docs/installation
[quickstart]: /docs/guides/quickstart
[repo]: https://github.com/ric03uec/clawrium
[issues]: https://github.com/ric03uec/clawrium/issues
