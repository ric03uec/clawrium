---
name: itx:bug-new
description: Create a GitHub bug report from current context
argument-hint: "[optional: brief description]"
---
name: itx:bug-new

# Bug Report Creation

Create a GitHub issue for a bug based on the current conversation context.

## Instructions

1. **Analyze Context**: Review the current conversation for:
   - Error messages and stack traces
   - Unexpected behavior descriptions
   - Steps that led to the issue
   - Environment details (Python version, OS, etc.)

2. **Ask for Customer Outcome**: Use `AskUserQuestion` to ask:
   > "What should the user be able to do when this bug is fixed?"

   Example outcomes:
   - "User can install claws without version mismatch errors"
   - "User can add hosts with special characters in names"
   - "User can run status command without timeout"

3. **Form Issue Title**: Use the customer outcome as the issue title.
   - Format: `<outcome>` (what the user can do after fix)
   - Example: "User can install claws without version mismatch errors"
   - The user can change this later if needed

4. **Gather Details**:
   - If the user provided a description argument, use it for context
   - Identify steps to reproduce if available
   - Note environment details

5. **Create Issue**: Use `gh issue create` with:
   ```bash
   gh issue create \
     --title "<customer outcome from step 3>" \
     --label "bug" \
     --label "needs-triage" \
     --body "<structured bug report>"
   ```

6. **Bug Report Body Format**:
   ```markdown
   ## Customer Outcome
   <The outcome statement - what user can do when fixed>

   ## Description
   <What is currently happening / the bug>

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
   **Skill**: /itx:bug-new
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt/context that led to this bug>
   ```

   </details>
   ```

7. **Return**: The issue URL and number

## Notes

- Always ask for customer outcome before creating the issue
- The outcome becomes the title - focus on what the user gains
- Always add `needs-triage` label for new bugs
- Include as much context as available from the conversation
- If steps to reproduce are unclear, note that in the issue
