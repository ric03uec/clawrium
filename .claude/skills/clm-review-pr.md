---
description: Review a pull request using ATX agents
argument-hint: "[pr-number]"
---

# PR Review

Request a code review using ATX agents.

## Instructions

1. **Identify PR**:
   - If PR number provided, use it
   - If not, find PR for current branch:
     ```bash
     gh pr view --json number,title,url
     ```

2. **Get PR Details**:
   ```bash
   gh pr view <number> --json number,title,body,files,additions,deletions
   gh pr diff <number>
   ```

3. **Invoke ATX Review**:
   Use the `mcp__atx__review_changes` tool or `mcp__atx__request_review` tool:
   ```
   mcp__atx__request_review(prompt="Review PR #<number>")
   ```

4. **Process Review Results**:
   - If rating <= 3/5 or blocking issues exist:
     - List issues to fix
     - Recommend specific changes
   - If rating > 3/5 and no blockers:
     - PR is ready for merge

5. **Report**:
   ```
   ## ATX Review Summary

   **PR**: #<number> - <title>
   **Rating**: <X>/5

   ### Blocking Issues
   <table or "None">

   ### Warnings
   <list or "None">

   ### Suggestions
   <list or "None">

   ### Verdict
   <READY FOR MERGE / NEEDS CHANGES>
   ```

## Notes

- ATX provides specialist reviews (DevOps, code quality, etc.)
- Follow AGENTS.md review requirements:
  - Rating must be > 3/5
  - No blocking issues
- Include ATX review summary in commit message if changes made
