# Clawrium

**An aquarium for your claws.**

Clawrium is a CLI tool (`clm`) for managing AI Claw fleets (ZeroClaw, NemoClaw, OpenClaw, or any other claw) on local networks. It allows users to deploy and manage multiple claw instances across hosts without dealing with each host separately. Using Clawrium, you can
1. manage any number of assistants on your local network
2. manage the agent lifecycle (upgrades, secrets management, backups etc)
3. track token usage across different agents and build guardrails
4. experiment with different models across your agent fleet

## Resources

- Repository: https://github.com/ric03uec/clawrium
- Project Board: https://github.com/users/ric03uec/projects/1

## Version

26.3.1

## Tech Stack

- **CLI**: Python + Typer
- **Execution**: ansible-runner
- **Packaging**: uv/uvx

## Key Concepts

- **Host**: A machine in your network that runs one or more claws
- **Claw**: An AI assistant instance (zeroclaw, nemoclaw, or openclaw)
- **Registry**: Platform-defined claw types with versions, dependencies, and templates

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

GitHub Issues are the single source of truth. Use `/clm:*` skills to manage the workflow.

### Issue States

| State | Label | Description |
|-------|-------|-------------|
| INBOX | (none) | New issues without workflow labels |
| TRIAGE | `needs-triage` | Needs more information |
| PLANNING | `planning` | Being planned |
| READY | `ready` | Plan complete, ready to execute |
| IN PROGRESS | `in-progress` | Currently being worked on |
| REVIEW | `in-review` | PR open for review |
| DONE | (closed) | Complete |

### Skills Reference

| Skill | Purpose |
|-------|---------|
| `/clm:bug-new` | Create bug issue from context |
| `/clm:bug-update <n> <text>` | Add comment to bug |
| `/clm:issue-new` | Create feature/improvement issue |
| `/clm:issue-update <n> <text>` | Add comment to issue |
| `/clm:triage` | Review unlabeled issues |
| `/clm:plan <n>` | Create implementation plan |
| `/clm:execute <n>` | Execute issue (parent or subtask) |
| `/clm:verify` | Run tests and lint |
| `/clm:review-pr [n]` | ATX review of PR |
| `/clm:pr-status` | Check open PRs |
| `/clm:note [text]` | Quick note to NOTES.md |

### Workflow

```
New Issue → /clm:triage → /clm:plan → /clm:execute → /clm:verify → /clm:review-pr → Merge
```

### Parent/Subtask Pattern

Complex issues can be broken into subtasks by `/clm:plan`:
- Subtask title format: `[Parent #N] <description>`
- `/clm:execute` on parent spawns subagents for each subtask
- Parent closes when all subtasks complete

## Review

When @atx-ci provides a review, the caller MUST fix all issues and iterate until:
1. Rating is >3/5
2. No blocking issues remain

All @atx-ci generated reviews and feedback MUST be updated in the commit. Use the format
```
ATX Review Summary
Review <number>: Rating <1/5>
Blocking issues:
<table with blocking issues, reasoning, and recommendations>

Warnings:
<table with warnings and recommendations>

Suggestions:
<good to have improvements>

Co-Authored-By: @atx-ci <269048218+atx-ci@users.noreply.github.com>
```
