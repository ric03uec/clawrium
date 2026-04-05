# Contributing to Clawrium

This guide explains how to contribute to Clawrium using the `/clm:*` workflow skills.

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/ric03uec/clawrium.git
cd clawrium
make install

# 2. Find an issue to work on
gh issue list --label ready

# 3. Start working (in Claude Code)
/clm:execute 42

# 4. Verify your changes
/clm:verify

# 5. Get review
/clm:review-pr
```

## Core Concepts

### GitHub as Source of Truth

All work is tracked in GitHub Issues. No separate planning directories or files - issues move through states via labels.

### Customer Outcome Titles

Issue titles describe what the user can do, not what you'll implement:

| Type | Bad | Good |
|------|-----|------|
| Bug | "Fix registry validation" | "User can install claws without version errors" |
| Feature | "Add backup command" | "User can backup claw configurations" |

### Workflow Skills

Claude Code skills (`/clm:*`) automate the workflow. They handle label transitions, create structured comments, and maintain prompt logs for reproducibility.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- [gh](https://cli.github.com/) GitHub CLI (authenticated)
- [Claude Code](https://claude.ai/claude-code) CLI

### Installation

```bash
# Clone repository
git clone https://github.com/ric03uec/clawrium.git
cd clawrium

# Install dependencies
make install

# Verify setup
make test
make lint
```

### Verify Skills are Available

In Claude Code, run `/help` to see available skills. You should see:
- `/clm:bug-new`
- `/clm:issue-new`
- `/clm:plan`
- `/clm:execute`
- `/clm:verify`
- etc.

## Workflow

### Overview

```
┌─────────┐    ┌──────────┐    ┌───────┐    ┌─────────────┐    ┌───────────┐    ┌──────┐
│  INBOX  │───▶│ PLANNING │───▶│ READY │───▶│ IN PROGRESS │───▶│ IN REVIEW │───▶│ DONE │
│(no label)    │(planning)│    │(ready)│    │(in-progress)│    │(in-review)│    │(closed)
└─────────┘    └──────────┘    └───────┘    └─────────────┘    └───────────┘    └──────┘
      │              │              │               │                 │
      │              │              │               │                 │
  /clm:triage   /clm:plan    /clm:execute    /clm:verify      PR merged
```

### Step-by-Step Example

#### 1. Report a Bug

```
You: I tried to install zeroclaw but got a version mismatch error

/clm:bug-new
```

Claude asks: "What should the user be able to do when this bug is fixed?"

You: "User can install zeroclaw without version mismatch errors"

Result: Issue #42 created with title "User can install zeroclaw without version mismatch errors"

#### 2. Plan the Work

```
/clm:plan 42
```

Claude:
- Reads the issue
- Explores the codebase
- Posts implementation plan as comment
- Creates subtasks if needed
- Moves issue: `planning` → `ready`

#### 3. Execute

```
/clm:execute 42
```

Claude:
- Reads the plan from issue comments
- Implements the changes
- Moves issue: `ready` → `in-progress`

#### 4. Verify

```
/clm:verify
```

Claude runs:
```bash
make test   # All tests must pass
make lint   # No lint errors
```

#### 5. Create PR and Review

```
/clm:review-pr
```

Claude:
- Creates PR if not exists
- Requests ATX code review
- Moves issue: `in-progress` → `in-review`

#### 6. Merge

After review passes and PR merges, issue closes automatically.

## Issue States

| State | Label | Description |
|-------|-------|-------------|
| **INBOX** | (none) | New issues awaiting triage |
| **NEEDS TRIAGE** | `needs-triage` | Bugs or issues needing clarification |
| **PLANNING** | `planning` | Ready to be planned |
| **READY** | `ready` | Plan complete, ready to execute |
| **IN PROGRESS** | `in-progress` | Currently being implemented |
| **IN REVIEW** | `in-review` | PR open, awaiting review |
| **DONE** | (closed) | Complete |

## Skills Reference

### Issue Management

| Skill | When to Use |
|-------|-------------|
| `/clm:bug-new` | Found a bug during development |
| `/clm:bug-update 42 <text>` | Add context to existing bug |
| `/clm:issue-new` | Have a feature idea |
| `/clm:issue-update 42 <text>` | Add context to existing issue |

### Workflow

| Skill | When to Use |
|-------|-------------|
| `/clm:triage` | Review issues without workflow labels |
| `/clm:plan 42` | Create implementation plan for issue |
| `/clm:execute 42` | Start working on a ready issue |
| `/clm:verify` | Before creating PR |
| `/clm:review-pr` | Request code review |
| `/clm:pr-status` | Check status of open PRs |

### Utilities

| Skill | When to Use |
|-------|-------------|
| `/clm:note <text>` | Quick capture idea to NOTES.md |

## Complex Issues: Parent/Subtask Pattern

For large issues, `/clm:plan` may create subtasks:

```
Parent Issue #100: "User can manage multiple hosts in batch"
    │
    ├── #101: [#100] Add batch host validation
    ├── #102: [#100] Implement parallel execution
    └── #103: [#100] Add progress reporting
```

### Working with Subtasks

```bash
# Execute parent (runs all subtasks sequentially)
/clm:execute 100

# Or execute individual subtask
/clm:execute 101
```

### Completion Rules

- Subtask done = PR merged for that subtask
- Parent done = ALL subtasks done

## Code Review

All PRs use ATX automated review. Requirements:

- **Rating**: Must be > 3/5
- **Blocking issues**: Must be zero

If review fails, fix issues and re-run `/clm:review-pr`.

See [AGENTS.md](AGENTS.md) for review format.

## Manual Workflow

You can work without skills too:

```bash
# 1. Pick an issue
gh issue view 42

# 2. Create branch
git checkout -b issue-42-fix-version-check

# 3. Make changes
# ... edit files ...

# 4. Verify
make test && make lint

# 5. Commit
git add -A
git commit -m "fix: resolve version mismatch in registry

Closes #42"

# 6. Push and create PR
git push -u origin issue-42-fix-version-check
gh pr create --title "fix: resolve version mismatch" --body "Closes #42"

# 7. Update labels manually
gh issue edit 42 --remove-label ready --add-label in-progress
gh issue edit 42 --remove-label in-progress --add-label in-review
```

## Prompt Logging

Skills automatically log prompts in issue comments:

```markdown
<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /clm:plan
**Timestamp**: 2026-04-04T10:30:00Z
**Model**: claude-opus-4-5-20251101

```prompt
<the prompt that triggered this action>
```

</details>
```

This enables:
- **Reproducibility**: Re-run the same prompt
- **Learning**: See what prompts led to what plans
- **Debugging**: Trace decisions to original intent

## FAQ

### How do I find issues to work on?

```bash
# Issues ready for execution
gh issue list --label ready

# All open issues
gh issue list

# Issues I created
gh issue list --author @me
```

### What if I discover a bug while working?

```
/clm:bug-new Found null pointer in host validation
```

This creates a separate tracked issue without derailing your current work.

### Can I skip the planning phase?

For trivial fixes, you can manually move an issue from `planning` to `ready`:

```bash
gh issue edit 42 --remove-label planning --add-label ready
```

### How do I update my PR after review feedback?

```bash
# Make fixes
git add -A
git commit -m "fix: address review feedback"
git push

# Re-request review
/clm:review-pr
```
