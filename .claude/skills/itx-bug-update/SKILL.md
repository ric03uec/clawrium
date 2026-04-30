---
name: itx:bug-update
description: Add a comment to an existing bug issue
argument-hint: "<issue-number> <comment text>"
---
name: itx:bug-update

# Bug Update

Add a comment to an existing GitHub bug issue.

## Instructions

1. **Parse Arguments**: Extract issue number and comment text from arguments
   - First argument: issue number (required)
   - Remaining text: comment content (required)

2. **Validate Issue**: Verify the issue exists and has `bug` label
   ```bash
   gh issue view <number> --json number,title,labels
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

   **Stage**: bug-update
   **Skill**: /itx:bug-update
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
/itx:bug-update 42 Added debug logging, the error occurs in registry.py line 156
```

## Notes

- Warn if the issue doesn't have a `bug` label (may be wrong issue type)
- Include relevant technical details from the conversation

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/00_PLAN.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.
