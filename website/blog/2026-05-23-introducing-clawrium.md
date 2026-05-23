---
slug: introducing-clawrium
title: "Introducing Clawrium: An aquarium for *claws"
authors: [ric03uec]
tags: [announcements]
---

I installed my first [OpenClaw][openclaw] on an old Ubuntu box. Smooth.
Then I dug up a Raspberry Pi and put [ZeroClaw][zeroclaw] on it. A week
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

- Deploy multiple agent types ([OpenClaw][openclaw], [ZeroClaw][zeroclaw],
  [Hermes][hermes]) across hosts on your local network or cloud
- Normalized configuration, secrets, and integrations across every
  supported agent type
- Swap models, rotate secrets, update personas without SSH-ing anywhere
- Install reusable skills onto agents from a shared registry
- One status pane (`clm ps`) for the whole fleet

The aspiration is broader — backups, cost guardrails, central log
aggregation, drift remediation, agent cloning — and I'm building it in
the open as the use cases sharpen. See the [docs][docs] for the full
shape of what's wired up today.

## Why now

The agents I talk to teams about are no longer hobby projects. They're
solving real work — but every team I've spoken to manages more than one,
and once you cross that threshold, the operational burden eats the
productivity gain. One org I talked to runs a separate OpenClaw per
engineering team. The 90% of configuration that's shared (Linear, Slack,
Confluence) is duplicated and managed differently in each instance.
Clawrium pulls those agents under one umbrella.

In the pets-vs-cattle framing, Clawrium agents are still pets. They're
just pets that are well-trained, on a leash, and play well with each
other.

## What I'm building with it

Two real use cases drive the roadmap:

1. **A project assistant for Clawrium itself** — an agent on my local
   network that I talk to over Discord. It files issues, gives status
   updates, captures notes. The bot's name is Maurice; if you join the
   Discord, be nice to it.
2. **Team assistants at work** — one agent per team, tuned to their
   domain and ownership. Reduces the logistics tax on humans.

## Try it

If you want the full picture, the [architecture][architecture] page
covers how the layers fit together, and the [installation][install]
page is the canonical step-by-step.

The 30-second version:

```bash
uv tool install clawrium
clm host init <ip> --user <user>
clm agent install --type openclaw --host <alias>
```

---

- **Repo:** [github.com/ric03uec/clawrium][repo]
- **Issues:** [open one here][issues]
- **Docs:** [ric03uec.github.io/clawrium][docs]

[openclaw]: https://github.com/openclaw/openclaw
[zeroclaw]: https://github.com/zeroclaw-labs/zeroclaw
[hermes]: https://github.com/NousResearch/hermes-agent
[architecture]: /docs/architecture
[install]: /docs/installation
[docs]: /docs/
[repo]: https://github.com/ric03uec/clawrium
[issues]: https://github.com/ric03uec/clawrium/issues
