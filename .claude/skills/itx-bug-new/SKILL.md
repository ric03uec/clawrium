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
   - Environment details (version, OS, etc.)

2. **Ask for Customer Outcome**: Use `AskUserQuestion` to ask:
   > "What should the user be able to do when this bug is fixed?"

   Example outcomes:
   - "User can install dependencies without version mismatch errors"
   - "User can add resources with special characters in names"
   - "User can run status command without timeout"

3. **Form Issue Title**: Use the customer outcome as the issue title.
   - Format: `<outcome>` (what the user can do after fix)
   - Example: "User can install dependencies without version mismatch errors"
   - The user can change this later if needed

4. **Gather Details**:
   - If the user provided a description argument, use it for context
   - Identify steps to reproduce if available
   - Note environment details

5. **Load Project Name** (for environment section):
   ```bash
   ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
   if [ -f "$ITX_CONFIG" ]; then
     PROJECT_NAME=$(jq -r '.project.name // ""' "$ITX_CONFIG")
     VERSION_LABEL=$(jq -r '.project.version_label // "Version"' "$ITX_CONFIG")
   fi

   # Fallback: use repository name if no config
   if [ -z "$PROJECT_NAME" ]; then
     REMOTE_URL=$(git config --get remote.origin.url)
     PROJECT_NAME=$(echo "$REMOTE_URL" | sed -E 's/.*[:/]([^/]+\/[^/]+)(\.git)?$/\1/' | cut -d'/' -f2)
   fi
   ```

6. **Create Issue**: Use `gh issue create` with:
   ```bash
   gh issue create \
     --title "<customer outcome from step 3>" \
     --label "bug" \
     --label "needs-triage" \
     --body "<structured bug report>"
   ```

7. **Bug Report Body Format**:
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
   - <project name> version: <version>
   - Platform: <os/platform>
   - Other relevant details: <details>

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

8. **Return**: The issue URL and number

## Notes

- Always ask for customer outcome before creating the issue
- The outcome becomes the title - focus on what the user gains
- Always add `needs-triage` label for new bugs
- Include as much context as available from the conversation
- If steps to reproduce are unclear, note that in the issue
- Project name dynamically detected or loaded from config

## Prompt Logging

**REQUIRED**: After creating the issue, append prompt log to `.itx/<N>/00_PLAN.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

```bash
mkdir -p .itx/<issue-number>
# Append prompt log to .itx/<issue-number>/00_PLAN.md
```
