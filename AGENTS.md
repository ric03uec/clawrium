# Clawrium - An aquarium for *claws

Clawrium is a CLI tool (`clm`) for managing AI agent fleets (ZeroClaw, NemoClaw, OpenClaw, or any other agent) on local networks. It allows users to deploy and manage multiple agent instances across hosts without dealing with each host separately. Using Clawrium, you can
1. manage any number of assistants on your local network
2. manage the agent lifecycle (upgrades, secrets management, backups etc)
3. track token usage across different agents and build guardrails
4. experiment with different models across your agent fleet

## Resources

- Repository: https://github.com/ric03uec/clawrium
- Project Board: https://github.com/users/ric03uec/projects/1

## Version

26.04.01

## Tech Stack

- **CLI**: Python + Typer
- **Execution**: ansible-runner
- **Packaging**: uv/uvx

## Key Concepts

- **Host**: A machine in your network that runs one or more agents
- **Agent**: An AI assistant instance (zeroclaw, nemoclaw, or openclaw)
- **Agent Type**: The specific AI assistant implementation (e.g., zeroclaw, nemoclaw, openclaw)
- **Agent Name**: The unique identifier for an installed agent instance
- **Registry**: Platform-defined agent types with versions, dependencies, and templates

## User Data

All user configuration stored in `~/.config/clawrium/`

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

Trigger with: `/clm:execute 35 in a subtree` or `/clm:execute 35 --worktree`

### Quick Reference

```
New Issue → /clm:triage → /clm:plan-build → /clm:plan-scaffold → /clm:execute → /clm:verify → /clm:review-pr → Merge
```

### Skills

| Skill | Purpose |
|-------|---------|
| `/clm:bug-new` | Create bug issue (asks for customer outcome) |
| `/clm:issue-new` | Create feature issue (asks for customer outcome) |
| `/clm:triage` | Review unlabeled issues |
| `/clm:plan-build <n>` | Create high-level implementation plan |
| `/clm:plan-scaffold <n>` | Create phased execution with entry/exit criteria |
| `/clm:execute <n>` | Execute issue (parent or subtask) |
| `/clm:verify` | Run tests and lint |
| `/clm:review-pr [n]` | ATX review of PR |

### Task-Based Execution

The `/clm:execute` skill uses a structured task checklist approach to prevent getting lost during execution:

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
Review 1: Rating 2/5
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

| Review | Rating | Blocking Issues | Status |
|--------|--------|-----------------|--------|
| 1 | 2/5 | B1, B2, B3 | All fixed |
| 2 | 4/5 | None | Ready |

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

See PRs #19 and #21 for real examples of this format.
</pr-format>

<enforcement>
### Enforcement Rules

1. **No merge without review**: PRs lacking ATX review section will be rejected
2. **No unresolved blockers**: All `B#` issues must be `Fixed` or `Out-of-scope` with justification
3. **Rating threshold**: Final review must be > 3/5
4. **Attribution required**: `Co-Authored-By: @atx-ci` must appear in both commit and PR
5. **Iteration tracking**: Each review round must be documented with its rating
</enforcement>
