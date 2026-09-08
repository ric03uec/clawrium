# Issue #982 — Plan

**Issue**: https://github.com/ric03uec/clawrium/issues/982
**Title**: zeroclaw renderer: emit `[heartbeat].agent = "<alias>"` so heartbeat worker can start
**Type**: bug (renderer — missing key, not a charset issue)
**Scope**: single PR, non-breaking

---

## Root cause

`src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2` at ~L411 renders the `[heartbeat]` block with `enabled = true` and all worker-tuning fields, but does **not** emit the `agent = "<alias>"` binding that zeroclaw 0.8.2's heartbeat worker requires. The worker exits on startup with:

```
heartbeat worker requires `[heartbeat] agent = "<alias>"` naming a configured agent
```

and enters a permanent restart loop.

Confirmed on `wolf-i` / `clawrium-d01` post-#980 (2026-09-08): all three previously-hyphenated alias sites are now `clawrium_d01` (underscored) and healthy, but `daemon_state.json.components.heartbeat.status == "error"` with the message above.

## Blast radius

`enabled = true` is the template default → **every clawctl-managed zeroclaw agent** exhibits this failure, regardless of alias charset. Hyphenated agents were already broken via #980; underscored agents fail via this bug. Discovered while verifying #980.

---

## Code changes

### 1. `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2` (~L411)

Before:
```jinja
[heartbeat]
adaptive = false
deadman_timeout_minutes = 0
enabled = true
interval_minutes = 30
...
```

After:
```jinja
[heartbeat]
agent = "{{ agent_alias }}"
adaptive = false
deadman_timeout_minutes = 0
enabled = true
interval_minutes = 30
...
```

### 2. `src/clawrium/core/render.py` — NO CHANGE REQUIRED

`agent_alias` is already threaded into the Jinja render context by #980. Reuse — do not re-derive.

### 3. New renderer test

Extend the existing `test_render_zeroclaw*` module (same file that #980 added tests to). Assert:

- For `agent_name="clawrium-d01"` (hyphenated → sanitized), rendered TOML contains a line matching `agent = "clawrium_d01"` inside the `[heartbeat]` section.
- For `agent_name="already_ok"` (already valid), rendered TOML contains `agent = "already_ok"` inside `[heartbeat]`.
- Guard against duplicate `agent =` keys elsewhere in `[heartbeat]`.

---

## Migration

No operator action required. Any lifecycle op that re-renders — `clawctl agent configure|sync|restart` — picks up the new binding and the heartbeat worker starts cleanly on the next daemon boot. `daemon_state.json.components.heartbeat.status` flips `error → ok`.

Document under `docs/releases/<next-version>/README.md` as a bug fix. **NOT** a BREAKING change — the missing key was silently keeping an already-nonfunctional worker nonfunctional; adding it strictly restores intended behavior.

---

## CHANGELOG entries (root `CHANGELOG.md`, `## [Unreleased]`)

```markdown
### Fixed

- zeroclaw renderer: emit `[heartbeat].agent = "<alias>"` so the
  heartbeat worker can bind to the agent alias and start. Without
  this, every zeroclaw agent's heartbeat worker was error-looping
  with `restart_count` climbing indefinitely; no operator-visible
  symptoms until you inspected `~/.zeroclaw/state/daemon_state.json`.
  Fixes #982.
```

---

## Verification

### Local (child agent)

1. `make lint`
2. `make test` (must include the new renderer test)
3. Grep the rendered fixture to confirm `agent = "…"` appears exactly once under `[heartbeat]`.

### Real-host UAT on `wolf-i` / `clawrium-d01` — REQUIRED before PR

Per memory `no PR without real-host UAT`.

1. `uv tool install .` from the worktree to install the branch build of `clawctl`.
2. `clawctl agent configure clawrium-d01` (re-renders, re-pairs, restarts daemon).
3. Verify:
   - `~/.zeroclaw/config.toml` — `[heartbeat]` section now includes `agent = "clawrium_d01"` as the first non-header line.
   - After ~60 seconds (heartbeat worker startup): `jq '.components.heartbeat' ~/.zeroclaw/state/daemon_state.json` shows `status = "ok"`, `restart_count` low (single digits), `last_ok` a recent timestamp, `last_error` empty or historical.
   - Chat, discord channel, and dashboard operations still work (regression check for the alias fix from #980).
4. Capture the full command transcript + before/after `daemon_state.json.components.heartbeat` snapshots for the PR Testing section.

---

## PR

- **Branch**: `issue-982-zeroclaw-heartbeat-agent` (created)
- **Base**: `main`
- **Body**: `.github/PULL_REQUEST_TEMPLATE.md` verbatim (Summary / Changes / Testing / ATX Review) — per memory `PR template required`.
- **Callouts**: required — see itx-execute skill. Likely `_None._` for this scope.
- **ATX**: MCP → CLI → skip w/ callout. Iterate to Rating > 3/5 with no blockers, or hit 3-iteration ceiling and open PR anyway with `[ITX-STUCK]`.
- **Squash-merge** on approval.

---

## Out of scope

- Verifying heartbeat effectiveness beyond "worker starts cleanly" (deadman timeouts, adaptive interval semantics) — those are upstream zeroclaw behavior, not renderer concerns.
- The leftover `~/.zeroclaw/agents/default/` and `~/.zeroclaw/agents/test/` on wolf-i — unrelated.
- Any other unrendered zeroclaw config sub-tables — file separately if found.
