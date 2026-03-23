---
description: Capture raw idea/thoughts and create new issue
---

You are capturing raw thoughts and ideas for Clawrium.

## Context
@.spec/CONTRIBUTING.md

## Template
@.spec/templates/idea.md

## Your Task

1. Generate a unique issue ID: `YYMMDD-XXX` (date + 3 random lowercase chars)
2. Create directory: `.spec/<issue>/`
3. Create `.spec/<issue>/idea.md` with the user's raw thoughts
4. Ask clarifying questions to fill in Context and Initial Scope

## Steps

1. Listen to the user's idea (from $ARGUMENTS or ask)
2. Generate issue ID (e.g., `260323-abc`)
3. Create the issue folder and idea.md
4. Capture thoughts exactly as provided

## Output

After creating idea.md:
```
Captured idea: .spec/<issue>/idea.md

Issue ID: <issue>

Next steps:
1. Refine into specification: /clawrium:write-spec <issue>
```

## Prompt Log

Add to the Prompt Log section:
- model: (current model)
- date: (today)
- type: idea-capture
- prompt: (user's raw input)

$ARGUMENTS
