---
description: Create or update specification for an issue
model: anthropic/claude-sonnet-4-20250514
---

You are creating or updating the specification for issue $ARGUMENTS.

## Context
@.spec/CONTRIBUTING.md
@AGENTS.md

## Template
@.spec/templates/spec.md

## Existing Content (read these if they exist)

Check for existing files in `.spec/$ARGUMENTS/`:
- idea.md (raw thoughts to formalize)
- spec.md (existing spec to update)

## Your Task

1. If idea.md exists, use it as input
2. Create or update `.spec/$ARGUMENTS/spec.md`
3. Fill in ALL sections of the template
4. Make acceptance criteria specific and testable
5. Identify files that will need modification

## Quality Checklist

Before finalizing, ensure:
- [ ] Summary is one clear paragraph
- [ ] Motivation explains WHO has this problem and WHY now
- [ ] Design includes concrete API/interface examples
- [ ] Acceptance criteria are testable (can be verified with commands)
- [ ] Alternatives considered with clear rationale
- [ ] Dependencies identified

## Codebase Context

Read relevant files to understand current patterns:
- `src/clawrium/` - existing code structure
- `tests/` - existing test patterns
- `.planning/PROJECT.md` - project constraints

## Output

After creating/updating spec.md:
```
Specification ready: .spec/$ARGUMENTS/spec.md

Status: draft

Next steps:
1. Review the spec
2. When approved, create plan: /clawrium:plan $ARGUMENTS
```

## Prompt Log

Add to spec.md Prompt Log:
- model: (current model)  
- date: (today)
- type: spec-creation | spec-update
- prompt: (summarize the user's request)
