# Linear

**Status:** 📋 Not Currently Planned

Linear integration for modern issue tracking.

---

## Why Not Planned?

Linear integration is not currently on the Clawrium roadmap for the following reasons:

1. **Niche:** Linear is popular in startup/tech circles but has smaller market share than Jira
2. **Overlap:** Jira integration (in development) serves the primary issue tracking need
3. **Priority:** GitHub and Jira cover most project management use cases
4. **Resources:** Limited development bandwidth
5. **API Maturity:** Linear's API is newer and still evolving

---

## Want This Feature?

We welcome community contributions! If you need Linear support:

### Option 1: Open an Issue

[Create a feature request](https://github.com/ric03uec/clawrium/issues/new?labels=enhancement,integration&title=Add+Linear+integration+support)

Include:
- Your use case (team size, workflow)
- Features you need most
- Whether Linear is a hard requirement vs nice-to-have
- Whether you can contribute a PR

### Option 2: Submit a PR

We'd love your contribution! Linear has a well-designed GraphQL API:

1. Linear GraphQL API client
2. Personal API key authentication
3. Issue CRUD operations
4. Cycle/sprint management
5. Real-time via webhooks

See [CONTRIBUTING.md](/docs/contributing) for guidelines.

---

## What Would Be Needed

### Authentication

- **Personal API Key:** Get from Linear Settings → API

### API Capabilities

Linear's GraphQL API supports:

- Issues (create, read, update, delete)
- Cycles (sprints)
- Projects
- Teams
- Comments
- Attachments
- Webhooks

### Use Cases

If implemented, Linear integration could:

- **Daily standups:** Summarize cycle progress
- **Issue creation:** Create tickets from chat
- **Triage:** Find unassigned/high priority issues
- **Reporting:** Cycle velocity, burndown
- **Git linking:** View linked PRs

---

## Alternatives

### Use Jira

[Jira integration](jira.md) will be available Q2 2026 and serves similar needs.

### Use GitHub Issues

[GitHub integration](github.md) (Q2 2026) if you're using GitHub for code.

### Notion Database

If you use Notion, database integration (if requested) could track issues.

### Direct API Calls

```bash
curl -H "Authorization: $LINEAR_API_KEY" \
     -H "Content-Type: application/json" \
     -X POST \
     https://api.linear.app/graphql \
     -d '{"query": "query { issues { nodes { id title state { name } } } }" }'
```

---

## Comparison: Linear vs Jira

| Feature | Linear | Jira |
|---------|--------|------|
| **Target** | Startups, modern teams | Enterprise, all sizes |
| **Speed** | Fast, opinionated | Slower, customizable |
| **Market Share** | ~5% | ~70% |
| **API** | GraphQL, modern | REST + GraphQL |
| **Integration Priority** | 📋 Not planned | 🚧 Q2 2026 |

---

## Vote for This Feature

Add a 👍 reaction to [this issue](https://github.com/ric03uec/clawrium/issues) to help us prioritize.

---

[Back to Integrations](index.md)
