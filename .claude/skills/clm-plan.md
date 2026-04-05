---
description: Create implementation plan for a GitHub issue
argument-hint: "<issue-number>"
---

# Implementation Planning

Create a detailed implementation plan for a GitHub issue.

## Instructions

1. **Fetch Issue**: Get full issue details
   ```bash
   gh issue view <number> --json number,title,body,labels,comments
   ```

2. **Explore Codebase**: Understand the scope
   - Identify affected files and modules
   - Review related code patterns
   - Check for existing tests
   - Note any dependencies

3. **Create Plan**: Structure the implementation approach
   - Break down into logical steps
   - Identify files to modify/create
   - Define test strategy
   - Note potential risks

4. **Decide on Subtasks**:
   - **Simple issue** (< 3 files, single concern): No subtasks needed
   - **Complex issue** (multiple files, multiple concerns): Create subtasks

5. **If Subtasks Needed**: Create subtask issues
   ```bash
   gh issue create \
     --title "[Parent #<parent>] <subtask description>" \
     --label "ready" \
     --body "<subtask details>"
   ```

6. **Post Plan**: Add plan as comment on parent issue
   ```markdown
   ## Implementation Plan

   ### Overview
   <brief description of approach>

   ### Files to Modify
   - `path/to/file.py` - <what changes>

   ### Steps
   1. <step>
   2. <step>

   ### Test Strategy
   - <how to verify>

   ### Subtasks
   - #<subtask1> - <description>
   - #<subtask2> - <description>
   (or "None - single task execution")

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: planning
   **Skill**: /clm:plan
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt that triggered planning>
   ```

   </details>
   ```

7. **Update Labels**:
   ```bash
   gh issue edit <number> --remove-label "planning" --add-label "ready"
   ```

8. **Return**: Plan summary and any subtask issue numbers

## Subtask Guidelines

- Each subtask should be independently executable
- Subtasks should have clear boundaries
- Order subtasks by dependency (execute first → last)
- Subtask title format: `[Parent #N] <action verb> <target>`

## Notes

- Use expensive models (Opus/Sonnet) for planning - this is where thinking matters
- Execution can use cheaper models (Haiku)
- Plans should be detailed enough that any developer can execute
