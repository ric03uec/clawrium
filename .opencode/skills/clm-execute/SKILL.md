---
name: clm:execute
description: Execute the plan for an issue (parent or subtask)
argument-hint: "<issue-number> [in a subtree|--worktree]"
---
name: clm:execute

# Issue Execution

Execute the implementation plan for a GitHub issue.

## Worktree Mode (Recommended for Parallel Execution)

Triggered by `in a subtree` or `--worktree` in arguments. Enables working on multiple issues simultaneously.

### Worktree Naming Convention
```
<repo-parent>/<repo-name>-issue-<number>/
```

Example:
```
~/projects/clawrium/           # Main repo
~/projects/clawrium-issue-35/  # Worktree for issue 35
~/projects/clawrium-issue-42/  # Worktree for issue 42
```

### Worktree Execution Steps

1. **Create Worktree**:
   ```bash
   REPO_NAME=$(basename $(git rev-parse --show-toplevel))
   REPO_PARENT=$(dirname $(git rev-parse --show-toplevel))
   WORKTREE_PATH="${REPO_PARENT}/${REPO_NAME}-issue-${NUMBER}"

   git worktree add "${WORKTREE_PATH}" -b issue-${NUMBER}-<slug> main
   ```

2. **Launch Execution**:

   **If tmux available** (autonomous execution):
   ```bash
   # Create session if not exists
   tmux has-session -t "clm/exec" 2>/dev/null || tmux new-session -d -s "clm/exec"

   # Create window and run claude autonomously
   tmux new-window -t "clm/exec" -n "issue-${NUMBER}" -c "${WORKTREE_PATH}"
   tmux send-keys -t "clm/exec:issue-${NUMBER}" \
     "claude --dangerously-skip-permissions -p '/clm:execute ${NUMBER}'" Enter

   echo "Spawned in tmux 'clm/exec:issue-${NUMBER}'"
   echo "Attach: tmux attach -t clm/exec"
   ```

   **If tmux not available** (fallback):
   Use `AskUserQuestion` to ask:
   - **Subagent**: Spawn Task agent in worktree (non-interactive)
   - **Same session**: Continue in current session (interactive, will ask permissions)

3. **Exit**: After spawning tmux window, exit current execution (work continues in tmux)

### Worktree Cleanup

After PR is merged:
```bash
# Remove worktree
git worktree remove ../clawrium-issue-35

# Or force remove if dirty
git worktree remove --force ../clawrium-issue-35

# Clean up tmux window
tmux kill-window -t "clm/exec:issue-35"
```

## GitHub Project Board

Project ID: `PVT_kwHOABDzzM4BSDdU`
Status Field ID: `PVTSSF_lAHOABDzzM4BSDdUzg_s1SU`

Status Options:
- Backlog: `d1b8c82d`
- Ready: `e68a5cf4`
- Executing: `47fc9ee4`
- In Review: `e78b7dd8`
- Done: `4aea9290`

### Add Issue to Project & Set Status

```bash
# Get issue node ID
NODE_ID=$(gh api repos/ric03uec/clawrium/issues/<number> --jq '.node_id')

# Add to project (returns item ID)
ITEM_ID=$(gh api graphql -f query='
  mutation {
    addProjectV2ItemById(input: {
      projectId: "PVT_kwHOABDzzM4BSDdU"
      contentId: "'"$NODE_ID"'"
    }) { item { id } }
  }
' --jq '.data.addProjectV2ItemById.item.id')

# Set status
gh project item-edit --project-id PVT_kwHOABDzzM4BSDdU --id "$ITEM_ID" \
  --field-id PVTSSF_lAHOABDzzM4BSDdUzg_s1SU --single-select-option-id 47fc9ee4
```

## Instructions

1. **Fetch Issue**: Get full issue details
   ```bash
   gh issue view <number> --json number,title,body,labels,comments
   ```

2. **Identify Issue Type**:
   - **Subtask**: Title starts with `[Parent #N]`
   - **Parent with subtasks**: Has subtask issues linked
   - **Parent without subtasks**: Direct execution

3. **Route Execution**:

### If Parent with Subtasks

1. List subtasks by searching for issues with `[Parent #<number>]` in title
2. For each subtask (in order):
   - Spawn a subagent to execute the subtask
   - Wait for subtask completion
   - Verify subtask is marked done
3. Once all subtasks complete, close parent issue

### If Parent without Subtasks OR Subtask

1. **Log Start**: Add execution start comment
   ```markdown
   ## Execution Started

   Beginning implementation...

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: execution
   **Skill**: /clm:execute
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <user prompt that triggered execution>
   ```

   </details>
   ```

2. **Update Label**:
   ```bash
   gh issue edit <number> --remove-label "ready" --add-label "in-progress"
   ```

3. **Read Plan**: Find the implementation plan in issue comments

4. **Execute**: Implement the changes following the plan
   - Make code changes
   - Write/update tests
   - Follow existing code patterns

5. **Verify**: Run `/clm:verify` to ensure quality

6. **Create Branch and PR**:
   ```bash
   git checkout -b issue-<number>-<slug>
   git add <files>
   git commit -m "<message>"
   git push -u origin issue-<number>-<slug>
   gh pr create --title "<title>" --body "Closes #<number>"
   ```

7. **Update Label**:
   ```bash
   gh issue edit <number> --remove-label "in-progress" --add-label "in-review"
   ```

## Subagent Spawning (for Parent with Subtasks)

Use the Task tool to spawn subagents:
```
Task(
  subagent_type="general-purpose",
  prompt="Execute /clm:execute <subtask-number>",
  description="Execute subtask #<number>"
)
```

Execute subtasks sequentially to avoid conflicts.

## Completion Check (for Subtasks)

After completing a subtask, check if all sibling subtasks are done:
```bash
# Find parent number from title [Parent #N]
# List all subtasks for that parent
# If all closed, close the parent
```

## Notes

- Subtasks can use cheaper/faster models (Haiku)
- Parent orchestration can use any model
- Always verify before marking complete
- Don't skip the verification step
