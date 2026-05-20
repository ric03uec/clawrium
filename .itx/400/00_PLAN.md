# Plan: Issue 400 — Agent Remove State Cleanup

## Summary

`clm agent remove <name>` leaves orphan `~/.config/clawrium/agents/<name>/skills.json`

## Root Cause

`remove_agent()` in `src/clawrium/core/lifecycle.py` (lines 1486-1616) cleans up instance secrets but never removes the agent's state directory.

## Implementation

### 1. Add cleanup helper to `skills_state.py`

```python
def cleanup_agent_state(agent_name: str) -> bool:
    """Remove the entire state directory for agent_name."""
    path = state_file_path(agent_name).parent  # agents/<name>/
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False
```

### 2. Call in `lifecycle.py` after instance secret cleanup (~line 1572)

```python
from clawrium.core.skills_state import cleanup_agent_state
# ... after remove_instance_secrets ...
cleanup_agent_state(unix_agent_name)
emit("remove", "Cleaned up agent state directory")
```

### 3. Add test in `tests/test_lifecycle.py`

- Create agent state directory with `skills.json`
- Call `remove_agent` (mocked playbook)
- Assert `~/.config/clawrium/agents/<name>/` no longer exists

## Files to Modify

| File | Change |
|------|--------|
| `src/clawrium/core/skills_state.py` | Add `cleanup_agent_state()` to `__all__` and implement |
| `src/clawrium/core/lifecycle.py` | Import and call `cleanup_agent_state()` |
| `tests/test_lifecycle.py` | Add regression test |

## Acceptance Criteria

- [ ] After `clm agent remove <name>`, `~/.config/clawrium/agents/<name>/` no longer exists
- [ ] Re-installing under same name starts with empty state
- [ ] Existing tests pass
- [ ] New unit test asserts cleanup
