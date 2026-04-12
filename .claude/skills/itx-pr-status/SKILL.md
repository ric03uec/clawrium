---
name: itx:pr-status
description: Check status of open pull requests
argument-hint: ""
---
name: itx:pr-status

# PR Status

Check the status of open pull requests for this repository.

## Instructions

1. **List Open PRs**:
   ```bash
   gh pr list --json number,title,author,createdAt,reviewDecision,statusCheckRollup,isDraft
   ```

2. **For Each PR**, gather:
   - PR number and title
   - Author
   - Age (days since created)
   - Review status (approved, changes requested, pending)
   - CI status (passing, failing, pending)
   - Draft status

3. **Check CI Details** (if needed):
   ```bash
   gh pr checks <number>
   ```

4. **Report**:
   ```
   ## Open Pull Requests

   | PR | Title | Author | Age | Reviews | CI | Status |
   |----|-------|--------|-----|---------|----| -------|
   | #N | ... | ... | Xd | ... | ... | ... |

   ### PRs Needing Attention
   - #X: <reason - e.g., "CI failing", "Needs review">

   ### Ready to Merge
   - #Y: <title>
   ```

5. **Highlight Issues**:
   - PRs with failing CI
   - PRs waiting for review > 2 days
   - PRs with requested changes not addressed
   - Stale PRs (> 7 days without activity)

## Notes

- This is a read-only status check
- No prompt logging (read-only operation)
- Use to identify what needs attention
