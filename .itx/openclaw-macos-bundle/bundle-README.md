# Clawrium Fixes — 2026-06-23

Bundle of fixes from setting up `macmini-openclaw` agent on `espers-mac-mini.tailf7742d.ts.net`.

## Issues Fixed

### 1. Issue #720 — openclaw install fails with `npm ETARGET` when hardware unknown

**Symptom**: `clawctl agent create` picks `openclaw@0.1.0` (first entry in manifest platforms list) instead of the latest CalVer version. That version doesn't exist on npm.

**Root cause**: `src/clawrium/core/install.py:327-331` — when `check_compatibility()` returns `matched_entry=None` (hardware facts not gathered), the fallback was `manifest["platforms"][0]["version"]` which is the oldest entry.

**Fix**: Deterministic fail-fast. If hardware is unknown, raise `InstallationError` with a message telling the operator to ensure `clawctl host create` gathered hardware facts first. No guessing.

**Files**:
- `src/clawrium/core/install.py` — `InstallationError` when `matched_entry` is None
- `src/clawrium/cli/install.py` — null-check before accessing `compat["matched_entry"]["version"]` (would crash with TypeError)
- `tests/test_install.py` — 2 new tests: `test_install_hardware_unknown_raises`, `test_install_hardware_unknown_with_version_override_bypasses_check`

**Error log (before fix)**:
```
agent/macmini-openclaw: [validate] Hardware unknown, using latest: openclaw v0.1.0
...
npm error notarget No matching version found for openclaw@0.1.0.
npm error A complete log of this run can be found in: /Users/macmini-openclaw/.npm/_logs/2026-06-23T04_36_01_529Z-debug-0.log
```

---

### 2. macOS sync — `install -g {owner}` fails (no per-user group on Darwin)

**Symptom**: `clawctl agent sync` fails on macOS with `install: illegal option -- g` or group-not-found because macOS doesn't create a per-user primary group matching the username.

**Root cause**: `_atomic_write()` in `lifecycle_canonical.py` passed `-g {agent_name}` unconditionally. macOS primary group is `staff`.

**Fix**: Added `host_os` parameter; group resolves to `"staff"` on macOS.

**File**: `src/clawrium/core/lifecycle_canonical.py`

---

### 3. macOS sync — `systemctl restart` doesn't exist

**Symptom**: `clawctl agent sync` calls `systemctl restart` which doesn't exist on macOS.

**Fix**: `_restart_unit()` now branches on `host_os`:
- macOS: `sudo -n launchctl kickstart -k system/ai.clawrium.{agent_type}.{agent_name}`
- Linux: `sudo -n systemctl restart` (unchanged)

**File**: `src/clawrium/core/lifecycle_canonical.py`

---

### 4. macOS sync — `systemctl is-active` verify doesn't exist

**Symptom**: `_verify_health()` calls `systemctl is-active` on macOS — fails.

**Fix**: macOS branch polls `lsof -i :{port} -P -sTCP:LISTEN` every 1s, up to 30s. Returns on first listen. Requires `gateway_port` parameter (from hosts.json).

**File**: `src/clawrium/core/lifecycle_canonical.py`

---

### 5. Bedrock model prefix — openclaw expects `amazon-bedrock/` not `bedrock/`

**Symptom**: After sync, openclaw logs `Unknown model: bedrock/zai.glm-5`. The agent can't use the provider.

**Root cause**: `_OPENCLAW_MODEL_PREFIX` in `render.py` mapped `"bedrock"` → `"bedrock/"`. OpenClaw's Bedrock provider is named `amazon-bedrock` and expects the prefix `amazon-bedrock/`.

**Fix**: Changed prefix mapping and all templates.

**Files**:
- `src/clawrium/core/render.py:1369` — `"bedrock"` → `"amazon-bedrock/"`
- `src/clawrium/platform/registry/openclaw/templates/.env.j2` — prefix fix
- `src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2` — prefix fix
- `src/clawrium/platform/registry/openclaw/templates/verify_config.py` — prefix fix

**Error log (before fix)**:
```
[gateway] Unknown model: bedrock/zai.glm-5
[gateway] Falling back to default model selection
```

---

### 6. Manifest registry update — v2026.6.9

OpenClaw published v2026.6.9. Added platform entries to manifest.

**File**: `src/clawrium/platform/registry/openclaw/manifest.yaml`
- Ubuntu 24.04 x86_64: v2026.6.9
- Ubuntu 22.04 x86_64: v2026.6.9
- macOS >=14 arm64: v2026.6.9
- Plugin pin bumped: `brave.version` → `"2026.6.9"`

---

## Test Adjustments

- `tests/cli/clawctl/agent/test_sync.py` — mock `fake_restart()` updated to accept `**kwargs` (for new `host_os` param)
- `tests/cli/test_agent_upgrade.py` — `test_upgrade_no_op_when_already_at_max` updated expected version from `2026.6.8` → `2026.6.9`
- `tests/core/test_render.py` — render tests updated for `amazon-bedrock/` prefix

## Known Remaining Issues

1. `test_below_min_version_raises` may need version update (manifest now has 2026.6.9)
2. `plugins.allow` warning on gateway startup (cosmetic, upstream openclaw issue)
3. macOS verify timeout (30s) can be tight on cold start with bedrock plugin

## How to Apply

```bash
cd /path/to/clawrium
git apply changes.patch
```

Or copy individual files from this bundle (directory structure matches repo layout).

## Host Setup Completed

- **Host**: `esper-macmini` @ `espers-mac-mini.tailf7742d.ts.net`
- **Agent**: `macmini-openclaw` (openclaw v2026.6.9)
- **Provider**: `keith-bedrock` → `amazon-bedrock/zai.glm-5`
- **Port**: 40510
- **Status**: Running, healthy, gateway responding
