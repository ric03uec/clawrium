# Integrations

Integrations allow agents to interact with external tools and services, extending their capabilities beyond chat.

## Available Integrations

| Integration | Status | Agents | Use Case |
|-------------|:------:|--------|----------|
| **[Atlassian (Jira + Confluence)](atlassian.md)** | ✅ | Hermes (MCP), OpenClaw | Issue tracking, docs / knowledge base |
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
clawctl integration registry get --types                 # list supported types
clawctl integration registry create my-github --type github
clawctl integration registry describe my-github # paste tokens interactively
```

See the [`clawctl integration` reference](../../reference/cli/integration.md) for the full command set.

**From the web dashboard:**

The [`Integrations` page](../../web-dashboard.md#integrations) (`clawctl gui` → Integrations) lists every configured integration with its agent usage count and renders dynamic credential fields per type — `Add Integration` for new ones, `Edit credentials` to rotate without re-typing the unchanged values. Credential values are never sent to the browser.

## Security

- API tokens stored securely
- Scoped permissions (least privilege)
- Audit logging for actions
- Per-integration credential isolation

## Requesting New Integrations

To request a new integration:

1. Check if it exists in [📋 Not Planned](gitlab.md) section
2. [Open an issue](https://github.com/ric03uec/clawrium/issues/new) describing:
   - The service (e.g., PagerDuty, Zendesk)
   - Use case
   - Required actions (read, write, both)
3. Consider contributing a PR

---

See individual integration pages for detailed setup instructions.
