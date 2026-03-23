---
description: Generate execution plan from specification
---

You are creating an execution plan for issue $ARGUMENTS.

## Context
@.spec/CONTRIBUTING.md
@AGENTS.md

## Required Input
@.spec/$ARGUMENTS/spec.md

## Template
@.spec/templates/plan.md

## Your Task

1. Read the spec.md thoroughly
2. Create `.spec/$ARGUMENTS/plan.md` with detailed, executable tasks
3. Each task must be completable by a junior dev or cheaper AI model

## Plan Quality Requirements

Each task MUST have:
- **Files**: Exact files to create/modify
- **Read First**: Files to read for context before starting
- **Action**: Step-by-step instructions (numbered)
- **Verification**: Exact commands to run
- **Acceptance**: Checkable criteria

## Task Granularity

- Each task should be 15-30 minutes of work
- Each task should be independently verifiable
- Tasks should follow TDD: tests first, then implementation

## Example Task Format

```markdown
### Task 1: Create tests for new feature

**Files**: `tests/test_feature.py`

**Read First**:
- `tests/conftest.py` - understand fixtures
- `src/clawrium/core/existing.py` - understand patterns

**Action**:
1. Create test file with test class
2. Write test for happy path
3. Write test for error case
4. Run tests (should fail - RED)

**Verification**:
```bash
uv run pytest tests/test_feature.py -v
# Expected: Tests fail (no implementation yet)
```

**Acceptance**:
- [ ] Test file exists
- [ ] At least 2 test cases
- [ ] Tests fail for right reason (import error, not syntax)
```

## Codebase Analysis

Before creating the plan, analyze:
- Existing patterns in `src/clawrium/`
- Test patterns in `tests/`
- Make commands in `Makefile`

## Output

After creating plan.md:
```
Plan ready: .spec/$ARGUMENTS/plan.md

Tasks: N tasks identified
Estimated time: X hours

Next steps:
1. Review the plan
2. Execute: /clawrium:execute $ARGUMENTS
```

## Prompt Log

Add to plan.md Prompt Log:
- model: (current model)
- date: (today)
- type: plan-creation
- prompt: (summarize what was requested)
