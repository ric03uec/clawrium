---
slug: hello-world
title: Hello, Clawrium
authors: [ric03uec]
tags: [announcements]
---

Welcome to the Clawrium blog.

Clawrium is a CLI tool (`clm`) for managing AI agent fleets across your local
network. Point it at a machine, and it handles deployment, configuration, and
lifecycle for agents like [zeroclaw][zeroclaw], [openclaw][openclaw], and
[hermes][hermes] — over SSH, with Ansible doing the work underneath.

<!-- truncate -->

## Why a blog

Until now, everything about the project has lived in three places: the
[docs][docs], the [GitHub issues][issues], and release notes attached to
[tags][releases]. That's enough to ship, but it's not enough to explain *why*
we made the choices we did, or to share usage patterns that don't quite
warrant a full doc page.

This blog is for that middle ground:

- **Release highlights** — what changed in a version, in plain English.
- **Design notes** — short pieces on tradeoffs we wrestled with (gateway
  token rotation, native dashboards, skill registries) before the decisions
  ossified into code.
- **Tutorials** — end-to-end walkthroughs that don't fit the reference docs.

## What's next

We're currently working through a backlog of agent UX improvements and
expanding the [skill registry][skills]. Expect posts on those soon. If you
have a topic you'd like to read about, [open an issue][issues] and tag it
`blog`.

[docs]: /docs/
[zeroclaw]: https://github.com/ric03uec/clawrium/tree/main/src/clawrium/platform/registry/zeroclaw
[openclaw]: https://github.com/ric03uec/clawrium/tree/main/src/clawrium/platform/registry/openclaw
[hermes]: https://github.com/ric03uec/clawrium/tree/main/src/clawrium/platform/registry/hermes
[issues]: https://github.com/ric03uec/clawrium/issues
[releases]: https://github.com/ric03uec/clawrium/releases
[skills]: https://github.com/ric03uec/clawrium/tree/main/skills
