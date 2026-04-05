---
description: Create a GitHub bug report from current context
argument-hint: "[optional: brief description]"
---

# Bug Report Creation

Create a GitHub issue for a bug based on the current conversation context.

## Instructions

1. **Analyze Context**: Review the current conversation for:
   - Error messages and stack traces
   - Unexpected behavior descriptions
   - Steps that led to the issue
   - Environment details (Python version, OS, etc.)

2. **Gather Information**:
   - If the user provided a description argument, use it as the basis
   - If not, summarize the bug from context
   - Identify steps to reproduce if available

3. **Create Issue**: Use `gh issue create` with:
   ```bash
   gh issue create \
     --title "<clear, concise bug summary>" \
     --label "bug" \
     --label "needs-triage" \
     --body "<structured bug report>"
   ```

4. **Bug Report Body Format**:
   ```markdown
   ## Description
   <What is happening>

   ## Steps to Reproduce
   1. <step>
   2. <step>

   ## Expected Behavior
   <What should happen>

   ## Actual Behavior
   <What actually happens>

   ## Environment
   - Clawrium version: <version>
   - Python version: <version>
   - OS: <os>

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: bug-creation
   **Skill**: /clm:bug-new
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt/context that led to this bug>
   ```

   </details>
   ```

5. **Return**: The issue URL and number

## Notes

- Always add `needs-triage` label for new bugs
- Include as much context as available from the conversation
- If steps to reproduce are unclear, note that in the issue
