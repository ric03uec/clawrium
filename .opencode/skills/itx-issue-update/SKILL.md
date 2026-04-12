---
name: itx:issue-update
description: Add a comment to an existing issue
argument-hint: "<issue-number> <comment text>"
---
name: itx:issue-update

# Issue Update

Add a comment to an existing GitHub issue.

## Instructions

1. **Parse Arguments**: Extract issue number and comment text from arguments
   - First argument: issue number (required)
   - Remaining text: comment content (required)

2. **Validate Issue**: Verify the issue exists
   ```bash
   gh issue view <number> --json number,title,state
   ```

3. **Add Comment**: Post the comment with prompt log
   ```bash
   gh issue comment <number> --body "<comment with prompt log>"
   ```

4. **Comment Format**:
   ```markdown
   <comment text>

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: issue-update
   **Skill**: /itx:issue-update
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt that triggered this update>
   ```

   </details>
   ```

5. **Return**: Confirmation with issue URL

## Examples

```
/itx:issue-update 28 Updated the plan to include prompt logging requirement
```

## Notes

- Works for any issue type (bug, feature, etc.)
- Warn if the issue is closed
