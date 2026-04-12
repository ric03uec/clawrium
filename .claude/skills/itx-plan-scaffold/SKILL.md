---
name: itx:plan-scaffold
description: Create phased execution plan with entry/exit criteria
argument-hint: "<issue-number>"
---
name: itx:plan-scaffold

# Execution Scaffolding

Create a phased execution plan from a plan-build output, defining entry/exit criteria for each phase.

## Instructions

1. **Fetch Issue**: Get full issue details with existing plan
   ```bash
   gh issue view <number> --json number,title,body,labels,comments
   ```

2. **Read Plan**: Find the plan-build comment from issue comments

3. **Analyze Complexity**:
   - **Simple** (< 3 files, single concern): Single-phase execution
   - **Moderate** (3-8 files, related changes): 2-3 phases
   - **Complex** (8+ files, multiple concerns): Multi-phase with subtasks

4. **Decide Execution Mode**:
   - **Single-phase**: Direct to `/itx:execute`
   - **Multi-phase**: Create subtasks, execute in order

5. **Create Scaffolding**: For each phase, define:
   ```markdown
   ### Phase N: <Name>

   **Entry Criteria** (must be true to start):
   - <condition>
   
   **Exit Criteria** (must be true to complete):
   - <test passing>
   - <validation rule>
   
   **Dependencies**: Phase <N-1> (or "None" for first phase)
   
   **Files Affected**:
   - `path/to/file.ext` - <change type>
   
   **Complexity**: simple/moderate/complex
   ```

6. **Post Scaffolding**: Add as comment on issue
   ```markdown
   ## Execution Scaffolding

   **Mode**: single-phase | multi-phase (<N> phases)

   <phase definitions>

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: scaffolding
   **Skill**: /itx:plan-scaffold
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <original user prompt>
   ```

   </details>
   ```

7. **Create Subtasks (if multi-phase)** and link as sub-issues:
    ```bash
    # Create subtask
    CHILD_URL=$(gh issue create \
      --title "[Parent #<parent>] Phase N: <name>" \
      --label "ready" \
      --body "<phase details>")
    CHILD_NUM=$(basename $CHILD_URL)
    
    # Link as sub-issue using GraphQL
    gh api graphql -f query='
      mutation($parentId: ID!, $childId: ID!) {
        addSubIssue(input: {issueId: $parentId, subIssueId: $childId}) {
          issue { number }
          subIssue { number }
        }
      }' \
      -f parentId=$(gh api graphql -f query='query($owner: String!, $repo: String!, $issue: Int!) { repository(owner: $owner, name: $repo) { issue(number: $issue) { id } } }' -f owner=OWNER -f repo=REPO -F issue=$PARENT_NUM | jq -r '.data.repository.issue.id') \
      -f childId=$(gh api graphql -f query='query($owner: String!, $repo: String!, $issue: Int!) { repository(owner: $owner, name: $repo) { issue(number: $issue) { id } } }' -f owner=OWNER -f repo=REPO -F issue=$CHILD_NUM | jq -r '.data.repository.issue.id')
    ```

8. **Update Labels**:
   ```bash
   gh issue edit <number> --remove-label "planned" --add-label "ready"
   ```

## Phase Guidelines

### Entry Criteria Patterns
- Prerequisite phase complete
- Environment prepared (dependencies, config)
- Data/fixtures available
- Branch created

### Exit Criteria Patterns
- All tests passing
- Lint/typecheck clean
- Manual verification checklist
- Documentation updated
- No regressions introduced

### Ordering Rules
1. Foundation phases first (schemas, models)
2. Core logic second (services, business rules)
3. Integration third (APIs, handlers)
4. Presentation last (UI, docs)

## Notes

- Each phase should be independently verifiable
- Exit criteria of phase N = entry criteria of phase N+1
- Use entry/exit criteria to enable parallel execution of independent phases
- Prefer more smaller phases over fewer larger ones
