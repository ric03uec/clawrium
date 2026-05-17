# Integrations

Integrations allow agents to interact with external tools and services, extending their capabilities beyond chat.

## Available Integrations

| Integration | Status | Agents | Use Case |
|-------------|:------:|--------|----------|
| **[Atlassian (Jira + Confluence)](atlassian.md)** | ✅ | Hermes (MCP), OpenClaw, ZeroClaw | Issue tracking, docs / knowledge base |
| **[GitHub](github.md)** | 🚧 | OpenClaw (planned) | PR reviews, issues |
| **[GitLab](gitlab.md)** | 📋 | Not planned | Alternative to GitHub |
| **[Linear](linear.md)** | 📋 | Not planned | Issue tracking |
| **[Notion](notion.md)** | 📋 | Not planned | Knowledge base |

## Integration vs Provider vs Channel

| Component | Purpose | Example |
|-----------|---------|---------|
| **Provider** | AI model backend | OpenAI GPT-4 |
| **Channel** | How users talk to agent | Discord, CLI |
| **Integration** | What the agent can do | Read GitHub issues |

## How Integrations Work

Integrations typically:

1. **Read data:** Fetch information from external services
2. **Take actions:** Create/update items in external services
3. **Receive events:** Webhooks for real-time updates
4. **Use credentials:** API keys or OAuth tokens

## Configuration

Integrations are managed independently of agents — define one once, then attach it to one or more agents.

**From the CLI:**

```bash
clm integration types                  # list supported types
clm integration add my-github --type github
clm integration credentials my-github  # paste tokens interactively
```

**From the web dashboard:**

`clm gui` opens an **Integrations** page where you can add, edit credentials, and remove integrations through a form. The page surfaces how many agents use each integration so you don't accidentally remove one that's in use; credential values are never returned to the browser.

## Security

- API tokens stored securely
- Scoped permissions (least privilege)
- Audit logging for actions
- Per-integration credential isolation

## Requesting New Integrations

To request a new integration:

1. Check if it exists in [📋 Not Planned](gitlab.md) section
2. [Open an issue](../../issues/new) describing:
   - The service (e.g., PagerDuty, Zendesk)
   - Use case
   - Required actions (read, write, both)
3. Consider contributing a PR

---

See individual integration pages for detailed setup instructions.
