---
description: Create high-level implementation plan with product output and technical details
---

Create a detailed implementation plan for GitHub issue $ARGUMENTS.

Steps:
1. Fetch the issue: `gh issue view $ARGUMENTS --json number,title,body,labels,comments`
2. Explore the codebase to understand scope
3. Create a high-level plan with:
   - Product output (what the user gets)
   - Technical details (files, modules affected)
   - Implementation steps
   - Test strategy
4. Post the plan as a comment on the issue
5. Update labels: `planning` → `planned`

If the issue is complex (multiple files/concerns), create subtasks.
