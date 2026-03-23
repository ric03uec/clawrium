---
description: Document learnings from completed issue
---

You are documenting learnings for issue $ARGUMENTS.

## Context
@.spec/CONTRIBUTING.md

## Required Input
@.spec/$ARGUMENTS/spec.md
@.spec/$ARGUMENTS/plan.md
@.spec/$ARGUMENTS/exec.md

## Template
@.spec/templates/learnings.md

## Your Task

1. Read all issue files (spec, plan, exec)
2. Create `.spec/$ARGUMENTS/learnings.md`
3. Extract insights for future work

## Analysis Questions

Answer these in the learnings doc:

### What Went Well
- What parts of the spec were clear and helpful?
- What plan tasks executed smoothly?
- What patterns worked well?

### What Could Be Improved
- Where did we deviate from the plan? Why?
- What was underspecified?
- What took longer than expected?

### Key Decisions
- What decisions were made during execution?
- What alternatives were considered?
- What would we do differently?

### Patterns Discovered
- Any reusable patterns emerged?
- Any anti-patterns to avoid?

### Follow-up Items
- What new issues should be created?
- What documentation needs updating?

## Output

After creating learnings.md:
```
Learnings documented: .spec/$ARGUMENTS/learnings.md

Summary:
- Went well: X items
- Improve: Y items  
- Follow-ups: Z items

Consider creating follow-up issues for:
- Item 1
- Item 2
```

## Prompt Log

Add to learnings.md Prompt Log:
- model: (current model)
- date: (today)
- type: learnings
- prompt: (document learnings request)
