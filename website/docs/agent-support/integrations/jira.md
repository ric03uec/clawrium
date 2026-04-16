# Jira

**Status:** 🚧 In Development

Jira integration allows agents to interact with Jira issues, projects, and workflows.

---

## Planned Features

- **Issue Management:** Read, create, and update issues
- **Search:** JQL query support
- **Comments:** Add and read comments
- **Transitions:** Move issues through workflows
- **Sprint Management:** View and update sprints
- **Reporting:** Summarize project status

## Timeline

**Target:** Q2 2026

**Milestone:** [SEA](https://github.com/ric03uec/clawrium/milestone/2)

Track progress: [GitHub Issue #230](https://github.com/ric03uec/clawrium/issues/230)

---

## Use Cases

### Daily Standup Summary

```
User: What's the status of PROJ sprint?
Agent: Sprint "March 2026":
      
      Completed: 12/20 issues (60%)
      In Progress: 5 issues
      Blocked: 3 issues
      
      Blocked issues:
      - PROJ-123: Waiting for API keys
      - PROJ-124: Dependency on external team
      - PROJ-125: Requirements unclear
```

### Issue Creation

```
User: Create a bug for the login issue
Agent: Creating issue...
      
      Title: Login fails with 500 error
      Type: Bug
      Priority: High
      
      PROJ-456 created and assigned to you.
```

### Ticket Triage

```
User: Show me high priority bugs from this week
Agent: Found 5 high priority bugs:
      
      1. PROJ-401: Memory leak (Created: 2 days ago)
      2. PROJ-402: Database timeout (Created: 3 days ago)
      3. PROJ-403: Race condition (Created: 4 days ago)
      
      2 issues are unassigned.
```

---

## Preliminary Setup (Subject to Change)

### 1. Create API Token

1. Log in to Jira
2. Go to **Account Settings** → **Security** → **API Tokens**
3. Click **Create API Token**
4. Name it (e.g., "Claw Agent")
5. Copy the token

### 2. Get Instance URL

- Cloud: `https://your-domain.atlassian.net`
- Server: `https://jira.yourcompany.com`

### 3. Configure in Clawrium (When Available)

```bash
clm agent configure my-agent
# Select Jira integration when prompted
```

---

## Authentication

Jira integration will support:

- **API Token:** For Jira Cloud
- **OAuth 2.0:** For enterprise SSO
- **Basic Auth:** For Jira Server/Data Center (legacy)

---

## Permissions Required

| Feature | Permission |
|---------|------------|
| Read issues | Browse Projects |
| Create issues | Create Issues |
| Update issues | Edit Issues |
| Add comments | Add Comments |
| Transition issues | Transition Issues |
| View sprints | View Agile |

---

## Alternatives (Current Workaround)

Until native integration is available:

1. **Jira CLI:** Use command-line tools
   ```bash
   jira issue list --project PROJ --status "In Progress"
   ```

2. **API via curl:** Direct Jira REST API calls
   ```bash
   curl -u email@example.com:$JIRA_TOKEN \
        https://your-domain.atlassian.net/rest/api/3/search \
        -d '{"jql": "project = PROJ"}'
   ```

3. **MCP Tools:** (Coming Q2 2026) Use Jira MCP server

---

## Vote for Priority

Add a 👍 reaction to [the Jira integration issue](https://github.com/ric03uec/clawrium/issues) to help prioritize.

---

[Back to Integrations](index.md)
