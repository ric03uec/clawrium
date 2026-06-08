---
sidebar_position: 5
---

# Per-Agent Local Skills

<!-- Mirror of docs/local-skills.md in the engineering docs.
     Body must match the engineering docs (modulo this Docusaurus
     frontmatter). When updating, edit docs/local-skills.md first. -->

## What it does

Clawrium can attach **local skills** to an individual agent — skill templates
copied from a skill registry into the agent's own workspace. Local skills are
distinct from the bundled skill registry (`clawrium/`, `openclaw/`, `hermes/`,
`zeroclaw/`) in that they live with the agent and follow that agent's
lifecycle (added, synced, removed) rather than being a global catalog entry.

## Where they live

- **Catalog** (read-only templates): `~/.config/clawrium/skills/` for user
  overlays, plus the bundled registries baked into the `clawctl` install.
- **Per-agent** (after attach): synced into the agent host's
  `~/.hermes/skills/<namespace>/<skill-name>/` (hermes) or equivalent for
  other agent types.

## CLI

Inspect a catalog template before installing:

```bash
clawctl skill registry get
clawctl skill registry describe clawrium/tdd
```

Add a skill to a specific agent:

```bash
clawctl agent skill add <agent-name> --from-template clawrium/tdd
clawctl agent sync <agent-name>
```

The desired-state record stores the **bare** skill name (e.g. `tdd`); the
fully-qualified `<registry>/<name>` reference is the catalog form used at
install time.

## GUI

Phase C (#638) adds the same lifecycle to the GUI: skills can be browsed,
attached, and removed per-agent from the fleet view.

## Background

- Parent issue: [#411](https://github.com/ric03uec/clawrium/issues/411)
- Phase A — core helpers: [#636](https://github.com/ric03uec/clawrium/pull/636)
- Phase B — CLI lifecycle: [#637](https://github.com/ric03uec/clawrium/pull/637)
- Phase C — GUI lifecycle: [#638](https://github.com/ric03uec/clawrium/pull/638)

See `AGENTS.md` (root) for the broader skill registry concept.
