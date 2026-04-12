---
description: Review a pull request using ATX agents
---

Request a code review for the current PR.

Steps:
1. If PR number provided as $ARGUMENTS, use it
2. Otherwise find PR for current branch: `gh pr view --json number`
3. Run ATX review agents
4. Fix any blocking issues
5. Re-request review if needed

Review must pass (rating > 3/5, no blocking issues) before merge.
