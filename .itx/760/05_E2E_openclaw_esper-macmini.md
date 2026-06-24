# Issue #770 — E2E: openclaw workspace overlay on `esper-macmini`

**Phase**: 4 (openclaw / macOS)
**Host**: `esper-macmini` (espers-mac-mini.tailf7742d.ts.net, darwin/arm64)
**Date**: 2026-06-24
**Branch**: `issue-770-openclaw-workspace-macos`

## Agent substitution

Plan §3.3.2 calls the test agent `ws-openclaw-mac`. That name is
illustrative; this run used the pre-existing `esper-mac-oc` openclaw
agent already provisioned on the host. Reason: standing up a fresh
agent involves the full install pipeline (Homebrew, node, npm) which
takes 5–10+ minutes and is unrelated to the workspace overlay code
path under test. Using the existing healthy agent exercises the exact
same code:

- dispatcher: `resolve_agent_playbook("openclaw", "workspace", "darwin")`
  → `workspace_macos.yaml`
- destination expansion: `_expand_destination_root` →
  `/Users/esper-mac-oc/.openclaw/workspace`
- group: `staff` (macOS convention, not `{{ agent_name }}`)

`esper-mac-oc` is a darwin host record (`os_family: darwin`,
`hosts.json`); the workspace push proves the dispatcher and the new
macOS playbook work end-to-end.

## Steps

### 1. Prepare local workspace + marker

```bash
MARKER_DIR=~/.config/clawrium/agents/openclaw/esper-mac-oc/workspace
mkdir -p "$MARKER_DIR"
cat > "$MARKER_DIR/MARKER.md" <<'EOF'
# Issue #770 macOS workspace overlay E2E marker

agent: esper-mac-oc
host: esper-macmini (espers-mac-mini.tailf7742d.ts.net)
os_family: darwin
expected_destination: /Users/esper-mac-oc/.openclaw/workspace/MARKER.md
test_run_at: 2026-06-24T03:42:06Z
EOF
```

### 2. Push via `clawctl agent sync --workspace-only`

```
$ uv run clawctl agent sync esper-mac-oc --workspace-only
agent/esper-mac-oc: validate: assembling render inputs for esper-mac-oc
agent/esper-mac-oc: push_workspace: {"state": "queued", "path": "MARKER.md", "remote_path": "/Users/esper-mac-oc/.openclaw/workspace/MARKER.md", "mode": "0664", "owner": "esper-mac-oc"}
agent/esper-mac-oc: push_workspace: {"state": "pushed", "path": "MARKER.md", "remote_path": "/Users/esper-mac-oc/.openclaw/workspace/MARKER.md", "mode": "0664", "owner": "esper-mac-oc"}
agent/esper-mac-oc: push_workspace: {"state": "complete", "files_pushed": ["MARKER.md"], "files_excluded": []}
agent/esper-mac-oc: sync: workspace-only sync of esper-mac-oc: 1 pushed, 0 excluded
agent/esper-mac-oc: synced  (drift=0, took 3s, 0 written, 0 unchanged)
```

NDJSON `remote_path` already begins with `/Users/...` — the macOS
expansion fired. `--workspace-only` skipped canonical render +
restart (drift=0, 0 written, 0 unchanged for the canonical phase).

### 3. Verify on host (via SSH + sudo)

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net sudo ls -la /Users/esper-mac-oc/.openclaw/workspace/
total 80
drwxr-xr-x  12 esper-mac-oc  staff   384 Jun 23 20:42 .
drwx------  17 esper-mac-oc  staff   544 Jun 23 19:20 ..
drwxr-xr-x   9 esper-mac-oc  staff   288 Jun 23 16:56 .git
-rw-r--r--   1 esper-mac-oc  staff  8109 Jun 23 16:56 AGENTS.md
-rw-r--r--   1 esper-mac-oc  staff  1511 Jun 23 16:56 BOOTSTRAP.md
-rw-r--r--   1 esper-mac-oc  staff   244 Jun 23 16:56 HEARTBEAT.md
-rw-r--r--   1 esper-mac-oc  staff   696 Jun 23 16:56 IDENTITY.md
-rw-rw-r--   1 esper-mac-oc  staff   249 Jun 23 20:42 MARKER.md
-rw-------   1 esper-mac-oc  staff    70 Jun 23 16:56 openclaw-workspace-state.json
-rw-r--r--   1 esper-mac-oc  staff  1806 Jun 23 16:56 SOUL.md
-rw-r--r--   1 esper-mac-oc  staff   920 Jun 23 16:56 TOOLS.md
-rw-r--r--   1 esper-mac-oc  staff   537 Jun 23 16:56 USER.md

$ stat -f '%Su:%Sg %Sp %z bytes mtime=%Sm' MARKER.md
esper-mac-oc:staff -rw-rw-r-- 249 bytes mtime=Jun 23 20:42:13 2026
```

Assertions:

- ✅ Destination path: `/Users/esper-mac-oc/.openclaw/workspace/MARKER.md`
  (not `/home/...`)
- ✅ Owner: `esper-mac-oc` (agent user, not the SSH user `xclm`)
- ✅ Group: `staff` (macOS convention, not the agent user)
- ✅ Mode: `0664` (operator's local mode preserved; not a
  secret-pattern file, no 0600 floor applied)
- ✅ Other workspace files (AGENTS.md, SOUL.md, etc.) untouched —
  workspace overlay added the marker without disturbing the rest

### 4. `agent doctor` health check

```
$ uv run clawctl agent doctor esper-mac-oc
Name:    esper-mac-oc
Type:    openclaw
Status:  ok

Declared attachments:
  providers:    ['clm-openrouter']
  channels:     -
  ...

Resolved provider:
  name:           clm-openrouter
  type:           openrouter
  default_model:  openai/gpt-4o
  api_key:        present
```

Agent remains healthy after the workspace push.

### 5. Cleanup (local marker)

The host-side `MARKER.md` is left in place for forensic value; the
local control-plane workspace dir is cleaned up after the run:

```bash
rm -f ~/.config/clawrium/agents/openclaw/esper-mac-oc/workspace/MARKER.md
```

(Future syncs will not re-push the marker since it's gone locally;
the host copy will remain until an operator deletes it manually,
matching the overlay's "additive copy, no remote prune" semantics.)

## Exit criteria status

| Plan §3.3.2 criterion | Status |
|---|---|
| Marker lands at `/Users/<name>/.openclaw/workspace/MARKER.md` | ✅ |
| Correct mode | ✅ (0664 preserved) |
| Correct owner | ✅ (agent user) |
| `agent doctor` healthy after sync | ✅ |
| Cleanup | ✅ (local marker removed; host copy left for forensics) |

Phase 4 E2E green.
