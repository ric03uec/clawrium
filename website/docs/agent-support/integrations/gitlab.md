# GitLab Integration

**Status:** 📋 Not Currently Planned

GitLab integration for merge requests, issues, and CI/CD pipelines.

---

## Why Not Planned?

GitLab integration is not currently on the Clawrium roadmap for the following reasons:

1. **Overlap:** GitHub integration (in development) covers most Git hosting needs
2. **Demand:** Lower community demand compared to GitHub
3. **Priority:** Jira and GitHub prioritized first
4. **Resources:** Limited development bandwidth
5. **API Similarity:** GitLab API is similar enough to GitHub that adaptation would be straightforward if needed

---

## Want This Feature?

We welcome community contributions! If you need GitLab support:

### Option 1: Open an Issue

[Create a feature request](https://github.com/ric03uec/clawrium/issues/new?labels=enhancement,integration&title=Add+GitLab+integration+support)

Include:
- Your use case (personal, enterprise, etc.)
- Self-hosted vs GitLab.com
- Which features you need most (MRs, issues, CI/CD, etc.)
- Whether you can contribute a PR

### Option 2: Submit a PR

We'd love your contribution! Implementation would be similar to [GitHub integration](github.md):

1. GitLab API client (REST or GraphQL)
2. OAuth or PAT authentication
3. MR/issue operations
4. CI/CD pipeline status
5. Webhook handling

See [CONTRIBUTING.md](/docs/contributing) for guidelines.

---

## What Would Be Needed

### Authentication

- **Personal Access Token:** For GitLab.com or self-hosted
- **OAuth 2.0:** For app-based authentication
- **CI/CD Token:** For pipeline integration

### API Scope

```
api (read, write)
read_repository
write_repository
read_user
```

### Features to Implement

- List/view merge requests
- Create MR comments
- Read/create issues
- View pipeline status
- Trigger pipeline runs
- Search code

---

## Alternatives

### Use GitHub Integration

If you can mirror to GitHub:

```bash
# Mirror GitLab to GitHub
git remote add github https://github.com/user/repo.git
git push github main
```

Then use [GitHub integration](github.md) when available.

### Direct API Calls

Agents can use curl to call GitLab API directly:

```bash
curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
     https://gitlab.com/api/v4/projects/123/issues
```

### MCP Tools

(Coming Q2 2026) Use generic HTTP MCP tools to interact with GitLab API.

---

## Comparison: GitHub vs GitLab

| Feature | GitHub | GitLab |
|---------|--------|--------|
| **Market Share** | ~70% | ~20% |
| **Self-hosted** | Enterprise only | Free option |
| **CI/CD** | GitHub Actions | Built-in (stronger) |
| **API** | REST + GraphQL | REST + GraphQL |
| **Integration Priority** | 🚧 Q2 2026 | 📋 Not planned |

---

## Vote for This Feature

Add a 👍 reaction to [this issue](https://github.com/ric03uec/clawrium/issues) to help us prioritize.

---

[Back to Integrations](index.md)
