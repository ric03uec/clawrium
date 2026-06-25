# UAT Evidence — Issue #812

Real-host verification of the `_verify_health` Linux gateway-port probe.

## Files

| File | Phase | Outcome |
|---|---|---|
| `wolf-i/00-baseline.txt` | Baseline before any change. wolf-i openclaw is currently healthy. | unit `active`, port 40198 bound, HTTP 200, probe rc=0 |
| `wolf-i/01-journal.txt` | journalctl tail (not directly used in this UAT — wolf-i user has no `journalctl --user` permission and no passwordless sudo). | empty — investigation moved to direct process inspection instead |
| `wolf-i/02-induced-repro-sync.txt` | **Induced repro.** Replaced `/home/wolf-i/.openclaw/bin/openclaw` with a stub that answers `--version` correctly (`2026.6.9`) but `exec /bin/sleep 99999` for `gateway run`. Killed the real daemon; systemd respawned the stub. Unit reports `active`; port 40198 silent. Ran `uv run clawctl agent sync wolf-i` (drift forced via a comment line in `.openclaw/env`). | Sync fails with: `Error: sync failed: gateway port 40198 not accepting connections after 15s (agent=wolf-i). systemctl is-active reported the unit running but the daemon is not bound to its declared gateway port. Inspect 'journalctl -u openclaw-wolf-i.service --since='2min ago'' on the agent host for the bind failure.` — `exit_rc=1`. **This is the primary acceptance signal for #812.** |
| `wolf-i/03-restored-negative-control.txt` | Restored the real `openclaw` binary, killed the stub, systemd respawned the real daemon (port 40198 bound again). Detached the `wolf-brave` integration temporarily (pre-existing #790/wolf-i brave-version mismatch is unrelated to #812), introduced drift, re-ran sync. | Sync passes through `verify: checking unit is active` without raising. `exit_rc=0`. **No false positive on a healthy Linux daemon.** Brave re-attached afterwards (host state restored). |
| `esper-macmini/00-mac-negative-control.txt` | Sync against `esper-mac-oc` (Darwin openclaw, port 41091). | Sync passes (`exit_rc=0`). macOS dispatch path unchanged; the Linux change does not regress it. |

## Code Path Demonstrated

`src/clawrium/core/lifecycle_canonical.py:_verify_health` Linux branch:

1. `systemctl is-active <unit>` → returns `active` (passes today even on a half-broken `Type=simple` unit).
2. **NEW** `bash -c 'exec 3<>/dev/tcp/127.0.0.1/<gateway_port>'` poll loop (1s, up to `timeout` seconds).
3. If poll never succeeds → `CanonicalSyncError` with the journal-pointing remediation hint.

The probe runs after the existing diagnostic catalogue (`_diagnose_unit_failure`)
so a unit that is already not-active continues to produce the existing rich
diagnostic; only `active`-but-not-listening was previously a silent green.

## Host State After UAT

- `wolf-i`: openclaw real binary restored, daemon respawned, port 40198 bound, env file canonical, `wolf-brave` integration re-attached. Sentinel file removed. Net state == baseline.
- `esper-macmini`: untouched.
