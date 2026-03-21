---
phase: quick
plan: 260321-iqu
subsystem: host-management
tags: [ssh, keys, bug-fix, cli]
dependency_graph:
  requires: [per-host-keys, host-init-command]
  provides: [key-id-field, stable-key-lookup]
  affects: [host-add, host-status, host-remove]
tech_stack:
  added: []
  patterns: [key-id-persistence, alias-priority]
key_files:
  created:
    - src/clawrium/core/names.py
    - tests/test_names.py
  modified:
    - src/clawrium/cli/host.py
    - tests/test_cli_host.py
decisions:
  - "key_id field stores the identifier used during host init (alias or hostname)"
  - "Alias takes precedence over hostname for key_id determination"
  - "No random name generation - users provide explicit aliases for IPs"
metrics:
  duration: 401s
  completed: 2026-03-21T20:38:48Z
---

# Quick Task 260321-iqu: Fix Key Lookup Mismatch Summary

Fixed issue #1 where SSH keys were stored under one identifier but looked up under another after hostname resolution.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Create names.py with random name generator (TDD) | 3fdc566, 65df92f | names.py, test_names.py |
| 2 | Add key_id field to host records | dda4260 | host.py, test_cli_host.py |
| 3 | Add tests for key_id behavior | 1262959 | test_cli_host.py |

## Implementation Details

### Names Module (src/clawrium/core/names.py)

New utility module with:

- `generate_random_name()` - Returns Docker-style "adjective-scientist" names
  - 29 adjectives (clever, swift, bright, etc.)
  - 50 scientist names (einstein, curie, newton, etc.)
  - Used for future enhancement of IP address handling
- `is_ip_address(value)` - Validates IPv4 addresses with regex + range check (0-255 per octet)

### Key ID Field

Added `key_id` field to host records to solve the lookup mismatch:

**Before (broken):**
1. `clm host init kevin` → keys at `~/.config/clawrium/keys/kevin/`
2. `clm host add 192.168.1.100 --alias kevin` → host record created
3. `clm host status kevin` → resolves kevin→192.168.1.100, looks for keys at `192.168.1.100/` → **FAILS**

**After (fixed):**
1. `clm host init kevin` → keys at `~/.config/clawrium/keys/kevin/`
2. `clm host add 192.168.1.100 --alias kevin` → host record with `key_id="kevin"`
3. `clm host status kevin` → uses `key_id="kevin"` from record, finds keys at `kevin/` → **SUCCESS**

### Key ID Determination Logic

```python
key_lookup_id = alias if alias else hostname
```

- If `--alias` provided → use alias as key_id
- Otherwise → use hostname argument as key_id
- Simplified from plan's random name generation (deferred for future UX improvement)

### Updated Commands

**host add:**
- Determines `key_id` before keypair check
- Stores `key_id` in host record
- Keypair lookup uses `key_id` (not resolved hostname)

**host status:**
- Reads `key_id` from host record
- Fallback to `hostname` for backward compatibility with old records
- Uses `key_id` for keypair lookup

**host remove:**
- Reads `key_id` from host record
- Fallback to `hostname` for backward compatibility
- Deletes keys using `key_id`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed test_host_add_with_flags to create keypair for alias**
- **Found during:** Task 2
- **Issue:** Test created keypair for IP "192.168.1.100" but used --alias "myhost", causing key lookup mismatch
- **Fix:** Changed test to create keypair for "myhost" to match new key_id logic
- **Files modified:** tests/test_cli_host.py
- **Commit:** dda4260 (included in Task 2)

### Design Decisions

**2. Simplified key_id logic - no random name generation**
- **Context:** Plan specified generating Docker-style random names when user provides IP without alias
- **Issue:** Creates chicken-egg problem - random name generated during `add`, but keys already stored under IP from `init`
- **Decision:** Simplified to use alias or hostname directly, no random generation
- **Rationale:** Clearer workflow, avoids lookup mismatch between init and add
- **Future:** Random name generation can be added to `host init` command for better UX with IPs
- **Files affected:** host.py (simpler logic), names.py (created but not used yet)

## Test Coverage

- 7 new tests for names module (generate_random_name, is_ip_address)
- 3 new tests for key_id behavior (alias storage, hostname storage, status lookup)
- 1 updated test (host_add_with_flags keypair location)
- Total: 115 tests passing

## Verification

Manual verification workflow:

```bash
# Workflow 1: Alias-based (original issue case)
clm host init kevin
clm host add 192.168.1.100 --alias kevin
clm host status kevin  # ✓ Now works - uses key_id="kevin"

# Workflow 2: Hostname-based
clm host init webserver
clm host add webserver
clm host status webserver  # ✓ Works - uses key_id="webserver"

# Workflow 3: IP-based (current behavior)
clm host init 192.168.1.100
clm host add 192.168.1.100
clm host status 192.168.1.100  # ✓ Works - uses key_id="192.168.1.100"
```

## Known Stubs

None - implementation is complete and functional.

## Self-Check: PASSED

**Created files exist:**
- FOUND: /home/devashish/workspace/ric03uec/clawrium/src/clawrium/core/names.py
- FOUND: /home/devashish/workspace/ric03uec/clawrium/tests/test_names.py

**Modified files verified:**
- FOUND: /home/devashish/workspace/ric03uec/clawrium/src/clawrium/cli/host.py
- FOUND: /home/devashish/workspace/ric03uec/clawrium/tests/test_cli_host.py

**Commits exist:**
- FOUND: 3fdc566 (test: RED phase)
- FOUND: 65df92f (feat: GREEN phase)
- FOUND: dda4260 (fix: key_id implementation)
- FOUND: 1262959 (test: key_id tests)
