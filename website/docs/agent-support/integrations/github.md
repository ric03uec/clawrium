# GitHub Integration

**Status:** 🚧 In Development

GitHub integration allows agents to interact with repositories, pull requests, and issues.

---

## Planned Features

- **PR Reviews:** Comment on pull requests
- **Issue Management:** Read and create issues
- **Code Search:** Search repositories
- **Actions:** Trigger and monitor workflows
- **Webhooks:** React to GitHub events
- **Notifications:** Summarize activity

## Timeline

**Target:** Q2 2026

**Milestone:** [SEA (Secondary Engagement & Automation)](https://github.com/ric03uec/clawrium/milestones)

Track progress: [GitHub Issue #TBD](https://github.com/ric03uec/clawrium/issues)

---

## Use Cases

### Code Review Assistant

```
User: Review PR #123 in myorg/myrepo
Agent: Analyzing PR #123...
      
      Summary:
      - 5 files changed, 250 lines added
      - No obvious security issues
      - 2 suggestions:
        1. Consider adding error handling on line 45
        2. Missing docstring for new function
```

### Issue Triage

```
User: Summarize open issues from last week
Agent: Found 12 new issues:
      
      Priority breakdown:
      - 3 high priority (label: bug)
      - 7 medium priority (label: enhancement)  
      - 2 low priority (label: question)
      
      2 issues need more info (label: needs-repro)
```

### Release Notes

```
User: Draft release notes for v2.1.0
Agent: Analyzing commits since v2.0.0...
      
      ## What's New
      
      ### Features
      - Add OAuth support (#234)
      - New dashboard widgets (#245)
      
      ### Bug Fixes
      - Fix memory leak in worker (#240)
      - Correct timezone handling (#238)
```

---

## Preliminary Setup (Subject to Change)

### 1. Create GitHub App

1. Go to [GitHub Developer Settings](https://github.com/settings/apps)
2. Click **New GitHub App**
3. Configure:
   - Name: `My Claw Agent`
   - Homepage URL: Your URL
   - Callback URL: Not needed for CLI
4. Set permissions:
   - Repository: Read & Write
   - Pull requests: Read & Write
   - Issues: Read & Write
   - Actions: Read (optional)
5. Create app and generate private key

### 2. Install App

1. Install the app on your repositories
2. Note the installation ID

### 3. Configure in Clawrium (When Available)

```bash
clm agent configure my-agent
# Select GitHub integration when prompted
```

---

## Authentication

GitHub integration will support:

- **GitHub App:** Recommended for organizations
- **Personal Access Token:** For personal use
- **Fine-grained PAT:** New GitHub feature

---

## Permissions Required

| Feature | Permission | Level |
|---------|------------|-------|
| Read issues | Issues | Read |
| Create issues | Issues | Write |
| Read PRs | Pull requests | Read |
| Comment on PRs | Pull requests | Write |
| Trigger workflows | Actions | Write |

---

## Alternatives (Current Workaround)

Until native integration is available:

1. **CLI Tools:** Use `gh` CLI in agent scripts
   ```bash
   clm chat my-agent
   # In chat: Run "gh issue list --repo myorg/myrepo"
   ```

2. **API via curl:** Make direct API calls
   ```bash
   curl -H "Authorization: token $GITHUB_TOKEN" \
        https://api.github.com/repos/myorg/myrepo/issues
   ```

3. **MCP Tools:** (Coming Q2 2026) Use GitHub MCP server

---

## Vote for Priority

Add a 👍 reaction to [the GitHub integration issue](https://github.com/ric03uec/clawrium/issues) to help prioritize.

---

[Back to Integrations](index.md)
