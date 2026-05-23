# Issue #499 — User can configure MCP servers once and attach them to any agent

GitHub: https://github.com/ric03uec/clawrium/issues/499

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-23T00:00:00Z
**Model**: claude-opus-4-7

```prompt
add support for MCP servers. user should be able to configure mcp servers in clawrium. once configured, they can be used by one or more agents as rquired. this wwll be like providers. investivage whether tools like toolhive can be used for this.
```

**Decisions captured during issue creation**:

- Customer outcome: configure MCP servers once + attach to any agent (provider/integration shape, not per-agent-only and not a curated catalog).
- v1 scope: hermes only. openclaw and zeroclaw follow as dedicated subtasks.
- Runtime hosting question: deferred to `/itx:plan-create`. Spike must compare at minimum toolhive (containers), plain stdio spawn by the daemon, and dedicated systemd units (mirrors the #478 dashboard pattern), with a written rationale for whichever is picked.

**Output**: Created GitHub issue #499 with customer-outcome title and an open-question section calling out the runtime-hosting decision for the planning stage.
