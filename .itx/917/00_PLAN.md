# Issue #917 — sync registry lookup uses instance name, not type

## Root cause

`src/clawrium/core/lifecycle_canonical.py:sync_agent_canonical` unpacks
`get_agent_by_name()`'s return tuple `(host_record, agent_type, agent_record)`
into a locally-scoped variable misleadingly named `agent_key` (line 1795).
That local actually holds the agent *type* (e.g. `"zeroclaw"`), not the
instance name.

Downstream at line 2417, the same local is passed to
`onboarding.transition_state(hostname, agent_key, _OS.READY)`, which
expects the instance name (e.g. `"e2e-zeroclaw"`) as its second
positional argument. The registry lookup inside `transition_state`
therefore fails, raising `AgentNotFoundError`, which is caught and
surfaced as:

```
warning: registry record missing for zeroclaw after sync:
    Agent 'zeroclaw' not found on host <hostname>
```

The warning is spurious on every zeroclaw sync where the instance name
differs from the type — which is the common operator setup.

## Fix

1. Rename the unpacked local from `agent_key` → `agent_type` so its
   name matches what `get_agent_by_name` actually returns.
2. Audit the whole function (roughly lines 1740–2450) for any other
   `agent_key` reference. Classify each occurrence:
   - JSON payload keys (event dicts at lines 1986 and 2351): unchanged
     — those are literal string keys `"agent_key"`, not the local
     variable, and the payload value is already `agent_name` (correct).
   - Transition block (lines 2417, 2421, 2427): all three want the
     agent *instance* name. Route to `agent_name` (already a function
     parameter of `sync_agent_canonical`, declared at line 1742).
3. Verify the newly-unused `agent_type` local does not trigger
   lint failures (ruff F841). If it does, prefix with `_` or drop the
   binding.

## Definition of Done

- `clawctl agent sync <existing-zeroclaw>` no longer prints
  `registry record missing for <type>` warning.
- `_transition` receives the instance name, verified by unit test.
- Unit tests added:
  - `test_sync_zeroclaw_transition_uses_instance_name` — stubs
    `transition_state`, asserts it was called with the instance name.
  - `test_sync_zeroclaw_no_registry_missing_warning` — captures the
    `emit` stream, asserts no `registry record missing` line appears.
- `make lint` passes.
- `make test` passes (263 tests in `test_lifecycle_canonical.py`).
- `CHANGELOG.md` updated under `## [Unreleased] → ### Fixed`.
- UAT on wolf-i (a real zeroclaw host) confirms the warning is gone
  and `clawctl agent get` still shows the agent post-sync.
