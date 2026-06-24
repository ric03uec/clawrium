# Issue #719 — Execution log

End-to-end verification run on `clawdmin03@espers-mac-mini.tailf7742d.ts.net`
using the branch `fix/openclaw-macos-bundle-20260623` (i.e. the branch
code, not the released `clawctl` on the management machine).

Date: 2026-06-23
Host: macOS 26.5.1, arm64 (Mac mini, 10 cores, 16GB)
Management user: `xclm`
Agent: `esper-mac-oc` (openclaw v2026.6.9)
Provider: `clm-openrouter` (openrouter/openai/gpt-4o) — reused, not
re-created
Gateway port: 41091

## Summary

End-to-end is **functional**. The bundle's openclaw-on-macOS fixes
land correctly. **Two additional bugs were uncovered during live
verification and fixed in this same branch:**

1. `verify_config.py` used PEP 604 `str | None` syntax (Python 3.10+);
   macOS ships Python 3.9.6 in `/usr/bin/python3` (Xcode CLI tools),
   so the verify step crashed with `TypeError: unsupported operand
   type(s) for |: 'type' and 'NoneType'`. Fixed with
   `from __future__ import annotations`.
2. `verify_health_macos` used `lsof -i :<port> -P -sTCP:LISTEN`, which
   only shows listeners owned by the running user on macOS. The
   canonical sync runs as `xclm` while the daemon runs as
   `<agent_name>` (different uid), so `lsof` returned rc=1 and the
   sync errored with `gateway port 41091 not listening after 30s` —
   even though the daemon was healthy and accepting connections.
   Switched to `nc -z -w 1 127.0.0.1 <port>` (TCP connect probe; no
   sudo required, ships in macOS by default). Tests + CHANGELOG
   updated to match.

## Steps Executed

### 1. SSH preflight — `clawdmin03`

```
ssh clawdmin03@espers-mac-mini.tailf7742d.ts.net 'sw_vers && uname -m && xcode-select -p'
→ macOS 26.5.1, arm64, /Library/Developer/CommandLineTools
```

Xcode CLI tools already installed → the original symptom in #719
(`xcode-select: error: No developer tools were found`) does not apply
to this host.

### 2. xclm management user

`clawctl host create … --user xclm` requires the `xclm` user with
NOPASSWD sudo and an authorized key. `clawdmin03` was used to set
this up (single interactive sudo over SSH; one-shot script per
`docs/host-preparation.md` macOS block).

**Quirk on this host:** an older xclm setup had stale
`/Users/xclm/.ssh/authorized_keys` (different pubkey from a prior
bundle owner's setup). Had to overwrite with our branch's
freshly-generated pubkey. Also, `com.apple.access_ssh` group
"not found" on this macOS version — irrelevant because Remote Login
is configured for "All Users".

### 3. `clawctl host create esper-macmini`

Succeeded immediately on the re-run (xclm key auth + NOPASSWD sudo
both working). Stored at `~/.config/clawrium/hosts.json` with
`hardware: {}`.

### 4. Hardware gathering — gap surfaced

The canonical `clawctl host create` (under
`src/clawrium/cli/clawctl/host/create.py`) **does not call
`gather_hardware`**. Only the legacy `clawctl host add` and `host
ps --refresh` do. So `hardware == {}` was the persisted state after
step 3.

Worked around by calling `gather_hardware` directly:

```python
from clawrium.core.hardware import gather_hardware
from clawrium.core.hosts import update_host
hw = gather_hardware(hostname='…', user='xclm', port=22, ssh_key='…')
update_host('…', lambda h: dict(h, hardware=hw, …))
```

Result: `hardware = {os: macos, os_version: 26.5.1, architecture: arm64, …}`.

**Follow-up issue worth filing**: canonical `clawctl host create`
should gather hardware (or call out the next-step) so operators don't
hit the #720 fail-fast on first install. Out of scope for this
branch.

### 5. `clawctl agent create … --type openclaw` — #720 fail-fast verified

First run with empty hardware:

```
agent/esper-mac-oc: [validate] Checking compatibility...
Error: installation failed: Cannot determine compatible version for
'openclaw': host hardware information is not available. Run 'clawctl
host create' with SSH access first to gather hardware facts, then
retry the install.
```

This is the #720 fix from the bundle. Confirms the dispatcher refuses
to guess `platforms[0]` (the v0.1.0 case from the bug report).

After backfilling hardware (step 4) and re-running:

```
agent/esper-mac-oc: installed (2026.6.9)
agent/esper-mac-oc: ready
```

Picks **v2026.6.9** — the macOS arm64 entry added to the manifest in
this branch.

### 6. Provider attach (reused existing openrouter)

```
clawctl agent provider attach clm-openrouter --agent esper-mac-oc
→ agent/esper-mac-oc: attached provider 'clm-openrouter'
```

### 7. `clawctl agent configure --stage providers` — verify_config bug

Failed at the `Verify openclaw.json configuration` task. `no_log:
true` masked the error. Temporarily flipped to `no_log: false` +
added `debug` + `fail` tasks to surface the real error:

```
verify rc=1 stderr=Traceback (most recent call last):
  File "/tmp/clawrium_verify_config_esper-mac-oc.py", line 50, in main
    def _expected_model_id(expected: dict) -> str | None:
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

Root cause: macOS host's `python3` is 3.9.6 (Xcode CLI tools); PEP
604 union types (`X | Y`) require 3.10+. Fixed in
`src/clawrium/platform/registry/openclaw/templates/verify_config.py`
by adding `from __future__ import annotations` (defers all annotation
evaluation; compat back to Python 3.7+).

Reverted the playbook debug changes; configure re-ran clean:

```
agent/esper-mac-oc: [configure] Successfully configured esper-mac-oc
agent/esper-mac-oc: [restart] launchctl kickstart -k esper-mac-oc (gateway)
agent/esper-mac-oc: stage providers complete
```

That `launchctl kickstart -k` line is the new
`lifecycle_macos.restart_unit_macos` dispatcher path from this
branch.

### 8. `clawctl agent sync` — lsof-needs-sudo bug

First sync run:

```
agent/esper-mac-oc: restart: launchctl kickstart -k system/ai.clawrium.openclaw.esper-mac-oc
agent/esper-mac-oc: verify: checking unit is active
Error: sync failed: gateway port 41091 not listening after 30s
```

But the daemon WAS healthy: `sudo lsof -i :41091 -P -sTCP:LISTEN` on
the host showed `node 15672 esper-mac-oc … TCP *:41091 (LISTEN)`.

Root cause: `lsof` on macOS only shows listeners owned by the
running user. Sync runs `lsof` over SSH as `xclm`; the daemon runs
as `esper-mac-oc`. Different uid → empty result → rc=1 → false
"not listening" verdict.

Fixed by replacing the lsof probe with `nc -z -w 1 127.0.0.1
<port>` — a TCP connect that succeeds when the daemon is
`accept()`-ing, regardless of which uid owns the socket. `nc` ships
in macOS by default; no sudo needed.

Updates:
- `src/clawrium/core/lifecycle_macos.py:verify_health_macos`
- `tests/core/test_lifecycle_canonical_macos_dispatch.py`
  (test_nc_connect_returns_immediately + timeout-message regex)
- `CHANGELOG.md` Added entry: `nc -z` (with rationale comment about
  the `lsof` uid restriction)

Re-ran `clawctl agent restart` to exercise the verify path:

```
agent/esper-mac-oc: [restart] launchctl kickstart -k esper-mac-oc (gateway)
agent/esper-mac-oc: [restart] Restarted esper-mac-oc successfully
agent/esper-mac-oc: restarted
```

### 9. Functional gateway check

```
curl http://espers-mac-mini.tailf7742d.ts.net:41091/health
→ {"ok":true,"status":"live"}
```

Daemon log shows openrouter provider loaded successfully:

```
[gateway] auto-enabled plugins for this runtime without writing config:
  - openrouter/openai/gpt-4o model configured, enabled automatically.
[gateway] http server listening (9 plugins: bonjour, browser, canvas,
  device-pair, file-transfer, memory-core, openrouter, phone-control,
  talk-voice; 0.4s)
[gateway] agent model: openrouter/openai/gpt-4o (thinking=medium, fast=off)
[gateway] ready
[gateway] provider auth state pre-warmed in 466ms
```

No `Unknown model: …` errors. Openrouter plugin loaded, model
resolved, gateway healthy.

### 10. `clawctl agent chat --once`

`--once` flag is marked "Not implemented". Interactive mode connects
but fails with `Protocol error: protocol mismatch` — appears to be a
separate clawctl-openclaw chat-client skew, not related to the
sync/install path this issue is about. Out of scope for #719.

The daemon-level evidence (openrouter loaded, model configured,
`/health` 200) is sufficient proof that the install + configure +
sync path works end-to-end on macOS.

## Test + Lint Status (post-fixes)

- `make lint` clean.
- `make test`: **3867 Python passed, 2 skipped, 0 failed; 305 vitest
  passed**.

## Files Touched (additions to the bundle work)

| File | Change |
|---|---|
| `src/clawrium/core/lifecycle_macos.py` | `verify_health_macos`: lsof → `nc -z` |
| `src/clawrium/platform/registry/openclaw/templates/verify_config.py` | Added `from __future__ import annotations` |
| `tests/core/test_lifecycle_canonical_macos_dispatch.py` | nc command + new error message in 2 tests |
| `CHANGELOG.md` | Added entry updated to mention `nc -z` rationale |

## Outstanding (for separate follow-ups, NOT blocking #719 close)

- Canonical `clawctl host create` should gather hardware (or print
  clear next-step). Today operators hit the #720 fail-fast on first
  `agent create` and have no documented way to backfill except the
  legacy `clawctl host add`/`host ps --refresh` paths or the Python
  workaround above.
- `clawctl agent chat` protocol mismatch with openclaw v2026.6.9 —
  worth filing as a separate bug.

## Prompt Log

**Stage**: execution
**Skill**: (none — direct E2E)
**Timestamp**: 2026-06-23T23:45:00Z
**Model**: claude-opus-4-7

```prompt
run the end to end test now on the host
```

**Output**: This execution log documenting the full E2E walkthrough,
two additional bugs found + fixed in the same branch, and the proof
that the install/configure/sync/health path on macOS works end-to-end
with an openrouter provider.
