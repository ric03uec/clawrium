# GitHub

**Status:** ✅ Supported on Hermes, ZeroClaw, OpenClaw, and Ethos (#419, #422, #649).

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

The standard workflow is attach + sync:

```bash
clawctl agent integration attach my-agent my-github
clawctl agent sync my-agent
```

`sync` handles everything: renders the token into the agent's environment, runs `gh auth login --with-token` and `gh auth setup-git` on the host as the agent user, and writes `~/.gitconfig` for `git`-type integrations. No manual `ssh xclm@host -- 'sudo -u <agent> gh auth setup-git'` steps are needed.

> **Note:** `gh` (GitHub CLI) is installed as part of agent host setup and is a **hard requirement** — if the binary is missing on the host, sync will raise a `CanonicalSyncError` rather than silently skipping.

The key difference from classic tokens: fine-grained tokens let you scope to specific repos and grant minimal permissions per resource type.

---

## How clawctl Wires GitHub to Each Agent Type

All agent types now use the same sync-path wiring hook (`_setup_github_integration` in `core/lifecycle_canonical.py`). On every `clawctl agent sync <name>`:

1. **`git`-type integrations first**: `~/.gitconfig` `[user]` / `[init]` / `[pull]` / `[core]` sections are rendered via `sudo -u <agent> tee`.
2. **`github`-type integrations second**: `gh auth login --with-token` (token via stdin — never in argv) followed by `gh auth setup-git` which appends the `[credential]` helper block to `~/.gitconfig`.

The ordering matters: `gitconfig` render must precede `setup-git` because `setup-git` appends `[credential]` to the file. If no `git`/`github` integration is attached, the hook is a fast no-op (zero SSH round-trips).

### Hermes — env vars in `~/.hermes/.env`

Hermes natively reads `GITHUB_TOKEN` from its environment. After `clawctl agent integration attach` + `sync`, the following is rendered into `~/.hermes/.env` (mode 0600):

```env
GITHUB_TOKEN_WORK_GH='ghp_...'
GITHUB_TOKEN='ghp_...'      # tracks the alphabetically-last github integration
```

In addition to the env var, `gh auth login --with-token` and `gh auth setup-git` run as the agent user so `git push` / `git pull` over HTTPS from the agent shell work without manual setup.

### ZeroClaw — two layers, both required

ZeroClaw's shell tool **auto-strips** any env var matching `_TOKEN` / `_SECRET` / `_PASSWORD` / `API_KEY` patterns unless explicitly listed in `[autonomy] shell_env_passthrough`. Source: zeroclaw v0.7.5 `docs/book/src/security/sandboxing.md` and `security/autonomy.md`. So GitHub credentials need to land in **two** places:

| Layer | Where | What it enables |
|---|---|---|
| 1. systemd `Environment=` drop-in | `/etc/systemd/system/zeroclaw-<name>.service.d/10-zeroclaw-env.conf` | The daemon process and all child processes (including the shell tool) inherit `GITHUB_TOKEN` from systemd. |
| 2. `[autonomy] shell_env_passthrough` | `~/.zeroclaw/config.toml` | The agent's sandboxed shell tool sees the token. Without this, layer 1 alone is invisible to `gh`/`git push` inside chat. |

Both layers are populated automatically by `clawctl agent sync <zeroclaw>` after `clawctl agent integration attach`. The drop-in template is `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-env.conf.j2`; the autonomy block lives in `config.toml.j2`. Re-running `clawctl agent sync` re-renders both atomically and triggers a single service restart (daemon_reload + restart, handled by the configure playbook's restart handler).

The sync path also runs `gh auth login --with-token` and `gh auth setup-git` as the agent user, so `git push` works from the shell tool without manual setup.

### OpenClaw & Ethos — sync-path wiring only

OpenClaw and Ethos agents do not use the systemd env-var or shell_env_passthrough layers. Instead, `clawctl agent sync` runs `gh auth login --with-token` and `gh auth setup-git` directly on the host as the agent user, which populates `~/.config/gh/hosts.yml` and the `[credential]` block in `~/.gitconfig`. This is sufficient for `git push` / `git pull` over HTTPS from the agent shell — no manual `ssh xclm@host -- 'sudo -u <agent> gh auth setup-git'` steps are required.

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
# Rendered in /etc/systemd/system/zeroclaw-<name>.service.d/10-zeroclaw-env.conf:
[Service]
Environment=GITHUB_TOKEN_WORK_GH="ghp_..."
Environment=GITHUB_TOKEN="ghp_..."
```

### Verifying the wiring (ZeroClaw)

```bash
# On the agent host:
systemctl show -p Environment zeroclaw-<name>      # should list GITHUB_TOKEN
grep -E '^shell_env_passthrough' ~/.zeroclaw/config.toml
# From clawctl:
clawctl agent chat <name>
> Run: echo $GITHUB_TOKEN          # should print the token
> Run: gh auth status              # should print "Logged in to github.com" if gh is installed
```

---

## Multi-Account Support

Both hermes and zeroclaw support multiple github integrations on a single agent:

```bash
clawctl integration registry create work-gh --type github
clawctl integration registry create personal-gh --type github
clawctl agent integration attach my-agent work-gh
clawctl agent integration attach my-agent personal-gh
clawctl agent sync my-agent
```

The agent then has `GITHUB_TOKEN_WORK_GH` and `GITHUB_TOKEN_PERSONAL_GH` available, plus a bare `GITHUB_TOKEN` set to the alphabetically-last integration (deterministic — uses Jinja's `dictsort`).

---

## Git Integration (`git` type)

A `git`-type integration (distinct from `github`) configures `~/.gitconfig` with `[user]`, `[init]`, `[pull]`, and `[core]` sections for the agent user. This enables `git push` / `git pull` over HTTPS when combined with `gh auth setup-git` (which `github` integrations handle). On its own, it sets up author identity, default branch naming, and fetch strategies:

```bash
clawctl integration registry create my-git --type git
clawctl agent integration attach my-agent my-git
clawctl agent sync my-agent
```

The rendered `~/.gitconfig` includes:
- `[user]` — name and email from the integration record
- `[init]` — `defaultBranch` for `git init`
- `[pull]` — `rebase = true` for rebase-on-pull behavior
- `[core]` — `editor` (shell-metachar sanitized, `vim` by default)

Both `github` and `git` integrations can be attached to the same agent — `sync` processes `git` first, then `github`, so the credential helper lands after the other sections.

---

## Migrating from Manual GitHub Setup

Before v26.7.2, `git push` from an agent shell required manual `gh auth setup-git` via SSH. If you have existing agents with this workaround:

1. Attach the integration: `clawctl agent integration attach <name> <gh-integration>`
2. Sync: `clawctl agent sync <name>`
3. Verify: `clawctl agent chat <name>` → `gh auth status` should show "Logged in to github.com"

The next `clawctl agent sync` will wire everything automatically. The manual `~/.gitconfig` entries `gh auth setup-git` previously wrote will be preserved (the sync hook is idempotent — it only appends `[credential]` if not already present).

---

[Back to Integrations](index.md)
