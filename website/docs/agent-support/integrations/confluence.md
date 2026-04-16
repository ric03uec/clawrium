# Confluence

**Status:** 📋 Not Currently Planned

Atlassian Confluence integration for documentation and knowledge base access.

---

## Why Not Planned?

Confluence integration is not currently on the Clawrium roadmap for the following reasons:

1. **Scope:** Confluence is primarily a documentation/wiki tool, less relevant for agent workflows
2. **Complexity:** Confluence API is complex for read operations
3. **Use Case:** Agents typically don't need to write documentation
4. **Priority:** Jira integration covers the more common Atlassian use case
5. **Alternatives:** Notion integration (if requested) would serve similar needs

---

## Want This Feature?

We welcome community contributions! If you need Confluence support:

### Option 1: Open an Issue

[Create a feature request](https://github.com/ric03uec/clawrium/issues/new?labels=enhancement,integration&title=Add+Confluence+integration+support)

Include:
- Your specific use case
- Read-only vs read-write needs
- Whether you can contribute a PR

### Option 2: Submit a PR

We'd love your contribution! Implementation would involve:

1. Confluence REST API client
2. Authentication (API token or OAuth)
3. Page search and retrieval
4. Content parsing (handle Confluence markup)
5. Optional: Page creation/updates

See [CONTRIBUTING.md](/docs/contributing) for guidelines.

---

## What Would Be Needed

### Authentication

- **API Token:** Personal access token
- **Username + Token:** For server instances
- **OAuth 2.0:** For app integrations

### Use Cases

If implemented, Confluence integration could:

- **Search documentation:** Find relevant pages
- **Answer questions:** Use docs as knowledge base
- **Summarize content:** Extract key information
- **Create pages:** Log agent activities
- **Update docs:** Maintain runbooks

### API Challenges

Confluence API has some complexities:

- Storage format is Confluence markup (not plain markdown)
- Versioning requires handling
- Space/page hierarchy navigation
- Permission model is complex

---

## Alternatives

### Use Jira Instead

For many use cases, [Jira integration](jira.md) (when available) with issue descriptions may suffice.

### Direct API Calls

```bash
curl -u email@example.com:$CONFLUENCE_TOKEN \
     "https://your-domain.atlassian.net/wiki/rest/api/content?spaceKey=TEAM&expand=body.storage"
```

### RAG over Exported Docs

Export Confluence pages and use RAG (Retrieval-Augmented Generation) via the agent's knowledge base.

---

## Related Integrations

| Integration | Status | Use Case |
|-------------|--------|----------|
| **Jira** | 🚧 Q2 2026 | Issue tracking |
| **Notion** | 📋 Not planned | Docs/notes (alternative) |
| **Confluence** | 📋 Not planned | Wiki/docs |

---

## Vote for This Feature

Add a 👍 reaction to [this issue](https://github.com/ric03uec/clawrium/issues) to help us prioritize.

---

[Back to Integrations](index.md)
