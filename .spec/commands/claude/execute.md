---
description: Execute plan tasks for an issue
---

You are executing the plan for issue $ARGUMENTS.

## Context
@.spec/CONTRIBUTING.md

## Required Input
@.spec/$ARGUMENTS/plan.md
@.spec/$ARGUMENTS/spec.md

## Execution Log
@.spec/$ARGUMENTS/exec.md (create if doesn't exist)

## Template
@.spec/templates/exec.md

## Your Task

1. Read the plan.md completely
2. Create/update exec.md to track progress
3. Execute tasks ONE AT A TIME
4. Run verification after each task
5. Log results in exec.md

## Execution Rules

1. **Follow the plan exactly** - Do not improvise or add features
2. **One task at a time** - Complete and verify before moving on
3. **Stop on failure** - If verification fails, stop and report
4. **Log everything** - Update exec.md after each task

## Task Execution Flow

For each task:
1. Mark task as "in-progress" in exec.md
2. Read the files specified in "Read First"
3. Execute the actions step by step
4. Run the verification command
5. Check acceptance criteria
6. Mark task as "done" or "blocked"
7. Log what was done and any deviations

## Deviation Policy

If you MUST deviate from the plan:
1. Document WHY in exec.md
2. Keep the deviation minimal
3. Still meet the acceptance criteria

## Output Format

After each task:
```
Task N: [DONE|BLOCKED]

Verification:
$ {command}
{output}

Acceptance:
- [x] Criterion 1
- [x] Criterion 2
```

After all tasks:
```
Execution complete: .spec/$ARGUMENTS/exec.md

Results:
- Tasks completed: X/Y
- All verifications: PASS|FAIL
- Ready for review: YES|NO

Next steps:
1. Run full test suite: make test
2. Document learnings: /clawrium:learn $ARGUMENTS
```

## Prompt Log

Add to exec.md Prompt Log for each task:
- model: (current model)
- date: (today)
- type: execution
- task: (task number)
- prompt: (what was requested)
