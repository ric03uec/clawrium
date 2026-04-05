---
description: Create a feature or improvement issue
argument-hint: "[optional: brief description]"
---

# Issue Creation

Create a GitHub issue for a feature request or improvement.

## Instructions

1. **Analyze Context**: Review the current conversation for:
   - Feature requests
   - Enhancement ideas
   - Improvement suggestions
   - User pain points

2. **Gather Information**:
   - If the user provided a description argument, use it as the basis
   - If not, summarize the feature/improvement from context
   - Identify the problem being solved

3. **Create Issue**: Use `gh issue create` with:
   ```bash
   gh issue create \
     --title "<clear, actionable title>" \
     --body "<structured issue>"
   ```

4. **Issue Body Format**:
   ```markdown
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
   **Skill**: /clm:issue-new
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt/context that led to this issue>
   ```

   </details>
   ```

5. **Return**: The issue URL and number

## Notes

- Do not add labels by default (let triage decide)
- Focus on the problem/need, not just the solution
- Include acceptance criteria when possible
