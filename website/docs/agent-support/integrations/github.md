# GitHub

**Status:** ✅ Supported on Hermes and ZeroClaw (#419, #422). 📋 Planned for OpenClaw.

GitHub integration allows agents to clone repos, open pull requests, comment on issues, and search code from inside the agent's shell tool. The credential is a Personal Access Token (classic) or a fine-grained token — see [Create Fine-Grained Token for One Repo](#create-fine-grained-token-for-one-repo) below.

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

## Create Fine-Grained Token for One Repo

1. Go to GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - Direct link: https://github.com/settings/tokens?type=beta
2. Click **Generate new token**
3. Configure:
   - Token name: Descriptive name (for example, `clawrium-myrepo`)
   - Expiration: Set as needed
   - Repository access: Select **Only select repositories** and pick your single repo
4. Set permissions based on what you need:

| Use Case | Permission | Level |
|----------|------------|-------|
| Read code | Contents | Read |
| Push code | Contents | Read & Write |
| Read issues | Issues | Read |
| Create/comment issues | Issues | Read & Write |
| Read PRs | Pull requests | Read |
| Create/review PRs | Pull requests | Read & Write |

5. Click **Generate token** and copy it immediately.

## Use with Clawrium

When configuring your agent:

```bash
clm agent configure my-agent
# Enter the fine-grained token when prompted for GitHub credentials
```

The key difference from classic tokens: fine-grained tokens let you scope to specific repos and grant minimal permissions per resource type.

---

## How clm Wires GitHub to Each Agent Type

### Hermes — env vars in `~/.hermes/.env`

Hermes natively reads `GITHUB_TOKEN` from its environment. `clm agent integration add <hermes> <gh-name>` followed by `clm agent sync <hermes>` renders the following into `~/.hermes/.env` (mode 0600):

```env
GITHUB_TOKEN_WORK_GH='ghp_...'
GITHUB_TOKEN='ghp_...'      # tracks the alphabetically-last github integration
```

`clm` then runs `gh auth login --with-token` as the agent user (soft dep — skipped if `gh` is not on the host). See [hermes/playbooks/configure.yaml](https://github.com/ric03uec/clawrium/blob/main/src/clawrium/platform/registry/hermes/playbooks/configure.yaml) lines 118–145.

### ZeroClaw — two layers, both required

ZeroClaw's shell tool **auto-strips** any env var matching `_TOKEN` / `_SECRET` / `_PASSWORD` / `API_KEY` patterns unless explicitly listed in `[autonomy] shell_env_passthrough`. Source: zeroclaw v0.7.5 `docs/book/src/security/sandboxing.md` and `security/autonomy.md`. So GitHub credentials need to land in **two** places:

| Layer | Where | What it enables |
|---|---|---|
| 1. systemd `Environment=` drop-in | `/etc/systemd/system/zeroclaw-<name>.service.d/10-clm-env.conf` | The daemon process and all child processes (including the shell tool) inherit `GITHUB_TOKEN` from systemd. |
| 2. `[autonomy] shell_env_passthrough` | `~/.zeroclaw/config.toml` | The agent's sandboxed shell tool sees the token. Without this, layer 1 alone is invisible to `gh`/`git push` inside chat. |

Both layers are populated automatically by `clm agent sync <zeroclaw>` after `clm agent integration add`. The drop-in template is `src/clawrium/platform/registry/zeroclaw/templates/clm-env.conf.j2`; the autonomy block lives in `config.toml.j2`. Re-running `clm agent sync` re-renders both atomically and triggers a single service restart (daemon_reload + restart, handled by the configure playbook's restart handler).

Like hermes, a `gh auth login --with-token` is run as the agent user when `gh` is present on the host — convenience only; the env-var path works without it.

```toml
# Rendered in ~/.zeroclaw/config.toml when github integrations are assigned:
[autonomy]
level = "supervised"
approval_timeout_secs = 300
workspace_only = true
allowed_commands = ["git", "cargo", "grep", "find", "ls", "cat"]
forbidden_commands = ["shutdown", "reboot", "mkfs"]
forbidden_paths = ["/etc", "/sys", "/boot", "~/.ssh", "~/.aws"]
shell_env_passthrough = ["PATH", "HOME", "USER", "LANG", "GITHUB_TOKEN_WORK_GH", "GITHUB_TOKEN"]
```

```ini
# Rendered in /etc/systemd/system/zeroclaw-<name>.service.d/10-clm-env.conf:
[Service]
Environment=GITHUB_TOKEN_WORK_GH="ghp_..."
Environment=GITHUB_TOKEN="ghp_..."
```

### Verifying the wiring (ZeroClaw)

```bash
# On the agent host:
systemctl show -p Environment zeroclaw-<name>      # should list GITHUB_TOKEN
grep -E '^shell_env_passthrough' ~/.zeroclaw/config.toml
# From clm:
clm chat <name>
> Run: echo $GITHUB_TOKEN          # should print the token
> Run: gh auth status              # should print "Logged in to github.com" if gh is installed
```

---

## Multi-Account Support

Both hermes and zeroclaw support multiple github integrations on a single agent:

```bash
clm integration add work-gh --type github
clm integration add personal-gh --type github
clm agent integration add my-agent work-gh
clm agent integration add my-agent personal-gh
clm agent sync my-agent
```

The agent then has `GITHUB_TOKEN_WORK_GH` and `GITHUB_TOKEN_PERSONAL_GH` available, plus a bare `GITHUB_TOKEN` set to the alphabetically-last integration (deterministic — uses Jinja's `dictsort`).

---

## OpenClaw (Not Yet Supported)

OpenClaw does not yet consume GitHub credentials. Use a hermes or zeroclaw agent for GitHub workflows, or follow the workaround below for OpenClaw-only fleets.

## Workaround for OpenClaw

1. **CLI Tools:** Manually `gh auth login` on the OpenClaw host outside of clm.
2. **API via curl:** Make direct API calls inside chat using a hard-coded token (not recommended for production).

---

[Back to Integrations](index.md)
