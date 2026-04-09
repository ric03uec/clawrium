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

2. **Update Status to Executing**: Use the project board commands at top of file

3. **Read Plan**: Find the implementation plan in issue comments

4. **Create Execution Checklist**:

   **CRITICAL**: ALWAYS create task checklist before any execution. Do not skip this step.

   Parse the implementation plan and create tasks for tracking:

   a. **Create Implementation Tasks**:
      For each phase/step in the plan, create a task:
      ```
      TaskCreate(
          subject="Implement: <phase/step description>",
          description="<detailed requirements from plan>",
          activeForm="Implementing <phase/step>"
      )
      ```

   b. **Create Verification Tasks**:
      ```
      TaskCreate(
          subject="Run test suite",
          description="Execute 'make test' and ensure all tests pass",
          activeForm="Running tests"
      )

      TaskCreate(
          subject="Run linter",
          description="Execute 'make lint' and fix any issues",
          activeForm="Running linter"
      )

      TaskCreate(
          subject="Verify ATX review requirements",
          description="Request ATX review and address all blocking issues",
          activeForm="Running ATX review"
      )
      ```

   c. **Set Dependencies** (if needed):
      ```
      TaskUpdate(
          taskId="<later-task-id>",
          addBlockedBy=["<prerequisite-task-id>"]
      )
      ```

   d. **Review Task List**:
      ```
      TaskList()  # Confirm all tasks created correctly
      ```

5. **Execute Tasks Systematically**:

   a. Get Next Task: `TaskList()` - Find first pending task with no blockedBy

   b. Start Task: `TaskUpdate(taskId="<task-id>", status="in_progress")`

   c. Execute Changes: Implement the task requirements
      - Make code changes
      - Write/update tests
      - Follow existing code patterns

   d. Complete Task: `TaskUpdate(taskId="<task-id>", status="completed")`

   e. Check Progress: `TaskList()` - See remaining tasks

   f. Repeat until all implementation tasks are completed

6. **Execute Verification Tasks**:

   Follow the same pattern as implementation:
   - Mark verification task as in_progress
   - Run verification (tests, lint, ATX review)
   - Mark as completed
   - Move to next verification task

7. **Create PR**:

   **If in worktree mode**: Branch already exists (created during worktree setup)
   ```bash
   git add <files>
   git commit -m "<message>"
   git push -u origin issue-<number>-<slug>
   gh pr create --title "<title>" --body "Closes #<number>"
   ```

   **If in regular mode**: Create branch first
   ```bash
   git checkout -b issue-<number>-<slug>
   git add <files>
   git commit -m "<message>"
   git push -u origin issue-<number>-<slug>
   gh pr create --title "<title>" --body "Closes #<number>"
   ```

   **WARNING**: Never push to `main`. Always push to feature branch and create PR.

## Progress Tracking with Tasks

### Creating Tasks from Plan

When reading the implementation plan, extract:
- **Implementation steps**: Each becomes a task
- **Files to modify**: Include in task descriptions
- **Dependencies**: Set using addBlockedBy
- **Acceptance criteria**: Include in task descriptions

### Task Naming Convention

```
subject: "Implement: <what>"
description: "<detailed requirements>"
activeForm: "Implementing <what>"
```

Examples:
```
subject: "Implement: Update CLI help text for agent terminology"
description: "Update all help text in src/clawrium/cli/agent.py to use 'agent' instead of 'claw'"
activeForm: "Updating CLI help text"

subject: "Implement: Refactor lifecycle.py function names"
description: "Rename functions: start_claw → start_agent, stop_claw → stop_agent"
activeForm: "Refactoring lifecycle.py"
```

### Standard Verification Checklist

Always create these verification tasks:
1. Run test suite (`make test`)
2. Run linter (`make lint`)
3. Request and address ATX review
4. Verify no regressions

### When You Get Lost

If execution feels unclear or you lose track of progress:
1. Run `TaskList()` to see current state
2. Check which task is in_progress
3. Review that task's description
4. Complete current task before starting next
5. Never jump ahead without marking tasks complete

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

- **ALWAYS create task checklist before execution** - Do not skip this step
- **Use TaskList() frequently** to maintain awareness of progress
- **Complete tasks sequentially** unless explicitly marked as parallel
- **If you feel lost**, check TaskList() to reorient
- Subtasks can use cheaper/faster models (Haiku)
- Parent orchestration can use any model
- Always verify before marking complete
- Don't skip the verification step
