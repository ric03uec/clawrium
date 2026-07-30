---
name: itx:execute
description: Execute the plan for an issue (parent or subtask)
argument-hint: "[orchestrate] <issue-number> [in a subtree|--worktree]"
---
name: itx:execute

# Issue Execution

Execute the implementation plan for a GitHub issue.

## Orchestrate Mode

Triggered by `orchestrate` as the **first token** in arguments
(e.g. `/itx:execute orchestrate 112`). Use when the issue is a **parent
with linked subtasks** and you want a hands-off, stacked-PR pipeline
across all subtasks.

### Preconditions

- Parent issue exists and has sub-issues linked (via GitHub
  `addSubIssue`). Detect via:
  ```bash
  gh issue view <parent> --json title,body,labels && \
  gh api graphql -f query='query($owner: String!, $repo: String!, $num: Int!) {
    repository(owner: $owner, name: $repo) {
      issue(number: $num) {
        subIssues(first: 50) { nodes { number title state } }
      }
    }
  }' -f owner="$OWNER" -f repo="$REPO" -F num=<parent>
  ```
- `tmux` available on the host. If not, fail with a clear message —
  orchestrate mode requires tmux.
- A plan file exists at `.itx/<parent>/00_PLAN.md` (created by
  `/itx:plan-create`). Refuse to start otherwise.

ATX availability is **not** a precondition. Children use the
fallback chain in **ATX Review** below. Handoff is still keyed on
PR-open — without ATX, that just means the child opens the PR after
local `make test` + `make lint` pass instead of after an ATX rating
clears.

### Orchestration contract

The orchestrator (the claude session that runs orchestrate mode) does
**only these things**:

1. Creates worktrees + branches + tmux windows for each subtask.
2. Spawns a child claude session per subtask via
   `claude --dangerously-skip-permissions '/itx:execute <N>'` in the
   subtask's worktree.
3. Polls subtask PR state every ~5 minutes.
4. When a subtask's PR appears (the child's handoff signal), spawns
   the **next** subtask with the correct stacked base.
5. Surfaces stuck children (PRs carrying `[ITX-STUCK]`) in the
   end-of-run summary table, but does **not** halt the pipeline
   waiting for user input — see "Stuck child" below.

The orchestrator does **NOT**:

- Touch source code.
- Run tests / lint directly.
- Merge PRs. Merging is the user's decision.
- Block on user input. If something requires a decision, the child
  records it as a Callout on its PR and proceeds.
- Bypass ATX when ATX is available; bypass `--no-verify`.
- Spawn all subtask windows up front. Windows are created **on demand**
  when the predecessor's PR is open.

### Stacked PR layout

Given subtasks A, B, C, D (in dependency order from sub-issue
metadata), the orchestrator opens each child's PR against the
**predecessor's branch**, not main:

| Sub | Branch | PR base |
|---|---|---|
| A | `issue-<A>-<slug>` | `main` |
| B | `issue-<B>-<slug>` | `issue-<A>-<slug>` |
| C | `issue-<C>-<slug>` | `issue-<B>-<slug>` |
| D | `issue-<D>-<slug>` | `issue-<C>-<slug>` |

As predecessors merge, GitHub auto-updates downstream PR bases to main.

### tmux layout

- Session name: `<project-name>-issue-<parent>` where `<project-name>`
  is the repo name from `basename $(git rev-parse --show-toplevel)`.
  Example: `clawrium-issue-478`.
- One window per subtask, named `issue-<N>` (the subtask issue number).
  Example: `issue-481`, `issue-482`, `issue-483`.
- Created on demand. User attaches with
  `tmux attach -t <project-name>-issue-<parent>`.
- Window 0 (the session's default window) is owned by the orchestrator
  and runs the polling loop / status display.

### Step-by-step

1. **Parse args.** Extract `orchestrate` token + parent issue number.
   Fall through to regular execution mode if `orchestrate` absent.

2. **Verify preconditions** (above). On failure, exit with a clear
   message citing the missing precondition.

3. **Enumerate subtasks.** Order by sub-issue number (creation order).
   Treat order as dependency order unless the plan file specifies
   otherwise.

4. **Create tmux session:**
   ```bash
   REPO_NAME=$(basename $(git rev-parse --show-toplevel))
   SESSION="${REPO_NAME}-issue-${PARENT}"
   tmux has-session -t "$SESSION" 2>/dev/null || \
     tmux new-session -d -s "$SESSION"
   ```

5. **Spawn subtask A:**
   ```bash
   REPO_PARENT=$(dirname $(git rev-parse --show-toplevel))
   WORKTREE_A="${REPO_PARENT}/${REPO_NAME}-issue-${A_NUM}"
   BRANCH_A="issue-${A_NUM}-<slug>"

   git worktree add "$WORKTREE_A" -b "$BRANCH_A" main

   tmux new-window -t "$SESSION" -n "issue-${A_NUM}" -c "$WORKTREE_A"
   tmux send-keys -t "${SESSION}:issue-${A_NUM}" \
     "claude --dangerously-skip-permissions '/itx:execute ${A_NUM}'" Enter
   ```

6. **Poll predecessor PR state every 5 minutes:**
   ```bash
   gh pr list --repo "$OWNER/$REPO" --head "$BRANCH_A" \
     --json number,state,reviewDecision,body --jq '.[0]'
   ```
   The child opens its PR when its work is ready — that means
   tests + lint pass and, if ATX is available, its iteration loop
   has either cleared or exhausted (with unresolved blockers
   documented as Callouts and an `[ITX-STUCK]` marker on the PR).

   **Do not poll faster than 5 minutes.** Child iterations take
   minutes; faster polling burns cache without changing outcomes.

7. **On predecessor PR open, spawn next subtask:**
   - Create worktree at `${REPO_PARENT}/${REPO_NAME}-issue-${NEXT_NUM}`.
   - Branch from the predecessor's branch (not main).
   - Create tmux window, run child claude.
   - Override the child's default PR base by passing the predecessor's
     branch name in the prompt:
     ```bash
     claude --dangerously-skip-permissions \
       "/itx:execute ${NEXT_NUM} --pr-base=${PREV_BRANCH}"
     ```
     (Child sessions in standard mode must honor `--pr-base` — see
     "PR base override" below.)

8. **Repeat** until all subtasks have open PRs.

9. **Final state.** Orchestrator reports a summary table with each
   subtask's PR URL, ATX rating, and base branch. Then stands down.
   Merging is the user's decision; merging happens bottom-up.

### Stuck child (non-blocking)

A child that exhausts its 3-iteration ATX ceiling without clearing
**still opens its PR**. The PR body documents every unresolved
blocker as a Callout and the PR carries an `[ITX-STUCK]` marker
comment.

The orchestrator's polling loop treats an `[ITX-STUCK]`-marked PR the
same as a clean PR for the purpose of advancing the pipeline — the
child has done its best, recorded the gaps, and handed off. **Do not
halt and do not block on user input.**

In the end-of-run summary, flag every stuck subtask with the count of
unresolved blockers so the user sees them up front. Merging decisions
remain entirely the user's — they can read the Callouts, push back on
the PR, take it over manually, or abandon. The orchestrator stands
down after reporting; it does not wait for that decision.

If the orchestrator itself encounters a genuinely unrecoverable
condition (e.g., worktree directory already exists with a conflicting
branch), it records a Callout on the **parent** issue (#`<parent>`)
and exits non-zero with a summary. It does not prompt.

### PR base override (child contract)

When a child receives `--pr-base=<branch>`, it MUST:

- Open its PR against that branch, not `main`.
- Include `Stacked on top of <branch>` in the PR body so reviewers know
  the dependency chain.

If the child's mode does not support `--pr-base`, the orchestrator
falls back to opening the PR itself after the child finishes:

```bash
gh pr edit <pr-num> --base "$PREV_BRANCH"
```

### Failure modes

- **No subtasks found**: fail with "Issue #N has no linked sub-issues.
  Use `/itx:execute <N>` (without orchestrate) for direct execution."
- **Subtask already has merged PR**: skip and advance to next.
- **Subtask already has open PR**: skip the spawn step; treat as
  "ATX-cleared, advance to next".
- **Worktree already exists**: re-use if branch matches expected name;
  fail otherwise (manual cleanup required).
- **tmux session orphaned**: re-use if exists; do not create duplicate.

### When to use orchestrate mode

- Parent issue with 2+ linked subtasks where order matters.
- You want hands-off execution across the whole chain.
- ATX is enabled and tmux is available.

### When NOT to use orchestrate mode

- Single-issue (no subtasks) — use regular mode.
- You want manual control between every subtask — use regular mode
  with explicit handoffs.

Note: ATX availability is **not** a precondition. If ATX is unavailable
or fails, the orchestrator still spawns subtasks; PR-open remains the
handoff signal. See **ATX Review** below.

## ATX Review (resilient, non-blocking)

Code review via ATX is desired but not required. Children execute
review with a strict fallback chain and persist state so an interrupted
execution can resume without re-running ATX on identical changes.

### Detection chain

Try each step in order; use the first that works. **Never block the
user** waiting for ATX to become available.

1. **ATX via MCP** (preferred). Check whether
   `mcp__atx__request_review` is available in the tool list. If yes,
   call it with the iteration body specified in
   [AGENTS.md](../../../AGENTS.md#if-mcp-review-enabled-atx).
2. **ATX via CLI** (fallback). If MCP is not available, check
   `command -v atx` on the host, then `atx server status`
   (expect `Running: true`). Pick the variant that matches who
   authored the changes — see **ATX CLI surface** below. Parse the
   JSON the same way you'd parse the MCP response.
3. **Skip ATX** (last resort). If neither MCP nor CLI is available,
   **proceed with the work** — do not block, do not prompt the user.
   Record a Callout on the PR (see "Callouts" below) noting that ATX
   was unavailable so the reviewer knows to do a manual pass.

### ATX CLI surface

Verified against `atx` v26.07.09. There is no `--pr` flag and no
`--json` flag; JSON is `--format json`.

Pick the variant by **who authored the changes**:

| Situation | Command |
|---|---|
| A Claude Code session made the edits (hooks captured them) | `atx review --format json` |
| Anything else — another agent's edits, a commit range, staged changes, CI | `atx review request -p "<scope>" --format json` |

`atx review` is session-scoped: it reviews what ATX hooks captured. If
the edits came from a non-Claude-Code agent, the hooks captured nothing
and the review comes back empty — use `atx review request`, which is
stateless and takes the scope in the prompt.

```bash
atx server status                       # Running: true
atx project status                      # project registered + supervisor running

atx review --format json                # session mode
atx review request \
  --prompt "Review the full diff of this branch against main (git diff main...HEAD)." \
  --format json --timeout 15m           # stateless mode

atx task list --format json --status running   # is a review still in flight
atx task cancel <id>                           # recover a hung review
```

Both commands accept `--worktree <name>` to run in a worktree's
working-directory context. The worktree name equals its branch name;
resolve it with:

```bash
atx project worktrees list --format json \
  | jq -r --arg b "$BRANCH" '.worktrees[] | select(.branch==$b) | .name'
```

Other flags: `--effort low|medium|high|xhigh|xtreme` (per-call tier
override), `--agent <name>` (pin an on-demand specialist),
`--review <id>` (join an existing Review group), `--timeout` (default
15m). Output is the v2 envelope — `atx_review.*` plus
`caller_instructions`.

**Reading the rating.** The `.rating` field from
`atx task list --format json` is a coarse aggregate that can disagree
with the leader's `Rating: N/5` line inside `.result`. Trust the review
body, not the JSON field. Never `tail -n` the CLI output — the full
body is authoritative.

### Session ID persistence

Whenever an ATX review is requested (MCP or CLI), persist the session
metadata immediately to `.itx/<N>/atx-session.json`:

```json
{
  "session_id": "<id returned by ATX>",
  "transport": "mcp" | "cli",
  "commit_sha": "<HEAD sha at the moment review was requested>",
  "iteration": 1,
  "last_rating": null,
  "last_blockers": [],
  "started_at": "<ISO-8601 UTC>",
  "updated_at": "<ISO-8601 UTC>"
}
```

Update the file after every iteration with `iteration`, `last_rating`,
`last_blockers`, and `updated_at`. Commit this file alongside your
code changes — it's a planning artifact and helps the next run.

### On resume / re-entry

When `/itx:execute <N>` starts and `.itx/<N>/atx-session.json` exists:

1. Read the file.
2. Compare `commit_sha` with current `git rev-parse HEAD`.
   - **Match + `last_rating > 3` + no blockers** → ATX already cleared
     these changes. Skip ATX entirely; proceed to PR open / push.
   - **Match + unresolved blockers** → Resume the same session
     (poll status if MCP / re-fetch if CLI) instead of starting a new
     review. This avoids burning cost on duplicate runs over identical
     changes.
   - **Mismatch** (HEAD has moved) → Stale session. Delete the file
     and start a fresh ATX review against the new commit.
3. If `transport` differs from what's currently available (e.g., file
   says `mcp` but only CLI is available now): treat as stale, start
   fresh — sessions are not portable across transports.

### Iteration ceiling (non-blocking)

Run at most **3** ATX iterations. After the 3rd iteration:

- If Rating > 3/5 with no blockers: open / update PR normally with
  the ATX summary in the body.
- If still blocked: **open the PR anyway** with:
  - The full ATX iteration history in the PR body (per
    `<pr-format-atx>` in AGENTS.md).
  - A **Callouts** section (see below) enumerating every unresolved
    blocker with a best-guess decision and the reasoning. Do not
    leave the work in an open-ended "stuck" state — close out with a
    callout instead.
  - Add the `[ITX-STUCK]` marker comment on the PR so the
    orchestrator's polling loop can flag it.

This replaces the older "wait for user direction" behavior. The
orchestrator may still surface a stuck child in its end-of-run
summary, but it will not pause the pipeline waiting for input — it
either proceeds to the next subtask (if one is queued) or stands down
with the report.

## Callouts (required in every PR body)

Every PR opened by `/itx:execute` MUST include a **Callouts** section
near the bottom of the body — even if empty. Format:

```markdown
## Callouts

- [DECISION] <one-line summary of a non-obvious choice you made>
  - Why: <best-guess rationale based on existing project standards>
  - Alternatives considered: <briefly>
  - Reviewer: confirm or push back.

- [UNRESOLVED] <what could not be resolved by the agent alone>
  - Best guess applied: <what you did anyway>
  - Reviewer: please verify.

- [ENVIRONMENT] <anything unusual about the execution environment>
  - Example: "ATX unavailable; review path was manual."

- [TODO-FOLLOWUP] <work intentionally deferred>
  - Tracking: <issue number or `to be filed`>
```

If you would otherwise want to ask the user a question via
`AskUserQuestion`, **don't** — make a best-guess decision using
existing project conventions (CLAUDE.md, AGENTS.md, neighboring code)
and record it as a `[DECISION]` callout instead. The PR is the
synchronization point with the user; do not block during execution.

If there are genuinely no callouts, write:

```markdown
## Callouts

_None._
```

so the reviewer knows the section wasn't forgotten.

## Worktree Mode (Recommended for Parallel Execution)

Triggered by `in a subtree` or `--worktree` in arguments. Enables working on multiple issues simultaneously.

### Worktree Naming Convention
```
<repo-parent>/<repo-name>-issue-<number>/
```

Example:
```
~/projects/myrepo/           # Main repo
~/projects/myrepo-issue-35/  # Worktree for issue 35
~/projects/myrepo-issue-42/  # Worktree for issue 42
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

   **If tmux available** (interactive execution in background):
   ```bash
   REPO_NAME=$(basename $(git rev-parse --show-toplevel))
   SESSION="${REPO_NAME}-issue-${NUMBER}"

   # Create session if not exists. Session-per-issue keeps standalone
   # runs isolated from orchestrate-mode sessions (which use the parent
   # issue number).
   tmux has-session -t "$SESSION" 2>/dev/null || \
     tmux new-session -d -s "$SESSION"

   # Create window and run claude interactively (no -p flag so you can watch execution)
   tmux new-window -t "$SESSION" -n "issue-${NUMBER}" -c "${WORKTREE_PATH}"
   tmux send-keys -t "${SESSION}:issue-${NUMBER}" \
     "claude --dangerously-skip-permissions '/itx:execute ${NUMBER}'" Enter

   echo "Spawned in tmux '${SESSION}:issue-${NUMBER}'"
   echo "Attach: tmux attach -t ${SESSION}"
   ```

   **If tmux not available** (fallback):
   Do **not** prompt the user. Spawn a Task subagent
   (`subagent_type="general-purpose"`) in the worktree with prompt
   `/itx:execute ${NUMBER}`. Record this fallback in the PR's
   **Callouts** section so the user knows the execution path differed
   from the default (tmux + interactive claude).

3. **Exit**: After spawning tmux window, exit current execution (work continues in tmux)

### Worktree Cleanup

After PR is merged:
```bash
# Remove worktree
git worktree remove ../<repo>-issue-35

# Or force remove if dirty
git worktree remove --force ../<repo>-issue-35

# Clean up tmux session (standalone mode: one session per issue)
tmux kill-session -t "<repo>-issue-35"

# Or, for orchestrate mode (one session per parent, kill just the window):
tmux kill-window -t "<repo>-issue-<parent>:issue-35"
```

## GitHub Project Board (Optional)

Project board integration is **optional** and controlled via `.claude/itx-config.json`.

### Check if Project Board is Enabled

```bash
ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
if [ -f "$ITX_CONFIG" ]; then
  PROJECT_ENABLED=$(jq -r '.github.project_board.enabled // false' "$ITX_CONFIG")
  if [ "$PROJECT_ENABLED" = "true" ]; then
    # Load project board configuration
    PROJECT_ID=$(jq -r '.github.project_board.project_id' "$ITX_CONFIG")
    STATUS_FIELD_ID=$(jq -r '.github.project_board.status_field_id' "$ITX_CONFIG")
    BACKLOG_ID=$(jq -r '.github.project_board.status_options.backlog' "$ITX_CONFIG")
    READY_ID=$(jq -r '.github.project_board.status_options.ready' "$ITX_CONFIG")
    EXECUTING_ID=$(jq -r '.github.project_board.status_options.executing' "$ITX_CONFIG")
    IN_REVIEW_ID=$(jq -r '.github.project_board.status_options.in_review' "$ITX_CONFIG")
    DONE_ID=$(jq -r '.github.project_board.status_options.done' "$ITX_CONFIG")
  fi
else
  PROJECT_ENABLED="false"
fi
```

### Add Issue to Project & Set Status (if enabled)

**Only execute if `PROJECT_ENABLED="true"`**:

```bash
# Extract repository info
REMOTE_URL=$(git config --get remote.origin.url)
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's/.*[:/]([^/]+\/[^/]+)(\.git)?$/\1/')
OWNER=$(echo "$OWNER_REPO" | cut -d'/' -f1)
REPO=$(echo "$OWNER_REPO" | cut -d'/' -f2)

# Get issue node ID
NODE_ID=$(gh api repos/$OWNER/$REPO/issues/<number> --jq '.node_id')

# Add to project (returns item ID)
ITEM_ID=$(gh api graphql -f query='
  mutation($projectId: ID!, $contentId: ID!) {
    addProjectV2ItemById(input: {
      projectId: $projectId
      contentId: $contentId
    }) { item { id } }
  }
' -f projectId="$PROJECT_ID" -f contentId="$NODE_ID" --jq '.data.addProjectV2ItemById.item.id')

# Set status to Executing
gh project item-edit --project-id "$PROJECT_ID" --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD_ID" --single-select-option-id "$EXECUTING_ID"
```

**If project board not enabled**, skip all project board operations silently.

## Branch Protection

**NEVER push directly to the `main` branch.**

Always:
1. Work on a feature branch: `issue-<number>-<slug>`
2. Push to the feature branch
3. Create a PR targeting `main`

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
   **Skill**: /itx:execute
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <user prompt that triggered execution>
   ```

   </details>
   ```

2. **Update Status to Executing** (if project board enabled):
   Use the conditional project board commands above.
   If not enabled, skip this step silently.

3. **Read Plan**: Find the implementation plan in issue comments or `.itx/<N>/01_EXECUTION.md`

4. **Load Build Configuration**:
   ```bash
   ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
   if [ -f "$ITX_CONFIG" ]; then
     TEST_CMD=$(jq -r '.build.test_command // "make test"' "$ITX_CONFIG")
     LINT_CMD=$(jq -r '.build.lint_command // "make lint"' "$ITX_CONFIG")
   else
     TEST_CMD="make test"
     LINT_CMD="make lint"
   fi
   ```

5. **Create Execution Checklist**:

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
          description="Execute configured test command and ensure all tests pass",
          activeForm="Running tests"
      )

      TaskCreate(
          subject="Run linter",
          description="Execute configured lint command and fix any issues",
          activeForm="Running linter"
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

6. **Execute Tasks Systematically**:

   a. Get Next Task: `TaskList()` - Find first pending task with no blockedBy

   b. Start Task: `TaskUpdate(taskId="<task-id>", status="in_progress")`

   c. Execute Changes: Implement the task requirements
      - Make code changes
      - Write/update tests
      - Follow existing code patterns

   d. Complete Task: `TaskUpdate(taskId="<task-id>", status="completed")`

   e. Check Progress: `TaskList()` - See remaining tasks

   f. Repeat until all implementation tasks are completed

7. **Execute Verification Tasks**:

   Follow the same pattern as implementation:
   - Mark verification task as in_progress
   - Run verification using configured commands ($TEST_CMD, $LINT_CMD)
   - Mark as completed
   - Move to next verification task

8. **Create PR**:

   PR body MUST follow the templates in AGENTS.md (ATX or manual,
   depending on what was actually used during execution) **and** MUST
   include a `## Callouts` section near the bottom — see the
   **Callouts** section earlier in this skill. The Callouts section is
   non-optional; write `_None._` if there are none.

   **If in worktree mode**: Branch already exists (created during worktree setup)
   ```bash
   git add <files>
   git commit -m "<message>"
   git push -u origin issue-<number>-<slug>
   gh pr create --title "<title>" --body-file <body-file>  # body must include Callouts
   ```

   **If in regular mode**: Create branch first
   ```bash
   git checkout -b issue-<number>-<slug>
   git add <files>
   git commit -m "<message>"
   git push -u origin issue-<number>-<slug>
   gh pr create --title "<title>" --body-file <body-file>
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
subject: "Implement: Update CLI help text for new terminology"
description: "Update all help text in src/cli/main.py to use new terminology"
activeForm: "Updating CLI help text"

subject: "Implement: Refactor service.py function names"
description: "Rename functions: old_name -> new_name, another_old -> another_new"
activeForm: "Refactoring service.py"
```

### Standard Verification Checklist

Always create these verification tasks:
1. Run test suite (using configured test command)
2. Run linter (using configured lint command)
3. Verify no regressions

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
  prompt="Execute /itx:execute <subtask-number>",
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

## Configuration

Build commands are configurable via `.claude/itx-config.json`:

```json
{
  "build": {
    "test_command": "npm test",
    "lint_command": "npm run lint"
  }
}
```

**Defaults** (no config): `make test`, `make lint`

See [CONFIG.md](../../CONFIG.md) for full configuration options.

## Notes

- **NEVER block on user input.** No `AskUserQuestion`, no interactive
  prompts. When in doubt, follow existing project standards (CLAUDE.md,
  AGENTS.md, neighboring code) and record the decision as a Callout on
  the PR. The PR is the synchronization point with the user.
- **Always include a Callouts section in the PR body** — see the
  Callouts section of this skill. Write `_None._` if empty.
- **ALWAYS create task checklist before execution** — do not skip this step.
- **Use TaskList() frequently** to maintain awareness of progress.
- **Complete tasks sequentially** unless explicitly marked as parallel.
- **If you feel lost**, check TaskList() to reorient.
- **ATX is best-effort**: try MCP, then CLI, then skip and note in
  Callouts. Never block on ATX availability. Persist
  `.itx/<N>/atx-session.json` so interrupted runs don't re-run ATX on
  identical changes.
- Project board updates are optional and only execute if configured.
- Build commands automatically adapt to project configuration.
- Subtasks can use cheaper/faster models (Haiku).
- Parent orchestration can use any model.
- Always verify before marking complete — don't skip the verification step.

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/01_EXECUTION.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.
