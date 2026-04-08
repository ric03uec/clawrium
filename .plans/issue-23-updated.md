# Issue #23: Friendly Naming - Updated Plan

## Summary

Allow users to provide friendly names for assistant instances (claws). The claw name serves as BOTH the display name AND the system username. Names are unique per host (across all claw types) and immutable after installation.

## Problem

Currently, claw instances are named based on the host identifier (alias or key_id), resulting in names like `opc-testhost`. This:
- Doesn't distinguish multiple claws on the same host clearly
- Isn't memorable or user-friendly
- Provides no personalization for users

## Key Design Decisions

### 1. Name = User (No Prefix)
- The `user` field in host data IS the claw name
- No separate display_name field needed
- No prefixes like `opc-` or `zc-`
- Example: `clever-einstein` not `opc-clever-einstein`

### 2. Uniqueness Scope
- Names are unique per HOST (not global)
- Uniqueness is across ALL claw types on that host
- `clever-einstein` blocks both openclaw AND zeroclaw on same host
- Same name can exist on different hosts

### 3. Immutability
- Names cannot be changed after installation
- To rename: uninstall and reinstall
- Document clearly in help text

### 4. Validation Rules
- Max 32 characters (Unix username limit)
- Allowed: alphanumeric, hyphens, underscores
- Disallowed: spaces, special chars, empty
- Format: `{adjective}-{scientist}` for auto-generated

## Data Model

### Before
```json
{
    "claws": {
        "openclaw": {
            "version": "0.1.0",
            "status": "installed",
            "user": "opc-hostname"  // Generated from prefix + host
        }
    }
}
```

### After
```json
{
    "claws": {
        "openclaw": {
            "version": "0.1.0",
            "status": "installed",
            "user": "clever-einstein"  // Same as display name, no prefix
        }
    }
}
```

## Files to Modify

### 1. src/clawrium/core/names.py

**Current**: ~51 scientist names

**Changes**:
- Expand `SCIENTISTS` list to 100 names (~49 additions)
- Add `validate_claw_name(name: str) -> tuple[bool, str]`
  - Returns `(is_valid, error_message)`
  - Max 32 chars
  - Alphanumeric + hyphens + underscores only
  - Not empty
- Add `is_name_available_on_host(name: str, host: dict) -> bool`
  - Check ALL claws on host (not just same type)
  - Return True if name is available

### 2. src/clawrium/core/install.py

**Current**: `_get_claw_user()` generates prefixed names (lines 91-112)

**Changes**:
- REMOVE `_get_claw_user()` function entirely
- Update `run_installation()` signature:
  - Accept `name: str | None = None`
  - Remove prefix logic
- Logic:
  1. If name provided, validate format
  2. If no name, generate random name
  3. Check uniqueness across ALL claws on host
  4. Use name directly as `user` field value

### 3. src/clawrium/cli/install.py

**Changes**:
- Add `name: Optional[str] = typer.Option(None, "--name", "-n", help="Friendly name for claw (max 32 chars, alphanumeric/ hyphens/underscores)")`
- Pass name to `run_installation()`
- Display name in success message

### 4. src/clawrium/cli/status.py

**Changes**: None - already displays `user` field

### 5. tests/test_names.py

**New tests**:
- `test_scientist_list_has_100_names()` - Exactly 100 names
- `test_validate_claw_name_valid()` - Valid formats accepted
- `test_validate_claw_name_too_long()` - Rejects > 32 chars
- `test_validate_claw_name_invalid_chars()` - Rejects special chars
- `test_is_name_available_on_host()` - Uniqueness across claw types

### 6. tests/test_install.py

**New tests**:
- `test_install_with_custom_name()` - Uses provided name as user
- `test_install_auto_generates_name()` - Generates name if not provided
- `test_install_rejects_duplicate_name_same_host()` - Uniqueness check
- `test_install_allows_same_name_different_host()` - Different hosts OK
- `test_install_rejects_invalid_name()` - Validation enforced

## Scientist Names to Add (~49)

From diverse fields and backgrounds:

**Physics**: rutherford, hertz, ohm, ampere, volta, kelvin, joule, watt, becquerel, roentgen, bohr, fermi, planck, hawking

**Chemistry**: mendeleev, pauling, lavoisier, dalton, avogadro, boyle, priestley, meitner, franklin

**Mathematics**: gauss, euler, riemann, hilbert, ramanujan, erdos, cauchy, leibniz, descartes, noether

**Biology/Medicine**: pasteur, lister, jenner, fleming, watson, crick, mendel, linnaeus, franklin

**Computer Science**: knuth, dijkstra, shannon, von_neumann, babbage, hopper, liskov, lamport

**Modern**: kaku, penrose, witten, hinton, lecun, bengio

## Implementation Steps

### Step 1: Expand scientist names (names.py)
- Add 49 new names to reach 100 total
- Ensure diverse representation

### Step 2: Add validation (names.py)
```python
def validate_claw_name(name: str) -> tuple[bool, str]:
    if not name:
        return (False, "Name cannot be empty")
    if len(name) > 32:
        return (False, "Name must be 32 characters or less")
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return (False, "Name must contain only alphanumeric characters, hyphens, and underscores")
    return (True, "")
```

### Step 3: Add uniqueness check (names.py)
```python
def is_name_available_on_host(name: str, host: dict) -> bool:
    for claw_config in host.get("claws", {}).values():
        if claw_config.get("user") == name:
            return False
    return True
```

### Step 4: Update install CLI (cli/install.py)
- Add `--name` option with validation help text

### Step 5: Refactor install orchestration (core/install.py)
- Remove `_get_claw_user()` prefix logic
- Accept name parameter
- Generate if None
- Validate and check uniqueness
- Use name as user field directly

### Step 6: Add tests
- Unit tests for validation and uniqueness
- Integration tests for install flow

## Test Strategy

### Unit Tests
- Name validation (format, length, chars)
- Uniqueness checking across claw types
- Name generation (100 names available)

### Integration Tests
- Custom name installation
- Auto-generated name installation
- Duplicate name rejection (same host)
- Same name on different hosts (allowed)
- Name appears without prefix

## Backward Compatibility

### Breaking Change (New Installs Only)
- New installations won't have prefixed usernames
- Only affects NEW installs

### Existing Installations
- Keep working with current `user` values (e.g., `opc-hostname`)
- No migration needed
- Status displays existing usernames as-is

### Documentation Updates
- Help text mentions max 32 chars
- Document immutability
- Note backward compatibility behavior

## Risks

| Risk | Mitigation |
|------|------------|
| Name collision across claw types | Check ALL claws on host |
| Unix username limits | Validate max 32 chars, alphanumeric + -_ |
| User confusion about immutability | Clear help text |
| Existing install confusion | Document backward compat |

## Acceptance Criteria

1. `clm install openclaw --name work-assistant` uses `work-assistant` as user
2. `clm install openclaw` generates random name like `clever-einstein`
3. Installing second claw with same name on same host fails with clear error
4. Installing same name on different host succeeds
5. Names have no prefix (not `opc-*` or `zc-*`)
6. Names max 32 chars validated
7. Invalid chars rejected with clear message
8. 100 scientist names available for generation
9. Existing installations continue working unchanged
10. `clm status` shows user field correctly

## Example Usage

```bash
# Custom name
clm install openclaw myhost --name work-assistant
# => Installed openclaw as 'work-assistant' on myhost

# Auto-generated name
clm install openclaw myhost
# => Installed openclaw as 'swift-curie' on myhost

# Duplicate rejected
clm install zeroclaw myhost --name work-assistant
# => Error: Name 'work-assistant' already in use on myhost

# Same name on different host
clm install openclaw otherhost --name work-assistant
# => Installed openclaw as 'work-assistant' on otherhost

# Status shows names
clm status
# HOST       CLAW       USER              STATUS
# myhost     openclaw   work-assistant    running
# myhost     zeroclaw   clever-einstein   running
# otherhost  openclaw   work-assistant    running
```

---

## Feedback Incorporated

1. ✅ User field = claw name (no prefix)
2. ✅ Names unique across ALL claws on host
3. ✅ Names immutable after installation
4. ✅ Max 32 chars for Unix username compatibility
5. ⏳ NOT pushed to GitHub (awaiting approval)
