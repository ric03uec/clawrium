---
name: itx:issue-new
description: Create a feature or improvement issue
argument-hint: "[optional: brief description]"
---
name: itx:issue-new

# Issue Creation

Create a GitHub issue for a feature request or improvement.

## Instructions

1. **Analyze Context**: Review the current conversation for:
   - Feature requests
   - Enhancement ideas
   - Improvement suggestions
   - User pain points

2. **Ask for Customer Outcome**: Use `AskUserQuestion` to ask:
   > "What should the user be able to do when this is implemented?"

   Example outcomes:
   - "User can deploy multiple components in a single command"
   - "User can see resource usage across all services"
   - "User can backup configurations automatically"

3. **Form Issue Title**: Use the customer outcome as the issue title.
   - Format: `<outcome>` (what the user can do after implementation)
   - Example: "User can deploy multiple components in a single command"
   - The user can change this later if needed

4. **Gather Details**:
   - If the user provided a description argument, use it for context
   - Identify the problem being solved
   - Note any constraints or preferences

5. **Create Issue**: Use `gh issue create` with:
   ```bash
   gh issue create \
     --title "<customer outcome from step 3>" \
     --body "<structured issue>"
   ```

6. **Issue Body Format**:
   ```markdown
   ## Customer Outcome
   <The outcome statement - what user can do when implemented>

   ## Summary
   <What is being proposed>

   ## Motivation
   <Why this is needed / what problem it solves>

   ## Proposed Solution
   <High-level approach if known>

   ## Acceptance Criteria
   - [ ] <criterion 1>
   - [ ] <criterion 2>

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: issue-creation
   **Skill**: /itx:issue-new
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt/context that led to this issue>
   ```

   </details>
   ```

7. **Return**: The issue URL and number

## Notes

- Always ask for customer outcome before creating the issue
- The outcome becomes the title - focus on what the user gains
- Do not add labels by default (let triage decide)
- Focus on the problem/need, not just the solution
- Include acceptance criteria when possible

## Prompt Logging

**REQUIRED**: After creating the issue, append prompt log to `.itx/<N>/00_PLAN.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

```bash
mkdir -p .itx/<issue-number>
# Append prompt log to .itx/<issue-number>/00_PLAN.md
```
