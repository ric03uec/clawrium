---
name: itx:plan-create
description: Create high-level implementation plan with product output and technical details
argument-hint: "<issue-number>"
---
name: itx:plan-create

# Implementation Planning (Create Phase)

Create a high-level implementation plan for a GitHub issue with product output and technical details.

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

4. **Save Plan to File**:
   ```bash
   mkdir -p .itx/<number>
   # Write plan to .itx/<number>/00_PLAN.md
   ```

5. **Decide on Subtasks**:
   - **Simple issue** (< 3 files, single concern): No subtasks needed
   - **Complex issue** (multiple files, multiple concerns): Create subtasks

6. **If Subtasks Needed**: Detect repository info and create subtask issues with sub-issue links
    ```bash
    # Extract repository info
    REMOTE_URL=$(git config --get remote.origin.url)
    OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's/.*[:/]([^/]+\/[^/]+)(\.git)?$/\1/')
    OWNER=$(echo "$OWNER_REPO" | cut -d'/' -f1)
    REPO=$(echo "$OWNER_REPO" | cut -d'/' -f2)

    # Create subtask
    CHILD_URL=$(gh issue create \
      --title "[Parent #<parent>] <subtask description>" \
      --label "ready" \
      --body "<subtask details>")
    CHILD_NUM=$(basename $CHILD_URL)

    # Link as sub-issue using GraphQL with dynamic repo
    gh api graphql -f query='
      mutation($parentId: ID!, $childId: ID!) {
        addSubIssue(input: {issueId: $parentId, subIssueId: $childId}) {
          issue { number }
          subIssue { number }
        }
      }' \
      -f parentId=$(gh api graphql -f query='query($owner: String!, $repo: String!, $issue: Int!) { repository(owner: $owner, name: $repo) { issue(number: $issue) { id } } }' -f owner="$OWNER" -f repo="$REPO" -F issue=$PARENT_NUM | jq -r '.data.repository.issue.id') \
      -f childId=$(gh api graphql -f query='query($owner: String!, $repo: String!, $issue: Int!) { repository(owner: $owner, name: $repo) { issue(number: $issue) { id } } }' -f owner="$OWNER" -f repo="$REPO" -F issue=$CHILD_NUM | jq -r '.data.repository.issue.id')
    ```

7. **Post Plan**: Add plan as comment on parent issue
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
   **Skill**: /itx:plan-create
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt that triggered planning>
   ```

   </details>
   ```

8. **Update Labels**:
   ```bash
   gh issue edit <number> --remove-label "planning" --add-label "planned"
   ```

9. **Return**: Plan summary and any subtask issue numbers

## Subtask Guidelines

- Each subtask should be independently executable
- Subtasks should have clear boundaries
- Order subtasks by dependency (execute first -> last)
- Subtask title format: `[Parent #N] <action verb> <target>`

## Notes

- Use expensive models (Opus/Sonnet) for planning - this is where thinking matters
- Execution can use cheaper models (Haiku)
- Plans should be detailed enough that any developer can execute
- Plan file saved to `.itx/<N>/00_PLAN.md` for reference

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/00_PLAN.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.
