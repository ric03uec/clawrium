---
description: File a new bug and create issue structure
---

You are helping create a new bug report for Clawrium.

## Your Task

1. Ask the user to describe the bug (if not provided in $ARGUMENTS)
2. Generate a unique issue number (use current date + random 3 chars, e.g., `260323-abc`)
3. Create the issue directory and spec.md

## Steps

1. Create directory: `.spec/{issue}/`
2. Create spec.md from template with bug-specific content

## Template Location
@.spec/templates/spec.md

## Output Format

After creating the files, output:
```
Created bug report: .spec/{issue}/spec.md

Next steps:
1. Review and refine the spec: /clawrium:write-spec {issue}
2. Create execution plan: /clawrium:plan {issue}
```

## Prompt Log

Capture this interaction in the spec.md file under the Prompt Log section with:
- model: (current model)
- date: (today)
- type: bug-filing
- prompt: (the user's bug description)

$ARGUMENTS
