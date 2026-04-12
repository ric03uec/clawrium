---
sidebar_position: 3
---

# Contributing Workflow

This guide explains how to contribute to Clawrium using the `/itx:*` workflow skills.

## Workflow Overview

### Parent issue lifecycle

```
                      ┌─────────┐
                      │  inbox  │
                      └────┬────┘
                           │
                           │  Maintainer changes label
                           ▼
                      ┌─────────┐
                      │ queued  │
                      └────┬────┘
                           │
                           │  Maintainer merges plan PR
                           ▼
  ┌─────────────────┐ ┌─────────┐ ◄──────────────────────────┐
  │ xs: maintainer  │ │ planned │                             │
  │ labels xs +     │ └────┬────┘                             │
  │ executing       │      │                                  │
  └───────┬─────────┘      │  ┌───────────────┐    ┌─────────┴─────────┐
          │                │  │ s: /itx:execute│    │ /itx:amend plan   │
          │                │  └──────┬────────┘    │ → back to planned │
          │                │         :             └───────────────────┘
          │                ▼         :
          │           ┌──────────┐   :
          └ ─ ─ ─ ─ ▶ │executing │ ◄┘    Maintainer creates
                      └────┬─────┘        subtask issues
                           │
                           │  All subtasks done + verified
                           ▼
                    ┌──────────────┐
                    │ done (closed)│
                    └──────────────┘
```

### Subtask issue lifecycle

```
  ┌─────────┐  PR opened  ┌───────────┐  PR merged  ┌──────────────┐
  │  inbox  │────────────▶│ executing │────────────▶│ done (closed)│
  └─────────┘             └───────────┘             └──────────────┘
```

### Legend

```
  ────▶  Forward transition
  ────▶  Amend (back to planned)
  ═ ═ ▶  xs fast path (inbox → executing)
  ····▶  s shortcut
```

## Issue States

| State | Label | Description |
|-------|-------|-------------|
| **INBOX** | (none) | New issues awaiting triage |
| **NEEDS TRIAGE** | `needs-triage` | Bugs or issues needing clarification |
| **PLANNING** | `planning` | Ready to be planned |
| **PLANNED** | `planned` | High-level plan complete, needs scaffolding |
| **READY** | `ready` | Execution plan complete, ready to execute |
| **IN PROGRESS** | `in-progress` | Currently being implemented |
| **IN REVIEW** | `in-review` | PR open, awaiting review |
| **DONE** | (closed) | Complete |

## Planning Phases

### Phase 1: Plan-Build (`/itx:plan-create`)

Creates a high-level implementation plan with:
- Overview of the approach
- Files to modify
- Key implementation steps
- Test strategy
- Subtasks (if needed)

**Transition**: `planning` → `planned`

### Phase 2: Plan-Scaffold (`/itx:plan-scaffold`)

Creates phased execution with entry/exit criteria:

```markdown
### Phase N: <Name>

**Entry Criteria** (must be true to start):
- Prerequisite phase complete
- Environment prepared
   
**Exit Criteria** (must be true to complete):
- All tests passing
- Lint/typecheck clean
   
**Dependencies**: Phase <N-1>

**Files Affected**:
- `path/to/file.ext` - <change type>

**Complexity**: simple/moderate/complex
```

**Transition**: `planned` → `ready`

## Entry/Exit Criteria Patterns

### Entry Criteria Patterns

- Prerequisite phase complete
- Environment prepared (dependencies, config)
- Data/fixtures available
- Branch created
- Tests passing from previous phase

### Exit Criteria Patterns

- All tests passing
- Lint/typecheck clean
- Manual verification checklist complete
- Documentation updated
- No regressions introduced

## Phase Ordering Rules

1. **Foundation phases first** - schemas, models, database changes
2. **Core logic second** - services, business rules, calculations
3. **Integration third** - APIs, handlers, external systems
4. **Presentation last** - UI, docs, help text

## Parallel Execution

Independent phases can execute in parallel. Use entry/exit criteria to identify dependencies:

```
Phase 1: Database Schema
   ↓
Phase 2a: Service Layer ←─┐
   ↓                      │ (parallel after Phase 1)
Phase 2b: API Layer    ←─┘
   ↓
Phase 3: UI Integration
```

## Skills Reference

### Issue Management

| Skill | When to Use |
|-------|-------------|
| `/itx:bug-new` | Found a bug during development |
| `/itx:issue-new` | Have a feature idea |

### Workflow

| Skill | When to Use |
|-------|-------------|
| `/itx:triage` | Review issues without workflow labels |
| `/itx:plan-create 42` | Create high-level implementation plan |
| `/itx:plan-scaffold 42` | Create phased execution with entry/exit criteria |
| `/itx:execute 42` | Start working on a ready issue |
| `/itx:verify` | Before creating PR |
| `/itx:review-pr` | Request code review |

### Utilities

| Skill | When to Use |
|-------|-------------|
| `/itx:note <text>` | Quick capture idea to NOTES.md |

## Complex Issues: Parent/Subtask Pattern

For large issues, `/itx:plan-create` may create subtasks:

```
Parent Issue #100: "User can manage multiple hosts in batch"
    │
    ├── #101: [#100] Add batch host validation
    ├── #102: [#100] Implement parallel execution
    └── #103: [#100] Add progress reporting
```

### Execution

```bash
# Execute parent (runs all subtasks sequentially)
/itx:execute 100

# Or execute individual subtask
/itx:execute 101
```

### Completion Rules

- Subtask done = PR merged for that subtask
- Parent done = ALL subtasks done
