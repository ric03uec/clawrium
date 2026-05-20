# Issue #437 — Plan

The full implementation plan is in the issue body (#437). This file logs the
execution against that plan. The acceptance criteria from #437 are the
contract; the file structure below is the execution trace.

## Implementation Outline

1. Extract pair handshake to reusable task file
   - New: `src/clawrium/platform/registry/zeroclaw/playbooks/tasks/pair.yaml`
   - Four tasks: request `/pair/code` → validate → POST `/pair` → validate
   - Sets cacheable fact `zeroclaw_gateway_token`

2. Refactor `configure.yaml`
   - Delete `Determine whether re-pairing is required` set_fact
   - Replace inlined pair handshake with `include_tasks: tasks/pair.yaml`
   - Remove all `zeroclaw_needs_pairing` / `force_repair` / `existing_gateway_token`
     references
   - Update success message (no more "existing token reused" branch)

3. Refactor `lifecycle.py`
   - Drop `existing_gateway_token` / `force_repair` block in `configure_agent`
   - Add zeroclaw branch in `restart_agent` that runs a new `restart.yaml`
     playbook, extracts the gateway token fact, and updates hosts.json atomically
   - Drop unconditional `restart_agent` call from `sync_agent`
   - Add `_emit_gateway_token_rotated` helper used at every write site that
     persists a new gateway.auth value

4. New playbook: `restart.yaml` for zeroclaw
   - `systemctl restart` → wait for `/health/providers` → `include_tasks: tasks/pair.yaml`

5. `cli/chat.py` transparent reconnect on 401
   - Catch `ChatAuthenticationError`, reload hosts.json, compare bearer
   - If different, reconnect once; if identical, surface the existing error

6. CLI: surface `gateway_token_rotated` events
   - Extend `_print_configure_warnings` (or sibling) to render the structured
     rotation event as a yellow notice

7. Tests
   - Remove tests pinned to `existing_gateway_token` / `force_repair`
   - Add post-condition tests: install / configure / sync / restart all leave
     `hosts.json.gateway.auth` equal to the daemon's enforced bearer
   - Add chat reconnect unit test

8. Docs
   - Update `AGENTS.md` with "Gateway token lifecycle" section
   - Remove stale ATX B3 comment block

## Prompt Log

### Execute

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-05-19T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 437
```

**Output**: Implementation of always-repair invariant for zeroclaw lifecycle.
