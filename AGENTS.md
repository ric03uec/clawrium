# Clawrium - An aquarium for *claws

## How It Works

Clawrium is a CLI tool (`clm`) that manages AI agent fleets across your local network. Point it at any machine, and it handles deployment, configuration, and lifecycle management via SSH and Ansible.

```
Your Machine (clm CLI)
    │
    ├── Host A ──> zeroclaw instance
    ├── Host B ──> openclaw instance
    └── Host C ──> nemoclaw instance, zeroclaw instance
```

## Why

- **Single pane of glass**: Manage all agents from one CLI instead of SSH-ing to each host
- **Consistent lifecycle**: Same commands for install, configure, start, stop, remove across all agent types
- **Secrets management**: Secure API key storage with per-agent isolation
- **Fleet visibility**: `clm ps` shows status of all agents across all hosts

## Who Is This For

- **Homelabbers**: Run multiple AI assistants on spare hardware
- **Teams**: Standardize agent deployment across developer machines
- **Experimenters**: Try different models/agents without manual setup on each host

## Quickstart

```bash
# Install
uv tool install clawrium

# Add a host
clm host init 192.168.1.100 --user myuser
clm host add 192.168.1.100 --alias mybox

# Install an agent
clm agent install --type openclaw --host mybox

# Configure and start
clm agent configure <agent-name>
clm agent start <agent-name>

# Check fleet status
clm ps
```

## Key Concepts

- **Host**: A machine in your network that runs one or more agents
- **Agent**: An AI assistant instance (zeroclaw, nemoclaw, or openclaw)
- **Agent Type**: The specific AI assistant implementation (e.g., zeroclaw, nemoclaw, openclaw)
- **Agent Name**: The unique identifier for an installed agent instance
- **Registry**: Platform-defined agent types with versions, dependencies, and templates

## Resources

- Repository: https://github.com/ric03uec/clawrium
- Project Board: https://github.com/users/ric03uec/projects/1
- Version: 26.04.03

## Tech Stack

- **CLI**: Python + Typer
- **Execution**: ansible-runner
- **Packaging**: uv/uvx
- **User Data**: `~/.config/clawrium/`

## Development

Always use `make` commands to run tests and validate changes:

```bash
make test       # Run tests (required before commits)
make lint       # Check code style
make format     # Format code
make test-cov   # Run tests with coverage
```

## Development Workflow

GitHub Issues are the single source of truth. See [CONTRIBUTING.md](CONTRIBUTING.md) for full workflow documentation.

### Worktree Convention

For parallel issue execution, use git worktrees with this naming:

```
<repo-parent>/<repo-name>-issue-<number>/
```

Example:
```
~/projects/clawrium/           # Main repo
~/projects/clawrium-issue-35/  # Worktree for issue 35
```

Trigger with: `/itx:execute 35 in a subtree` or `/itx:execute 35 --worktree`

### Quick Reference

```
New Issue → /itx:triage → /itx:plan-create → /itx:plan-scaffold → /itx:execute → /itx:verify → /itx:review-pr → Merge
```

### Skills

| Skill | Purpose |
|-------|---------|
| `/itx:bug-new` | Create bug issue (asks for customer outcome) |
| `/itx:issue-new` | Create feature issue (asks for customer outcome) |
| `/itx:triage` | Review unlabeled issues |
| `/itx:plan-create <n>` | Create high-level implementation plan |
| `/itx:plan-scaffold <n>` | Create phased execution with entry/exit criteria |
| `/itx:execute <n>` | Execute issue (parent or subtask) |
| `/itx:verify` | Run tests and lint |
| `/itx:review-pr [n]` | ATX review of PR |

### Task-Based Execution

The `/itx:execute` skill uses a structured task checklist approach to prevent getting lost during execution:

**Planning Phase (Mandatory)**:
1. Read implementation plan from issue
2. Create implementation tasks using `TaskCreate()` for each phase/step
3. Create verification tasks (tests, lint, ATX review)
4. Set dependencies between tasks if needed
5. Review task list to confirm structure

**Execution Phase**:
1. Get next pending task using `TaskList()`
2. Mark task `in_progress` using `TaskUpdate()`
3. Execute the task requirements
4. Mark task `completed`
5. Check progress with `TaskList()`
6. Repeat until all tasks done

**Example Task Creation**:
```python
# Implementation task
TaskCreate(
    subject="Implement: Update CLI help text",
    description="Update all help text in src/clawrium/cli/agent.py",
    activeForm="Updating CLI help text"
)

# Verification task
TaskCreate(
    subject="Run test suite",
    description="Execute 'make test' and ensure all tests pass",
    activeForm="Running tests"
)
```

**Recovery Mechanism**:
If execution feels unclear or you lose orientation:
- Run `TaskList()` to see current state
- Check which task is `in_progress`
- Review that task's description
- Complete current task before starting next

## Review

<atx-review-requirements>
**MANDATORY**: All code changes MUST include @atx-ci review before merging.

### Iteration Requirements
1. Request review using `mcp__atx__review_changes` or `mcp__atx__request_review`
2. Fix ALL blocking issues (B1, B2, etc.)
3. Iterate until: Rating > 3/5 AND no blocking issues remain
4. Document each review iteration in commit message and PR body

### When to Request Review
- Before creating a commit with code changes
- After fixing issues from previous review
- Before marking PR as ready for merge
</atx-review-requirements>

<commit-format>
### Commit Message Format

Include ATX review summary after the commit body:

```
feat(component): short description

Detailed explanation of changes.

Closes #XX

ATX Review Summary
Review 1: Rating 2/5 | Cost: $0.12 | Time: 45s | Agents: leader, cli-ux
Blocking issues:
| # | Status | Issue |
|---|--------|-------|
| B1 | Fixed | Description of issue and fix |
| B2 | Out-of-scope | Pre-existing issue, tracked in #YY |

Warnings:
| # | Status | Warning |
|---|--------|---------|
| W1 | Fixed | Description |
| W2 | Acknowledged | Will address in follow-up |

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: @atx-ci <269048218+atx-ci@users.noreply.github.com>
```
</commit-format>

<pr-format>
### PR Body Format

Include detailed ATX review after Summary and Testing sections:

```markdown
## ATX Review Summary

**Final Review: Rating 4/5**
**Total Cost: $0.20 | Total Time: 1m 17s**

| Review | Rating | Blocking Issues | Status | Cost | Time | Agents |
|--------|--------|-----------------|--------|------|------|--------|
| 1 | 2/5 | B1, B2, B3 | All fixed | $0.12 | 45s | leader, cli-ux, test-coverage |
| 2 | 4/5 | None | Ready | $0.08 | 32s | leader, cli-ux |

> **Note**: ATX does not expose model information per agent.

<details>
<summary>Review 1 Details (Rating 2/5)</summary>

**Blocking Issues:**

| # | File | Issue | Resolution |
|---|------|-------|------------|
| B1 | `module.py:42` | SQL injection risk | Fixed - parameterized query |
| B2 | `test_module.py` | Missing edge case test | Fixed - added test |

**Warnings:**

| # | File | Warning | Action |
|---|------|---------|--------|
| W1 | `module.py:15` | Consider adding timeout | Added 30s timeout |
| W2 | `config.py` | Magic number | Deferred to #XX |

**Suggestions:**

| # | Suggestion | Action |
|---|------------|--------|
| S1 | Add docstring | Added |
| S2 | Consider caching | Deferred |

</details>

Co-Authored-By: @atx-ci <269048218+atx-ci@users.noreply.github.com>
```

See PRs #19, #21, and #205 for real examples of this format.
</pr-format>

<enforcement>
### Enforcement Rules

1. **No merge without review**: PRs lacking ATX review section will be rejected
2. **No unresolved blockers**: All `B#` issues must be `Fixed` or `Out-of-scope` with justification
3. **Rating threshold**: Final review must be > 3/5
4. **Attribution required**: `Co-Authored-By: @atx-ci` must appear in both commit and PR
5. **Iteration tracking**: Each review round must be documented with its rating
</enforcement>
