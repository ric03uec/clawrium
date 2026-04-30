---
name: itx:review-pr
description: Request code review for a pull request
argument-hint: "[pr-number]"
---
name: itx:review-pr

# PR Review

Request a code review for a pull request.

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

3. **Check Review Configuration**:
   ```bash
   ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
   if [ -f "$ITX_CONFIG" ]; then
     REVIEW_ENABLED=$(jq -r '.mcp.review_enabled // false' "$ITX_CONFIG")
     REVIEW_TOOL=$(jq -r '.mcp.review_tool // "mcp__atx__request_review"' "$ITX_CONFIG")
   else
     REVIEW_ENABLED="false"
   fi
   ```

4. **Execute Review**:

### If MCP Review Enabled

Use the configured MCP tool for automated review:

```
# Use the tool specified in config (default: mcp__atx__request_review)
$REVIEW_TOOL(prompt="Review PR #<number>")
```

**Process Review Results**:
- If rating <= 3/5 or blocking issues exist:
  - List issues to fix
  - Recommend specific changes
- If rating > 3/5 and no blockers:
  - PR is ready for merge

**Report**:
```
## Automated Review Summary

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

### If MCP Review Not Enabled (Manual Review)

Perform manual review using checklist:

**Review Checklist**:

1. **Code Quality**:
   - [ ] Code follows project conventions and style
   - [ ] No obvious bugs or logic errors
   - [ ] Error handling is appropriate
   - [ ] No security vulnerabilities (injection, XSS, etc.)
   - [ ] No hardcoded credentials or secrets

2. **Testing**:
   - [ ] Tests added for new functionality
   - [ ] Existing tests still pass
   - [ ] Edge cases are covered
   - [ ] Test coverage is adequate

3. **Documentation**:
   - [ ] Code is self-documenting or has comments where needed
   - [ ] Public APIs are documented
   - [ ] README updated if needed

4. **Architecture**:
   - [ ] Changes align with existing patterns
   - [ ] No unnecessary complexity
   - [ ] Dependencies are justified
   - [ ] Performance considerations addressed

5. **PR Hygiene**:
   - [ ] PR title and description are clear
   - [ ] Commits are logical and well-named
   - [ ] No unrelated changes included
   - [ ] Links to related issues

**Report**:
```
## Manual Review Summary

**PR**: #<number> - <title>

### Review Checklist Results

#### Code Quality: /
<findings>

#### Testing: /
<findings>

#### Documentation: /
<findings>

#### Architecture: /
<findings>

#### PR Hygiene: /
<findings>

### Issues to Address
<list blocking issues or "None">

### Suggestions
<list improvements or "None">

### Verdict
<READY FOR MERGE / NEEDS CHANGES>
```

5. **Add Review Comment** (for both modes):
   Post review summary as PR comment:
   ```bash
   gh pr comment <number> --body "<review summary from above>"
   ```

6. **Update Issue Status** (if configured):
   ```bash
   # Check if project board is enabled
   ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
   if [ -f "$ITX_CONFIG" ]; then
     PROJECT_ENABLED=$(jq -r '.github.project_board.enabled // false' "$ITX_CONFIG")
     if [ "$PROJECT_ENABLED" = "true" ]; then
       # Extract repo info
       REMOTE_URL=$(git config --get remote.origin.url)
       OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's/.*[:/]([^/]+\/[^/]+)(\.git)?$/\1/')
       OWNER=$(echo "$OWNER_REPO" | cut -d'/' -f1)
       REPO=$(echo "$OWNER_REPO" | cut -d'/' -f2)

       # Load project config
       PROJECT_ID=$(jq -r '.github.project_board.project_id' "$ITX_CONFIG")
       STATUS_FIELD_ID=$(jq -r '.github.project_board.status_field_id' "$ITX_CONFIG")
       IN_REVIEW_ID=$(jq -r '.github.project_board.status_options.in_review' "$ITX_CONFIG")

       # Get issue number from PR
       ISSUE_NUM=$(gh pr view <number> --json number --jq '.number')
       NODE_ID=$(gh api repos/$OWNER/$REPO/issues/$ISSUE_NUM --jq '.node_id')

       # Get project item ID
       ITEM_ID=$(gh api graphql -f query='
         query($projectId: ID!, $contentId: ID!) {
           node(id: $projectId) {
             ... on ProjectV2 {
               items(first: 100) {
                 nodes {
                   id
                   content {
                     ... on Issue { id }
                   }
                 }
               }
             }
           }
         }
       ' -f projectId="$PROJECT_ID" -f contentId="$NODE_ID" | \
         jq -r ".data.node.items.nodes[] | select(.content.id == \"$NODE_ID\") | .id")

       # Update status to In Review
       gh project item-edit --project-id "$PROJECT_ID" --id "$ITEM_ID" \
         --field-id "$STATUS_FIELD_ID" --single-select-option-id "$IN_REVIEW_ID"
     fi
   fi
   ```

## Configuration

Enable MCP-based automated review in `.claude/itx-config.json`:

```json
{
  "mcp": {
    "review_enabled": true,
    "review_tool": "mcp__atx__request_review"
  }
}
```

**Default** (no config): Manual review mode with checklist

See [CONFIG.md](../../CONFIG.md) for full configuration options.

## Notes

**MCP Review Mode**:
- Automated specialist reviews
- Faster turnaround
- Requires MCP server configuration
- Rating-based approval (> 3/5)

**Manual Review Mode**:
- Comprehensive checklist-based review
- No external dependencies
- Requires human reviewer
- Detailed findings documentation

**Best Practices**:
- Review promptly after PR creation
- Address all blocking issues before merge
- Use suggestions to improve code quality
- Update PR description with review findings

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/02_VERIFY.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.
