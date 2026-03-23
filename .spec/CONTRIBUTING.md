# Contributing to Clawrium

## Development Workflow: Spec-Plan-Execute

Clawrium uses a structured workflow designed for OSS collaboration. This workflow separates **planning** (requires more context/expensive models) from **execution** (can use cheaper models).

### Workflow Overview

```
Idea → Spec → Plan → Execute → Learnings
  │      │      │       │          │
  │      │      │       │          └── What we learned
  │      │      │       └── Implementation (cheap model OK)
  │      │      └── Detailed tasks (expensive model)
  │      └── What & why (expensive model)
  └── Raw thoughts capture (creates new issue)
```

### Issue Structure

```
.spec/
├── status.md            # Issue tracking (in-progress/pending/completed)
├── CONTRIBUTING.md      # This file
├── templates/           # Templates (do not edit)
└── <issue>/             # One folder per issue (e.g., 260323-abc/)
    ├── idea.md          # Initial capture
    ├── spec.md          # Specification
    ├── plan.md          # Execution plan
    ├── exec.md          # Execution log
    └── learnings.md     # Post-mortem
```

### Status Tracking

Check `.spec/status.md` before starting work:
- **In Progress**: Issues currently being worked on
- **Pending**: Issues ready to pick up
- **Completed**: Finished issues

Agents should check this file to decide what to work on next.

### Available Commands

| Command | Purpose | Recommended Model |
|---------|---------|-------------------|
| `/clawrium:file-bug` | Create new bug report | Any |
| `/clawrium:idea` | Capture raw thoughts (creates new issue) | Any |
| `/clawrium:write-spec <issue>` | Create/update specification | Opus/Sonnet |
| `/clawrium:write-plan <issue>` | Generate execution plan | Opus/Sonnet |
| `/clawrium:execute <issue>` | Execute plan tasks | Haiku/DeepSeek |
| `/clawrium:learn <issue>` | Document learnings | Any |

### Step-by-Step Guide

#### 1. Start with an Idea or Bug

```
> /clawrium:idea
# Describe your feature idea...

# Creates: .spec/260323-abc/idea.md
# Returns: Issue ID for next steps
```

Or for a bug:
```
> /clawrium:file-bug
```

#### 2. Write the Specification

```
> /clawrium:write-spec 260323-abc
```

This creates/updates `.spec/260323-abc/spec.md`. The spec defines:
- **What** we're building
- **Why** we're building it
- **Acceptance criteria** (testable)

**Best done with**: Claude Opus, Claude Sonnet

#### 3. Create the Plan

```
> /clawrium:write-plan 260323-abc
```

This creates `.spec/260323-abc/plan.md` with:
- Numbered tasks
- Files to modify per task
- Verification commands
- Clear acceptance criteria per task

**Best done with**: Claude Opus, Claude Sonnet

#### 4. Execute the Plan

```
> /clawrium:execute 260323-abc
```

This:
1. Reads the plan
2. Executes tasks sequentially
3. Logs progress in `.spec/260323-abc/exec.md`

**Can be done with**: Claude Haiku, DeepSeek, or any model that can follow instructions.

#### 5. Document Learnings

```
> /clawrium:learn 260323-abc
```

Creates `.spec/260323-abc/learnings.md` with:
- What went well
- What could improve
- Patterns discovered
- Follow-up items

### Prompt Logging

Every command logs prompts in a collapsed section at the bottom of each file:

```markdown
<details>
<summary>Prompt Log</summary>

```yaml
- model: claude-sonnet-4-20250514
  date: 2026-03-23
  type: spec-creation
  prompt: |
    Create a specification for...
```

</details>
```

This enables:
- **Reproducibility**: Recreate or refine with the same prompts
- **Learning**: New contributors understand context
- **Debugging**: Trace decisions back to prompts

### Model Recommendations

| Phase | Recommended | Budget Option |
|-------|-------------|---------------|
| Idea | Any | Any |
| Spec | Claude Opus/Sonnet | Claude Haiku |
| Plan | Claude Opus/Sonnet | Claude Sonnet |
| Execute | Claude Haiku | DeepSeek |
| Learn | Any | Any |

### Setting Up

```bash
make setup-dev

# This will:
# 1. Install dependencies
# 2. Ask which editor you use (opencode/claude)
# 3. Create local slash commands
# 4. Print next steps
```

### Tips

1. **Check status.md first**: See what's in progress before starting
2. **Specs are contracts**: Don't start planning until spec is approved
3. **Plans are instructions**: Write them so anyone can follow
4. **Execution is mechanical**: Follow the plan exactly; deviate only if blocked
5. **Learnings are gold**: Future you will thank present you
