# Real-host UAT — Issue #811

All transcripts in this directory. One-line status per scenario below.

## wolf-i (linux) — the host that carried the original wedge

| Scenario | Transcript | Result |
|---|---|---|
| Baseline: describe shows `ready`, host has no unit | `wolf-i/00-baseline-describe.txt`, `wolf-i/00-baseline-host-state.txt` | Confirms #811 repro state. |
| Baseline: sync fails at restart (old behavior) | `wolf-i/00-baseline-sync.txt` | Render + diff + write + workspace push all execute against missing daemon; failure at `_restart_unit`. |
| After fix: sync (first attempt — bug found in probe) | `wolf-i/10-sync-after-fix.txt` | Validate phase triggered. First version of probe incorrectly reported home dir missing — turned out `xclm` cannot `test -d` paths inside an agent's mode-0750 home without sudo. |
| After sudo fix: sync correctly identifies only the unit as missing | `wolf-i/11-sync-after-sudo-fix.txt` | Probe now uses `sudo -n test -d`; cleanly fails with `missing service unit '/etc/systemd/system/zeroclaw-clawrium-d01.service'`. No render, no diff, no write. |
| Happy-path regression: healthy hermes agent | `wolf-i/12-sync-happy-path-regression.txt` | `clawrium-triage` syncs cleanly; validate phase emits `checking host install` then proceeds through render/diff/write/restart. |
| Health probe surfaces INSTALL_MISSING | `wolf-i/13-health-probe-install-missing.txt` | `check_claw_health('clawrium-d01')` returns `status=install_missing` with actionable error string. |
| Health probe happy-path regression | `wolf-i/14-health-probe-healthy-regression.txt` | `clawrium-triage` returns `status=running` — install probe correctly skipped on running agents. |

## kevin (linux/arm) — independent host reproduction

| Scenario | Transcript | Result |
|---|---|---|
| Direct probe shell on kevin for a synthetic agent | `kevin/01-probe-shell-direct-fakebox.txt` | `unit:0\nhome:0` — proves the probe shell command behaves identically on a different Linux host with `sudo -n` available. |

Note: kevin has no installed agents and is on armv7l (per project memory
`zeroclaw_armv7l_bind_bug`, the zeroclaw daemon has a known bind issue on
that arch). Installing + tearing down an agent there to produce a `clawctl
agent sync` transcript would have polluted the host with broken
bind-state. The direct probe-shell run + the wolf-i transcripts together
exercise every code path the fix introduces.

## mac-test / esper-macmini (darwin/arm64) — macOS dispatcher

| Scenario | Transcript | Result |
|---|---|---|
| Probe shell direct (synthetic agent) | `mac-test/00-esper-macmini-probe.txt` | `unit:0\nhome:0` — confirms the same probe shell command works on darwin. |
| Probe shell direct (real installed openclaw) | `mac-test/01-esper-macmini-happy-path.txt` | `unit:1\nhome:1` — happy path on macOS. |
| Probe via canonical pipeline (`probe_host_install` → `unit_path_for(darwin, ...)`) | `mac-test/02-probe-via-canonical-pipeline.txt` | Real openclaw: `ok`. Synthetic hermes: both artifacts correctly identified as missing; plist path resolved through `core.launchd.plist_path_for`, home path through `home_root_for("darwin")` → `/Users/<agent>/.hermes`. Confirms the dispatcher-only OS-fork invariant holds end-to-end. |

mac-test SSH was timing out at the time of UAT despite `clawctl host get`
showing `ready` (the latter reads cached state). `esper-macmini` is the
sibling macOS host (per project-board) and is the standing alternative
target. macOS coverage rides on the esper-macmini transcripts.

## Coverage matrix

| Path | unit_path_for | home_root_for | Real host | Result |
|---|---|---|---|---|
| Linux, both present | systemd | `/home` | wolf-i clawrium-triage | ✓ happy path |
| Linux, unit missing only | systemd | `/home` | wolf-i clawrium-d01 | ✓ probe failure caught |
| Linux, both missing | systemd | `/home` | kevin synthetic | ✓ probe failure caught |
| Linux, only home missing | n/a | n/a | (unit-test only) | unit test `test_probe_failure_with_home_missing_names_home` |
| macOS, both present | launchd plist | `/Users` | esper-macmini esper-mac-oc | ✓ happy path |
| macOS, both missing | launchd plist | `/Users` | esper-macmini synthetic | ✓ probe failure caught |
| Health probe → INSTALL_MISSING | systemd | `/home` | wolf-i clawrium-d01 | ✓ status transitions correctly |
| Health probe → RUNNING (regression) | n/a | n/a | wolf-i clawrium-triage | ✓ install probe skipped on running agents |
