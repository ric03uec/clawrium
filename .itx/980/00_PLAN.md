# Issue #980 — Plan

**Issue**: https://github.com/ric03uec/clawrium/issues/980
**Title**: zeroclaw renderer: sanitize alias for `[agents.<alias>]` and `[providers.models.<type>.<alias>]` (mirror #974 discord fix)
**Type**: bug (renderer / BREAKING for hyphenated agent names)
**Scope**: single PR

---

## Root cause

Zeroclaw 0.8.2 schema v3 requires TOML sub-table alias keys to match `[a-z0-9_]+`. `src/clawrium/core/render.py:1570` sanitizes only the discord alias (fix from #974); the sibling `[agents.<alias>]` and `[providers.models.<type>.<alias>]` headers in `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2` are rendered with the raw `agent_name`. The TOML boot-loader is lenient, so the daemon starts, but the dashboard's alias resolver is strict and returns `[path_not_found]` on any agent-scoped operation.

Real-world manifestation on `wolf-i` / `clawrium-d01`:

```
[path_not_found] could not select agents alias `clawrium-d01`:
alias 'clawrium-d01' contains invalid character '-';
only lowercase letters, digits, and single underscores are allowed
```

Side effect observed: heartbeat worker error-loops with `heartbeat worker requires [heartbeat] agent = "<alias>" naming a configured agent` (7188 restart_count on wolf-i). Same root cause; resolves as a side benefit.

---

## Code changes

### 1. `src/clawrium/core/render.py` (~L1570 and `_render_zeroclaw_config_template` signature)

Before:
```python
discord_alias = _sanitize_zeroclaw_alias(inputs.agent_name)
toml_body = _render_zeroclaw_config_template(
    agent_name=inputs.agent_name,
    ...
    discord_alias=discord_alias,
    ...
)
```

After:
```python
agent_alias = _sanitize_zeroclaw_alias(inputs.agent_name)
discord_alias = agent_alias  # kept named for intent at each call site
toml_body = _render_zeroclaw_config_template(
    agent_name=inputs.agent_name,   # unchanged — still needed for on-host paths
    agent_alias=agent_alias,        # NEW — for in-TOML sub-table keys
    ...
    discord_alias=discord_alias,
    ...
)
```

Add `agent_alias: str` parameter to `_render_zeroclaw_config_template` signature (~L1720) and thread it into the Jinja render context.

### 2. `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`

Three substitutions — swap `{{ agent_name }}` → `{{ agent_alias }}`:

- L39: `[providers.models.litellm.{{ agent_name }}]`
- L234: `[agents.{{ agent_name }}]`
- L235: `model_provider = "litellm.{{ agent_name }}"`

Everything else stays `{{ agent_name }}` — `home_root`, systemd unit references, paths. `[channels.discord.{{ discord_alias }}]` and its channel-list reference are already correct (#974).

### 3. New renderer test

Feed `render_zeroclaw` an agent named `clawrium-d01`. Assert:

- All 4 alias sites (`[agents.…]`, `[providers.models.litellm.…]`, the `model_provider = "…"` string, `[channels.discord.…]`) contain `clawrium_d01` (underscored).
- Any path/unit-name field (e.g. `home_root`, workspace paths) still contains `clawrium-d01`.

Place alongside existing `render_zeroclaw` tests (grep `test_render_zeroclaw` or similar to find the neighbor file).

---

## Migration (BREAKING — manual, documented)

**Why manual, not automated**: the per-alias on-host state directory at `~/.zeroclaw/agents/<name>/` is created by the zeroclaw daemon under whatever alias key is in `config.toml`. Renaming the alias without moving the directory causes the daemon to initialize a fresh empty per-alias state (losing whatever the daemon persists there). This is safer to do behind an operator's eyes than to embed in `clawctl agent configure`.

Shared SQLite (`data/memory/brain.db`, `data/sessions/sessions.db`) is not alias-keyed → session history and memory carry over untouched regardless.

### Documented procedure (goes in `docs/releases/<next-version>/README.md`)

```bash
# Check whether you're affected:
clawctl agent get | awk '$2=="zeroclaw" && $1 ~ /[-A-Z]/ {print $1}'

# For each affected agent <NAME>:
NEW_ALIAS=$(echo "<NAME>" | tr 'A-Z-' 'a-z_')

# 1. Stop the daemon
clawctl agent stop <NAME>

# 2. Rename the per-alias state directory on the host
clawctl agent shell <NAME> -- "mv ~/.zeroclaw/agents/<NAME> ~/.zeroclaw/agents/${NEW_ALIAS}"

# 3. Re-render config with the sanitized alias
clawctl agent configure <NAME>

# 4. Start the daemon
clawctl agent start <NAME>

# 5. Verify all four alias sites are underscored
clawctl agent shell <NAME> -- "grep -E '^\\[(agents|providers\\.models|channels\\.discord)\\.' ~/.zeroclaw/config.toml"
```

Notes for operators:
- `agent_name` in `clawctl` / `hosts.json` does NOT change — only the on-host TOML alias key and the per-alias state directory.
- Agents whose name is already `[a-z0-9_]+` need no action; running the procedure is a no-op but adds daemon churn.

---

## CHANGELOG entries (root `CHANGELOG.md`, under `## [Unreleased]`)

```markdown
### BREAKING

- **zeroclaw agents with hyphens or uppercase in their name require a
  one-time on-host state migration.** The renderer now sanitizes the
  in-TOML alias keys (`[agents.<alias>]`, `[providers.models.<type>.<alias>]`)
  to match zeroclaw 0.8.2's schema-v3 charset requirement (`[a-z0-9_]+`).
  Chat continued to work with the hyphenated aliases because the TOML
  loader was lenient, but the dashboard's alias resolver rejected them
  with `[path_not_found]`. See `docs/releases/<version>/README.md` for
  the exact migration steps. No automated migration — the per-alias
  state directory at `~/.zeroclaw/agents/<name>/` must be renamed
  manually on each affected host so session history and per-alias
  memory carry over. Agents whose name is already `[a-z0-9_]+` need no
  action.

### Fixed

- zeroclaw renderer: `[agents.<alias>]` and
  `[providers.models.<type>.<alias>]` are now sanitized the same way
  `[channels.discord.<alias>]` was in #974. Fixes #980.
```

---

## Verification

### Local (child agent)

1. `make lint`
2. `make test` (must include the new renderer test)
3. Grep to confirm no other template site still uses raw `{{ agent_name }}` for what should be an alias key.

### Real-host UAT on `wolf-i` / `clawrium-d01` — REQUIRED before PR

Per memory `no PR without real-host UAT`.

1. `uv tool install .` from the worktree on control machine to install the branch build of `clawctl`.
2. Run the Phase-2 migration procedure verbatim on `clawrium-d01`:
   - `clawctl agent stop clawrium-d01`
   - `clawctl agent shell clawrium-d01 -- "mv ~/.zeroclaw/agents/clawrium-d01 ~/.zeroclaw/agents/clawrium_d01"`
   - `clawctl agent configure clawrium-d01`
   - `clawctl agent start clawrium-d01`
3. Verify:
   - `~/.zeroclaw/config.toml` — all 4 alias sites underscored
   - `~/.zeroclaw/agents/clawrium_d01/` exists (renamed from `-`)
   - Dashboard operations on `clawrium-d01` no longer return `[path_not_found]`
   - `clawctl agent chat clawrium-d01` still works end-to-end
   - Discord channel still receives messages
   - `~/.zeroclaw/state/daemon_state.json` — `heartbeat.status` transitions `error` → `ok` (side benefit; call out in PR body)
4. Capture the full command transcript for the PR's Testing section.

---

## PR

- **Branch**: `issue-980-zeroclaw-alias-sanitize` (already created)
- **Base**: `main`
- **Body**: `.github/PULL_REQUEST_TEMPLATE.md` verbatim (Summary / Changes / Testing / ATX Review) — per memory `PR template required`.
- **Callouts**: required section — see itx-execute skill.
- **ATX**: run per AGENTS.md `<atx-review-requirements>` (MCP → CLI → skip w/ callout). Iterate until Rating > 3/5 with no blocking issues, or hit the 3-iteration ceiling and open PR anyway with `[ITX-STUCK]` marker.
- **Squash-merge** on approval.

---

## Out of scope (not this PR)

- The leftover `~/.zeroclaw/agents/default/` and `~/.zeroclaw/agents/test/` directories on `wolf-i` — unrelated to this fix; file separately if cleanup wanted.
- Automated alias migration inside `clawctl agent configure` — deliberately deferred; documented manual path is safer for this schema-charset change.
- Heartbeat worker `[heartbeat] agent = "<alias>"` config — resolves as a byproduct of this fix; no direct code change needed.
