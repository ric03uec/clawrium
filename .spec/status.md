# Spec Workflow Status

> Last updated: 2026-03-23

## Issue Types

| Type | Description | Scope |
|------|-------------|-------|
| `bug` | Something not working as expected | Fix only |
| `enhancement` | Small improvement, no significant changes | Single issue completes |
| `feature` | Large item needing discussion and approval | Multiple issues, specs required |

---

## In Progress

| Issue | Type | Title | Phase | Owner | Started |
|-------|------|-------|-------|-------|---------|
| - | - | - | - | - | - |

## Pending

| Issue | Type | Title | Priority | Created | Blocked By |
|-------|------|-------|----------|---------|------------|
| #15 | enhancement | Host reset command (destructive cleanup) | medium | 2026-03-22 | - |
| #13 | enhancement | Add architecture + design docs with domain model | low | 2026-03-22 | - |
| #12 | enhancement | Add GitHub issue templates, PRD template, CONTRIBUTING | medium | 2026-03-22 | - |
| #11 | feature | PRD: Implement NemoClaw reference architecture | high | 2026-03-21 | - |
| #10 | feature | PRD: Migrate Clawrium data storage to SQLite | medium | 2026-03-21 | - |
| #9 | feature | PRD: Localhost web UI dashboard | low | 2026-03-21 | - |
| #8 | feature | PRD: TUI dashboard for fleet overview | medium | 2026-03-21 | - |

## Completed

| Issue | Type | Title | Completed | Duration |
|-------|------|-------|-----------|----------|
| #3 | bug | Hardware detection fails: ansible-runner not executing | 2026-03-21 | 1h |
| #1 | bug | Key lookup mismatch: keys stored by alias but looked up by IP | 2026-03-21 | 2h |

---

## How to Use This File

Agents should:
1. Check "In Progress" first - continue existing work
2. Pick from "Pending" if nothing in progress (highest priority first)
3. Update status when starting/completing work

### Issue Type Guidelines

- **bug**: Broken functionality. Fix and move on.
- **enhancement**: Small wins. One person can complete in a session.
- **feature**: Needs spec → plan → execute flow. May span multiple sessions.

### Status Transitions

```
idea → pending (after spec written)
pending → in-progress (when work starts)  
in-progress → completed (all tasks done)
```

### Adding New Issues

1. Run `/clawrium:idea` to capture raw thoughts
2. Run `/clawrium:write-spec <issue>` to formalize
3. Add row to "Pending" table with appropriate type

### Priority Levels

| Priority | Meaning |
|----------|---------|
| `high` | Critical path, do first |
| `medium` | Important but not blocking |
| `low` | Nice to have, do when time permits |
