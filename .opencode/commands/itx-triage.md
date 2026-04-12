---
description: Review issues without workflow labels and assign appropriate labels
---

Find and triage issues that don't have workflow labels.

Steps:
1. List unlabeled issues: `gh issue list --state open --json number,title,labels`
2. For each issue without workflow labels:
   - Read the issue body
   - Classify as: bug, feature, or process
   - Add appropriate label: `bug`, `enhancement`, or `process`
   - Add `planning` label to move to planning state
