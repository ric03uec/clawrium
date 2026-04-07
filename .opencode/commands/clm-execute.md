---
description: Execute the plan for an issue (parent or subtask)
---

Execute the implementation plan for GitHub issue $ARGUMENTS.

## Branch Protection

**NEVER push directly to the `main` branch.** Always create a PR targeting `main`.

## Steps

1. Fetch the issue and find the plan in comments
2. Read the plan phases and entry/exit criteria
3. Update GitHub project status to `Executing`:
   ```bash
   ITEM_ID=$(gh project item-list 1 --owner ric03uec --format json | jq -r '.items[] | select(.content.number == <number>) | .id')
   gh project item-edit --project-id PVT_kwHOABDzzM4BSDdU --id "$ITEM_ID" --field-id PVTSSF_lAHOABDzzM4BSDdUzg_s1SU --single-select-option-id 47fc9ee4
   ```
4. Implement each phase in order:
   - Verify entry criteria before starting
   - Make the changes
   - Verify exit criteria (tests pass)
5. Create PR:
   - **Worktree mode**: Branch already exists, just commit/push/create PR
   - **Regular mode**: Create branch `issue-<number>-<slug>` first
   ```bash
   git add <files>
   git commit -m "<message>"
   git push -u origin issue-<number>-<slug>
   gh pr create --title "<title>" --body "Closes #<number>"
   ```

For parallel execution: add `in a subtree` or `--worktree` to work in a git worktree.
