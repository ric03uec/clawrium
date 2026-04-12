# Contributing to Clawrium

This guide explains how to contribute to Clawrium using the `/itx:*` workflow skills.

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/ric03uec/clawrium.git
cd clawrium
make install

# 2. Find an issue to work on
gh issue list --label ready

# 3. Start working (in Claude Code)
/itx:execute 42

# 4. Verify your changes
/itx:verify

# 5. Get review
/itx:review-pr
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

Claude Code skills (`/itx:*`) automate the workflow. They handle label transitions, create structured comments, and maintain prompt logs for reproducibility.

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
- `/itx:bug-new`
- `/itx:issue-new`
- `/itx:plan`
- `/itx:execute`
- `/itx:verify`
- etc.

## Workflow

### Overview

```
┌─────────┐    ┌──────────┐    ┌─────────┐    ┌───────┐    ┌─────────────┐    ┌───────────┐    ┌──────┐
│  INBOX  │───▶│ PLANNING │───▶│ PLANNED │───▶│ READY │───▶│ IN PROGRESS │───▶│ IN REVIEW │───▶│ DONE │
│(no label)    │(planning)│    │(planned)│    │(ready)│    │(in-progress)│    │(in-review)│    │(closed)
└─────────┘    └──────────┘    └─────────┘    └───────┘    └─────────────┘    └───────────┘    └──────┘
      │              │               │              │               │                 │
      │              │               │              │               │                 │
   /itx:triage  /itx:plan-create  /itx:plan-scaffold  /itx:execute    /itx:verify    PR merged
```

### Step-by-Step Example

#### 1. Report a Bug

```
You: I tried to install zeroclaw but got a version mismatch error

/itx:bug-new
```

Claude asks: "What should the user be able to do when this bug is fixed?"

You: "User can install zeroclaw without version mismatch errors"

Result: Issue #42 created with title "User can install zeroclaw without version mismatch errors"

#### 2. Plan the Work

```
/itx:plan-create 42
```

Claude:
- Reads the issue
- Explores the codebase
- Posts high-level implementation plan as comment
- Creates subtasks if needed
- Moves issue: `planning` → `planned`

#### 2b. Scaffold Execution (Optional but Recommended)

```
/itx:plan-scaffold 42
```

Claude:
- Reads the plan-build output
- Decides single-phase vs multi-phase execution
- Creates entry/exit criteria for each phase
- Creates subtask issues if multi-phase
- Moves issue: `planned` → `ready`

#### 3. Execute

```
/itx:execute 42
```

Claude uses a structured task checklist approach:

**Planning Phase**:
1. Reads implementation plan from issue
2. Creates task checklist:
   - Implementation tasks (one per phase/step)
   - Verification tasks (tests, lint, ATX review)
3. Sets dependencies between tasks
4. Reviews task list

**Execution Phase**:
1. Gets next pending task (`TaskList()`)
2. Marks task in progress
3. Implements the requirements
4. Marks task completed
5. Checks progress
6. Repeats until all tasks done

**Example Execution Flow**:
```
TaskList() shows:
  #1 [pending] Implement: Update CLI help text
  #2 [pending] Implement: Refactor function names
  #3 [pending] Run test suite
  #4 [pending] Run linter

Agent marks #1 in_progress → implements changes → marks completed
Agent marks #2 in_progress → implements changes → marks completed
Agent marks #3 in_progress → runs tests → marks completed
Agent marks #4 in_progress → runs lint → marks completed
```

Issue moves: `ready` → `in-progress`

#### 4. Verify

```
/itx:verify
```

Claude runs:
```bash
make test   # All tests must pass
make lint   # No lint errors
```

#### 5. Create PR and Review

```
/itx:review-pr
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
| **PLANNED** | `planned` | High-level plan complete, needs scaffolding |
| **READY** | `ready` | Execution plan complete, ready to execute |
| **IN PROGRESS** | `in-progress` | Currently being implemented |
| **IN REVIEW** | `in-review` | PR open, awaiting review |
| **DONE** | (closed) | Complete |

## Skills Reference

### Issue Management

| Skill | When to Use |
|-------|-------------|
| `/itx:bug-new` | Found a bug during development |
| `/itx:bug-update 42 <text>` | Add context to existing bug |
| `/itx:issue-new` | Have a feature idea |
| `/itx:issue-update 42 <text>` | Add context to existing issue |

### Workflow

| Skill | When to Use |
|-------|-------------|
| `/itx:triage` | Review issues without workflow labels |
| `/itx:plan-create 42` | Create high-level implementation plan |
| `/itx:plan-scaffold 42` | Create phased execution with entry/exit criteria |
| `/itx:execute 42` | Start working on a ready issue |
| `/itx:verify` | Before creating PR |
| `/itx:review-pr` | Request code review |
| `/itx:pr-status` | Check status of open PRs |

### Utilities

| Skill | When to Use |
|-------|-------------|
| `/itx:note <text>` | Quick capture idea to NOTES.md |

## Complex Issues: Parent/Subtask Pattern

For large issues, `/itx:plan` may create subtasks:

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
/itx:execute 100

# Or execute individual subtask
/itx:execute 101
```

### Completion Rules

- Subtask done = PR merged for that subtask
- Parent done = ALL subtasks done

## Parallel Execution (Recommended)

Work on multiple issues simultaneously using git worktrees and tmux.

### Why Parallel Execution?

- **Speed**: Work on independent issues concurrently
- **No conflicts**: Each issue gets its own isolated directory
- **Autonomous**: Claude runs without permission prompts in tmux

### Quick Start

```bash
# In main repo, spawn parallel executions
/itx:execute 35 in a subtree
/itx:execute 42 in a subtree
/itx:execute 48 in a subtree

# Attach to see progress
tmux attach -t itx/exec
```

### How It Works

```
/itx:execute 35 in a subtree
       │
       ▼
┌──────────────────────────────┐
│ 1. Create worktree           │
│    clawrium-issue-35/        │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ 2. Spawn tmux window         │
│    Session: itx/exec         │
│    Window: issue-35          │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ 3. Run claude autonomously   │
│    --dangerously-skip-       │
│    permissions               │
└──────────────────────────────┘
```

### Worktree Layout

```
~/projects/
├── clawrium/                  # Main repo (you are here)
├── clawrium-issue-35/         # Worktree for issue 35
├── clawrium-issue-42/         # Worktree for issue 42
└── clawrium-issue-48/         # Worktree for issue 48
```

### tmux Session Management

```bash
# View all execution windows
tmux list-windows -t itx/exec

# Attach to session
tmux attach -t itx/exec

# Switch between windows (inside tmux)
# Ctrl-a n    (next window)
# Ctrl-a p    (previous window)
# Ctrl-a 0-9  (window by number)

# Kill a specific window
tmux kill-window -t "itx/exec:issue-35"
```

### Cleanup After Merge

```bash
# Remove worktree
git worktree remove ../clawrium-issue-35

# List remaining worktrees
git worktree list

# Clean up stale worktree references
git worktree prune
```

### Without tmux

If tmux is not available, you'll be prompted:
- **Subagent**: Run as background task (non-interactive)
- **Same session**: Continue interactively (will ask for permissions)

## Code Review

All PRs use ATX automated review. Requirements:

- **Rating**: Must be > 3/5
- **Blocking issues**: Must be zero

If review fails, fix issues and re-run `/itx:review-pr`.

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
**Skill**: /itx:plan
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
/itx:bug-new Found null pointer in host validation
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
/itx:review-pr
```
