# Atlassian (Jira + Confluence)

**Status:** ✅ Supported (Hermes via MCP, OpenClaw via `.env`). ZeroClaw integrations are deferred — see [ZeroClaw → Deferred items](../zeroclaw.md#deferred-items--follow-ups).

Atlassian integration connects agents to **Jira** and **Confluence** on Atlassian Cloud using a single set of credentials. On Hermes the integration is wired through the [`mcp-atlassian`](https://pypi.org/project/mcp-atlassian/) MCP server — hermes launches it as a subprocess via `uvx` and registers its Jira/Confluence tools at startup. On OpenClaw the credentials are rendered into the agent's environment (`.env`) so the agent can call the Jira/Confluence REST API directly.

This is a **headless, no-UI** integration. Authentication is via Atlassian API token only — there is no browser-based OAuth approval at any step.

---

## What you can do

| Capability | Hermes (MCP) | OpenClaw |
|------------|:------------:|:--------:|
| Read Jira issues / JQL search | ✅ | via API |
| Create / update / transition issues | ✅ | via API |
| Read / search Confluence pages | ✅ | via API |
| Create / update Confluence pages | ✅ | via API |
| Add Jira comments | ✅ | via API |
| Sprint queries | ✅ | via API |

On Hermes the surface is the full `mcp-atlassian` toolset (≈72 tools across Jira + Confluence). On OpenClaw the agent uses its general tool-use surface (HTTP, shell) backed by the rendered credentials.

---

## Auth model

| Method | Headless? | Supported |
|--------|:---------:|:---------:|
| API Token (`USERNAME` + `API_TOKEN`) | Yes | ✅ Atlassian Cloud |
| Personal Access Token (server / Data Center) | Yes | 📋 Roadmap |
| OAuth 2.0 | No (browser required) | ❌ Not supported |

**One credential set drives both Jira and Confluence** — on Atlassian Cloud they share an account, instance URL, and API token. clm stores them as `ATLASSIAN_URL` / `ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN`; the per-agent template derives `JIRA_*` / `CONFLUENCE_*` from those at render time (Confluence URL is `<ATLASSIAN_URL>/wiki`).

---

## Setup

### 1. Generate an Atlassian API token

1. Visit **[https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)**.
2. Click **Create API token**.
3. Name it (e.g. `clawrium`) and copy the token immediately — Atlassian only shows it once.

### 2. Register the integration in clm

```bash
clm integration add work-atlassian --type atlassian
```

You will be prompted for:

| Credential | Required | Example |
|------------|:--------:|---------|
| `ATLASSIAN_URL` | Yes | `https://company.atlassian.net` |
| `ATLASSIAN_EMAIL` | Yes | `dev@company.com` |
| `ATLASSIAN_API_TOKEN` | Yes | (from step 1) |
| `CONFLUENCE_SPACES_FILTER` | No | `ENG,PROD` |
| `JIRA_PROJECTS_FILTER` | No | `PROJ,OPS` |

The filter fields, when set, scope the MCP tool surface to specific Jira projects / Confluence spaces — useful for limiting noise in large workspaces.

### 3. Assign the integration to an agent

```bash
clm agent integration add my-hermes work-atlassian
```

### 4. Configure the agent

```bash
clm agent configure my-hermes
```

For **Hermes**, the configure playbook:

1. Installs `uv` for the agent user via `pip install --user uv==<pinned-version>` (PyPI hash-verified; no `curl|sh`).
2. Pre-installs `mcp-atlassian` at a pinned version: `uv tool install --force mcp-atlassian==<pinned-version>`.
3. Renders an `mcp_servers:` block into `~/.hermes/config.yaml` with the Atlassian credentials embedded as single-quoted YAML scalars (escaped via the template's `yaml_quote` macro).
4. Restarts `hermes-<agent-name>.service`. Hermes reads `config.yaml`, launches `uvx --from mcp-atlassian==<version> mcp-atlassian` as a subprocess, and registers the Jira/Confluence tools.

For **OpenClaw**, the playbook renders the same credentials into `~/.openclaw/.env` as `JIRA_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` / `CONFLUENCE_URL` / `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` (shell-quoted via the template's `shell_quote` macro).

For **ZeroClaw**, Atlassian (and all other) integrations are not wired in this iteration. The `[integrations]` table is not emitted by `clm`'s `config.toml.j2`. Tracked as a follow-up to issue #112 — see [ZeroClaw → Deferred items](../zeroclaw.md#deferred-items--follow-ups).

### 5. Verify

```bash
clm agent chat my-hermes
> list my open jira tickets
> search confluence for "onboarding docs"
```

---

## What gets rendered (Hermes)

The `mcp_servers` block in `~/.hermes/config.yaml` looks like:

```yaml
mcp_servers:
  work_atlassian:
    command: "/home/my-hermes/.local/bin/uvx"
    args: ["--from", "mcp-atlassian==<pinned-version>", "mcp-atlassian"]
    env:
      JIRA_URL: 'https://company.atlassian.net'
      JIRA_USERNAME: 'dev@company.com'
      JIRA_API_TOKEN: 'ATATT3xFf...'
      CONFLUENCE_URL: 'https://company.atlassian.net/wiki'
      CONFLUENCE_USERNAME: 'dev@company.com'
      CONFLUENCE_API_TOKEN: 'ATATT3xFf...'
      JIRA_PROJECTS_FILTER: 'PROJ,OPS'         # only if set
      CONFLUENCE_SPACES_FILTER: 'ENG,PROD'     # only if set
```

The integration name (`work-atlassian`) becomes the MCP server key (`work_atlassian` — hyphens are replaced with underscores). Multiple Atlassian integrations on the same agent (e.g. `team-a-atlassian`, `personal-atlassian`) each get their own `mcp_servers.<name>:` entry.

The render task uses `no_log: true` so the rendered file body never appears in Ansible logs. The file is written `mode: 0600` owned by the agent user.

---

## Trailing slash handling

If you enter `ATLASSIAN_URL = "https://company.atlassian.net/"` (with a trailing slash), the template strips it before deriving the Confluence URL — you will not get `//wiki`. The exact value you enter is preserved for `JIRA_URL`; only the derived Confluence URL has the slash normalized.

---

## Migrating from the old `jira` / `confluence` types

Earlier releases shipped separate `jira` and `confluence` integration types. These were collapsed into the unified `atlassian` type in [#348](https://github.com/ric03uec/clawrium/pull/351). **There is no automatic migration** — by design, clm keeps a single source of truth for Atlassian credentials and doesn't carry compatibility shims.

If you have a stale record from a previous version:

- `clm integration list` will mark the row `<type> (unknown)` in yellow.
- `clm integration show <name>` and `clm integration credentials <name>` exit non-zero with a remediation message.
- `clm agent configure` emits a `WARNING: integration '<name>' has unknown type '<type>' — skipping` and continues without wiring MCP for that record.

To recover:

```bash
clm integration remove old-jira
clm integration remove old-confluence

clm integration add work-atlassian --type atlassian
# Re-enter the URL/email/token; the API token from the old jira/confluence
# entry works as-is — Atlassian doesn't issue separate tokens per service.

clm agent integration add my-hermes work-atlassian
clm agent configure my-hermes
```

---

## Required Atlassian permissions

The integration uses whatever Atlassian permissions are granted to the account whose API token is registered. There is no separate scope layer. Minimum recommended grants:

| Capability | Atlassian permission |
|------------|----------------------|
| Read issues | **Browse Projects** |
| Create issues | **Create Issues** |
| Edit / transition issues | **Edit Issues** + **Transition Issues** |
| Add comments | **Add Comments** |
| Read Confluence pages | **View** on the target space |
| Create / edit Confluence pages | **Add / Delete** on the target space |

For least-privilege deployments, create a dedicated Atlassian service account, restrict its project / space memberships, then generate the API token from that account.

---

## Multiple integrations on one agent

You can attach more than one Atlassian integration to the same agent — e.g. a work tenant and a personal tenant. Each integration becomes its own MCP server entry, with isolated credentials:

```bash
clm integration add work-atlassian     --type atlassian   # company.atlassian.net
clm integration add personal-atlassian --type atlassian   # me.atlassian.net

clm agent integration add my-hermes work-atlassian
clm agent integration add my-hermes personal-atlassian
clm agent configure my-hermes
```

Hermes launches two `uvx mcp-atlassian` subprocesses; tools are namespaced as `mcp_work_atlassian_jira_search`, `mcp_personal_atlassian_confluence_get_page`, etc.

---

## Headless guarantees

| Concern | Resolution |
|---------|-----------|
| OAuth needs browser | Not used. API token only. |
| Token refresh | Not needed. Atlassian API tokens are long-lived (until manually revoked). |
| MCP server startup prompts | `uvx --from mcp-atlassian==<version> mcp-atlassian` runs non-interactively. |
| Package install during reconfigure | `pip install --user uv` and `uv tool install --force mcp-atlassian` are both non-interactive and version-pinned. |

---

## Troubleshooting

<details>
<summary><strong>Hermes restart succeeds but Jira / Confluence tools don't appear</strong></summary>

1. SSH to the agent host and confirm `mcp-atlassian` is installed at the pinned version under the agent user:

   ```bash
   sudo -u my-hermes /home/my-hermes/.local/bin/uv tool list
   ```

   You should see `mcp-atlassian v<pinned-version>`. If not, re-run `clm agent configure <agent-name>` — the configure playbook installs the package with `--force`.

2. Inspect the rendered MCP block (the file is `mode: 0600` and owned by the agent user):

   ```bash
   sudo -u my-hermes cat /home/my-hermes/.hermes/config.yaml
   ```

   Verify the `mcp_servers.<integration-name>:` entry exists and `JIRA_URL` / `CONFLUENCE_URL` are populated. If `JIRA_URL` is empty, the credential is missing from `~/.config/clawrium/secrets.json` — re-run `clm integration credentials <name> --update`.

3. Check hermes's logs for MCP startup errors:

   ```bash
   sudo journalctl -u hermes-my-hermes.service -n 200 --no-pager | grep -i mcp
   ```

</details>

<details>
<summary><strong>`401 Unauthorized` from Atlassian</strong></summary>

1. Re-test the token directly against Atlassian:

   ```bash
   curl -s -u "$ATLASSIAN_EMAIL:$ATLASSIAN_API_TOKEN" \
        "$ATLASSIAN_URL/rest/api/3/myself" | jq .
   ```

   Expected: your account profile. Anything else (`401`, HTML login page) means the token / email / URL trio is wrong.

2. If the curl succeeds but hermes still gets `401`, the rendered token may have been truncated by a stray shell character. Re-add the integration: `clm integration remove <name>` then `clm integration add <name> --type atlassian` and paste the token at the prompt (no quotes, no whitespace).

</details>

<details>
<summary><strong>Confluence works but Jira doesn't (or vice versa)</strong></summary>

Both services share the same token, but separate **permissions** on the Atlassian side. Open Atlassian → Site Administration and confirm the account whose token you used has the relevant Jira / Confluence product access enabled and is a member of the projects / spaces you're trying to reach.

</details>

<details>
<summary><strong>"unknown type 'jira' / 'confluence'" warning during configure</strong></summary>

You have a stale integration record from before [#348](https://github.com/ric03uec/clawrium/pull/351). See [Migrating from the old `jira` / `confluence` types](#migrating-from-the-old-jira--confluence-types) above.

</details>

<details>
<summary><strong>`uv tool install` fails on configure</strong></summary>

The Atlassian-MCP install path is conditional on at least one Atlassian integration being assigned. If you see `uv: command not found` on a fresh agent:

1. Confirm the agent user has Python 3.11+ available (uv installs as a pip package under the agent user).
2. Inspect the configure playbook's stat assertion for `~/.local/bin/uv` — if `pip install --user uv` succeeded but the binary isn't at that path, the agent host may have a non-standard home directory layout.

Re-run `clm agent configure <agent-name>`; the install task is idempotent.

</details>

---

## Out of scope

- **Atlassian Server / Data Center** — different URL layout and auth (PAT). Roadmap item.
- **OAuth 2.0** — requires browser-based approval; fundamentally incompatible with headless remote agents.
- **Tool subsetting beyond `*_FILTER` env vars** — the `mcp-atlassian` server exposes ≈72 tools; the `JIRA_PROJECTS_FILTER` / `CONFLUENCE_SPACES_FILTER` env vars are the only built-in narrowing knobs. Per-tool enable/disable is a future iteration.
- **HTTP / SSE transport for `mcp-atlassian`** — clm uses stdio because hermes manages the subprocess lifecycle directly; HTTP transport is unnecessary for the single-agent-per-process model.

---

## Related

- [Hermes Agent Support](../hermes.md) — full hermes feature matrix
- [OpenClaw Agent Support](../openclaw.md) — for context on env-var-based integrations
- [`clm integration` CLI reference](../../reference/cli/integration.md) — full command reference
- [PR #351](https://github.com/ric03uec/clawrium/pull/351) — the implementing PR for context / commit history

[Back to Integrations](index.md)
