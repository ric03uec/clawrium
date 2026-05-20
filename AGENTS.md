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

# Install a skill onto the agent (catalog: skills/)
clm skill list
clm skill show clawrium/tdd       # Inspect a skill before installing
clm agent skill install <agent-name> clawrium/tdd

# Check fleet status
clm ps
```

## Key Concepts

- **Host**: A machine in your network that runs one or more agents
- **Agent**: An AI assistant instance (zeroclaw, nemoclaw, or openclaw)
- **Agent Type**: The specific AI assistant implementation (e.g., zeroclaw, nemoclaw, openclaw)
- **Agent Name**: The unique identifier for an installed agent instance
- **Agent Registry**: Platform-defined agent types with versions, dependencies, and templates
- **Skill Registry**: A namespace under `skills/` from which skills can be installed onto an agent (`clawrium`, `openclaw`, `hermes`, `zeroclaw`). Skills are referenced as `<skill-registry>/<name>` (e.g. `clawrium/tdd`). Distinct from the Agent Registry.

## Resources

- Repository: https://github.com/ric03uec/clawrium
- Project Board: https://github.com/users/ric03uec/projects/1
- Version: 26.4.7

## Gateway Token Lifecycle (zeroclaw)

The zeroclaw gateway authenticates `clm chat` sessions with a bearer token
the daemon mints via a `/pair/code` → `/pair` loopback handshake. The
daemon does not persist that bearer across systemd restarts, so the only
way for `clm` to guarantee `hosts.json.gateway.auth` equals the bearer the
daemon will enforce on the next request is to **always re-pair** on every
lifecycle op that touches the daemon.

Rules (issue #437):

- `clm agent configure`, `clm agent sync`, and `clm agent restart` all
  mint a fresh bearer and overwrite `hosts.json.gateway.auth` atomically.
- There is no idempotent-skip path. Do not add a `--no-rotate` flag —
  branching here is the bug the original ATX Round 1 B3 code introduced.
- Remote `clm chat` sessions (running on a different machine than the one
  that ran the lifecycle op) will get a clean 401 on their next request.
  They must reconnect — that's the documented trade-off.
- Local `clm chat` reconnects transparently: on 401 it reloads
  `hosts.json` once, compares the bearer in memory vs disk, and rebuilds
  the backend with the fresh token if they differ.
- A single `gateway_token_rotated` event is emitted from `lifecycle.py`
  whenever the bearer is overwritten. The CLI renders it as a yellow
  notice during `configure`/`sync`/`restart`.

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

### Workflow Commands

| Command | Purpose |
|---------|---------|
| `/itx:bug-new` | Create bug issue (asks for customer outcome) |
| `/itx:issue-new` | Create feature issue (asks for customer outcome) |
| `/itx:triage` | Review unlabeled issues |
| `/itx:plan-create <n>` | Create high-level implementation plan |
| `/itx:plan-scaffold <n>` | Create phased execution with entry/exit criteria |
| `/itx:execute <n>` | Execute issue (parent or subtask) |
| `/itx:verify` | Run tests and lint |
| `/itx:review-pr [n]` | Review PR (MCP or manual) |

### Planning Artifacts Directory (`.itx/`)

The `.itx/` directory stores implementation plans and execution documentation for each issue. These are **NOT ephemeral files** - they document how an issue was planned and executed.

```
.itx/
└── <issue-number>/
    ├── 00_PLAN.md           # High-level implementation plan (from /itx:plan-create)
    └── 01_SCAFFOLD.md       # Phased execution plan (from /itx:plan-scaffold)
```

**IMPORTANT**: Always commit the `.itx/` directory with your changes. These files serve as:
- Historical record of implementation decisions
- Context for future maintenance
- Documentation of the execution approach

When completing work on an issue, ensure `.itx/<issue-number>/` is included in your commit.

### Task-Based Execution

The `/itx:execute` skill uses a structured task checklist approach to prevent getting lost during execution:

**Planning Phase (Mandatory)**:
1. Read implementation plan from issue
2. Create implementation tasks using `TaskCreate()` for each phase/step
3. Create verification tasks (tests, lint, review if MCP enabled)
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

Review requirements depend on whether MCP-based automated review is configured in `.claude/itx-config.json`.

### Check Review Mode

```bash
ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
if [ -f "$ITX_CONFIG" ]; then
  REVIEW_ENABLED=$(jq -r '.mcp.review_enabled // false' "$ITX_CONFIG")
else
  REVIEW_ENABLED="false"
fi
```

---

## If MCP Review Enabled (ATX)

<atx-review-requirements>
When `mcp.review_enabled` is `true`, all code changes MUST include automated review before merging.

### Iteration Requirements
1. Request review using the configured MCP tool (default: `mcp__atx__request_review`)
2. Fix ALL blocking issues (B1, B2, etc.)
3. Iterate until: Rating > 3/5 AND no blocking issues remain
4. Document each review iteration in commit message and PR body

### When to Request Review
- Before creating a commit with code changes
- After fixing issues from previous review
- Before marking PR as ready for merge
</atx-review-requirements>

<commit-format-atx>
### Commit Message Format (ATX)

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
</commit-format-atx>

<pr-format-atx>
### PR Body Format (ATX)

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
</pr-format-atx>

<enforcement-atx>
### Enforcement Rules (ATX)

1. **No merge without review**: PRs lacking ATX review section will be rejected
2. **No unresolved blockers**: All `B#` issues must be `Fixed` or `Out-of-scope` with justification
3. **Rating threshold**: Final review must be > 3/5
4. **Attribution required**: `Co-Authored-By: @atx-ci` must appear in both commit and PR
5. **Iteration tracking**: Each review round must be documented with its rating
</enforcement-atx>

---

## If MCP Review Not Enabled (Manual Review)

<manual-review-requirements>
When `mcp.review_enabled` is `false` or not configured, use manual review with self-attestation.

### Requirements
1. Run all tests and ensure they pass
2. Run linter and fix any issues
3. Self-review changes for quality and security
4. Document testing approach in PR
</manual-review-requirements>

<commit-format-manual>
### Commit Message Format (Manual)

```
feat(component): short description

Detailed explanation of changes.

Closes #XX

Co-Authored-By: Claude <noreply@anthropic.com>
```
</commit-format-manual>

<pr-format-manual>
### PR Body Format (Manual)

```markdown
## Summary
<1-3 bullet points describing what this PR does>

## Testing

### Test Results
- [ ] All existing tests pass (`make test`)
- [ ] Linter passes (`make lint`)
- [ ] New tests added for new functionality

### Test Coverage
- Files changed: <list files>
- New tests: <list new test files or "N/A">
- Coverage impact: <increased/maintained/decreased>

### Manual Testing
<Describe any manual testing performed>

### Security Checklist
- [ ] No hardcoded secrets or credentials
- [ ] Input validation for user-provided data
- [ ] No SQL injection, XSS, or command injection risks
- [ ] Dependencies are from trusted sources

## Reviewer Notes
<Any additional context for reviewers>

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
</pr-format-manual>

<enforcement-manual>
### Enforcement Rules (Manual)

1. **Tests must pass**: All tests must pass before merge
2. **Linter must pass**: No lint errors allowed
3. **Testing documented**: PR must include Testing section
4. **Security reviewed**: Security checklist must be completed
</enforcement-manual>

## Prompt Logging Standard

Skills that produce artifacts as part of an issue (plans, scaffolds, demos, etc.) append a prompt log to `.itx/<issue-number>/<NN>_<STAGE>.md`. The log captures the prompt, model, and skill name so the path from human input → artifact is reproducible.

**Format** (markdown, append-only):

```markdown
## <Stage Name>

**Stage**: <stage-slug>           # e.g. demo, plan, scaffold
**Skill**: /<skill-name>          # e.g. /create-vhs
**Timestamp**: <ISO-8601 UTC>     # e.g. 2026-05-19T15:30:00Z
**Model**: <model-id>             # e.g. claude-opus-4-7

```prompt
<verbatim user prompt that triggered the skill>
```

**Output**: <one-line description of what was produced>
```

**File numbering**: `00_PLAN.md`, `01_SCAFFOLD.md`, `02_EXECUTE.md`, `03_DEMO.md`, …  Match the order in which stages run for the issue.

**One log per stage**: if a stage runs multiple times, append additional H2 sections to the same file rather than creating new files.
