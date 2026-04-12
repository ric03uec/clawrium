---
description: Check status of open pull requests
---

Check the status of all open pull requests.

Steps:
1. List open PRs: `gh pr list --json number,title,author,reviewDecision,statusCheckRollup`
2. Show each PR's review status and CI status
3. Highlight any PRs that need attention
