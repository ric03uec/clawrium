# Plan: Persist SSH Tunnel Ports + Increase SSH Timeout (#866)

## Overview

Two independent improvements to `web_ui_tunnel.py`:

1. **Port persistence** — when a dead tunnel is re-established, try to reuse the
   same local port from the prior state file. Callers (e.g. `clawctl agent open`,
   GUI) get the same `127.0.0.1:<port>` URL after a reconnect, so bookmarks and
   in-browser sessions survive SSH drops.

2. **SSH timeout increase** — current config is `ServerAliveInterval=30` with no
   `ServerAliveCountMax` (kernel default = 3 → ~90 s silence → disconnect). Bump
   to `ServerAliveInterval=60` + `ServerAliveCountMax=10` = 10 minutes of network
   silence tolerance, covering typical WiFi hand-offs and brief ISP hiccups without
   killing the tunnel.

## Root Cause Analysis

### Port churn
`ensure()` and `ensure_at_port()` call `_pick_free_port()` (OS `bind(0)`) every time
a tunnel needs spawning. The tunnel state file holds `local_port` from the *previous*
run, but the code discards it — the preferred port is never consulted.

Key code path in `ensure()` (`web_ui_tunnel.py:491`):
```python
_evict_stale(agent_key)   # deletes state file
local_port = _pick_free_port()  # fresh ephemeral port — loses last port
```

### Short keepalive
`_ssh_command()` (`web_ui_tunnel.py:247`) emits only `ServerAliveInterval=30`; no
`ServerAliveCountMax` means the SSH default of 3 applies → 90 s ceiling.

## Files to Modify

| File | Change |
|------|--------|
| `src/clawrium/core/web_ui_tunnel.py` | Add `_is_port_available`, update `ensure` + `ensure_at_port`, bump SSH keepalive |
| `tests/test_web_ui_tunnel.py` | Tests for port reuse, port fallback, keepalive params |
| `CHANGELOG.md` | `### Changed` entry |

## Implementation Steps

### Step 1 — `_is_port_available(port)` helper

```python
def _is_port_available(port: int) -> bool:
    """Return True iff 127.0.0.1:<port> can be bound (not currently in use)."""
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False
```

No `SO_REUSEADDR` — we want a strict check so we don't accidentally tell SSH to
bind a port that's in TIME_WAIT.

### Step 2 — Read preferred port before eviction in `ensure()`

Insert before `_evict_stale(agent_key)`:

```python
# Capture the last port before state is cleared; used as preference below.
_last_state = _read_state(agent_key)
_preferred_port: int | None = None
if _last_state:
    try:
        _preferred_port = int(_last_state["local_port"])
    except (KeyError, TypeError, ValueError):
        pass
```

Then replace `local_port = _pick_free_port()` with:

```python
if _preferred_port is not None and _is_port_available(_preferred_port):
    local_port = _preferred_port
else:
    local_port = _pick_free_port()
```

Apply the same pattern to `ensure_at_port()` (line 558), using the namespaced key.

### Step 3 — Bump SSH keepalive in `_ssh_command()`

Change (line 247):
```python
"-o", "ServerAliveInterval=30",
```
To:
```python
"-o", "ServerAliveInterval=60",
"-o", "ServerAliveCountMax=10",
```

This raises the silence ceiling to 10 minutes (60 × 10 = 600 s) without affecting
the KeepAlive frequency in a way that would stress the network.

### Step 4 — Tests

Add to `tests/test_web_ui_tunnel.py`:

- `test_preferred_port_reused_after_stale_eviction`: write a dead-state JSON with
  `local_port=XXXX` into the state dir; mock `_is_port_available` → True; call
  `ensure()`; assert the SSH command receives `XXXX` as the local port.
- `test_preferred_port_fallback_when_occupied`: same dead state; mock
  `_is_port_available` → False; verify SSH gets a *different* port (from
  `_pick_free_port`).
- `test_ssh_command_includes_keepalive_params`: call `_ssh_command(...)` directly
  and assert `-o ServerAliveInterval=60` and `-o ServerAliveCountMax=10` appear in
  the output list.

### Step 5 — CHANGELOG

Under `### Changed`:
```
- SSH tunnel keepalive increased to 60 s interval × 10 count (10 min ceiling), reducing spurious disconnects during brief network interruptions (#866).
- SSH tunnel manager now tries to reuse the previous local port when a tunnel is re-established, keeping `127.0.0.1:<port>` URLs stable across reconnections (#866).
```

## Test Strategy

- Unit tests only — no real SSH invoked (Popen is mocked throughout the existing test
  suite; new tests follow the same pattern).
- Run `make test && make lint` before commit.
- Real-host UAT: `clawctl agent open <hermes-agent>` on a host with a hermes agent,
  kill the SSH tunnel process manually (`kill <pid>`), then run `clawctl agent open`
  again and verify the browser URL port is unchanged.

## Risks / Notes

- **Race condition**: between `_is_port_available` returning True and SSH binding the
  port, another process could grab it. The existing `_pick_free_port` docstring
  acknowledges the same race. If SSH fails to bind, `ExitOnForwardFailure=yes` causes
  it to exit non-zero; `_wait_for_connect` times out and raises `TunnelError` as
  today. No silent fallback needed.
- **Port range**: no restriction on which ephemeral port can be "preferred" — if the
  previous port was in the OS ephemeral range (32768–60999 on Linux), it's still
  valid to try. SSH has no preference as long as the port is available.
- **No subtasks** — single-file core change + single-file test update. Too small to
  split.

---

## Prompt Log

### Planning

**Stage**: plan
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-11T00:00:00Z
**Model**: claude-sonnet-4-6

```prompt
866 . plan create only in a worktree.
```

**Output**: High-level implementation plan saved to `.itx/866/00_PLAN.md`
