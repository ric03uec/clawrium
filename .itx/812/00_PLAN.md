# Implementation Plan — Issue #812

> openclaw daemon does not bind its gateway port after `clawctl agent sync`
> reports successful restart.

## Root Cause

`core/lifecycle_canonical.py:_verify_health` on Linux runs **one** check:
`systemctl is-active <unit>`. That returns `active` as soon as the daemon
process is *spawned* by systemd, regardless of whether the process has
yet bound its gateway port — because the openclaw systemd unit shipped
by our installer is `Type=simple`:

```
[Service]
Type=simple
User=wolf-i
EnvironmentFile=/home/wolf-i/.openclaw/env
ExecStart=/home/wolf-i/.openclaw/bin/openclaw gateway run --allow-unconfigured
Restart=always
RestartSec=5
```

(captured from `/etc/systemd/system/openclaw-wolf-i.service` on wolf-i —
see `.itx/812/evidence/wolf-i/00-baseline.txt`).

There are three failure modes that all surface as the same "sync says OK
but the port is not listening" symptom:

| Mode | What systemd sees | What `is-active` returns | What `ss -tlnp <port>` returns |
|---|---|---|---|
| a) Daemon spawned, in the middle of binding (cold start) | running | `active` | empty (race) |
| b) Daemon crashloops in <5s but is "active" between restarts | activating (`auto-restart`) **or** active mid-crashloop | sometimes `active` | empty |
| c) Daemon runs forever but never binds (misconfig / hang) | running | `active` | empty |

`Type=simple` cannot disambiguate any of these — systemd has no
readiness signal from the daemon. Only an out-of-band probe against the
gateway port can.

The **macOS** verify path (`core/lifecycle_macos.py:verify_health_macos`)
already does exactly this — it polls `nc -z -w 1 127.0.0.1 <port>` until
the port accepts a TCP connect, or raises after `timeout` seconds. That
is the same shape we need on Linux. The fix is to bring the Linux path
to parity.

### Why this is wolf-i-specific in the field

The bug is **not** wolf-i-specific in source — it's a Linux-class bug
that anyone running the openclaw daemon on systemd is exposed to. wolf-i
just happens to be the host where it caught the eye, because its
openclaw install never completed cleanly (issue #810) and the daemon was
transiently failing to bind the gateway. `esper-mac-oc` doesn't trigger
it because the macOS verify path already probes the port.

### Shared root cause with #810?

**Partially.** #810 is "openclaw with status=failed in hosts.json still
sails through `clawctl agent sync`" — a separate state-machine bug.
That bug *exposed* #812 because a partially-installed daemon is exactly
the kind of daemon that runs but cannot bind. But the fixes are
independent:

- #810 — refuse / quarantine sync for agents whose install never
  completed. (Handled by sibling session.)
- #812 — even if sync is permitted, post-restart verify must prove the
  daemon is actually listening on its declared gateway port.

Fixing #812 alone is sufficient to stop the "green sync, dead port"
operator-facing symptom. Fixing #810 alone would not — a healthy install
can still hit #812 if the daemon decides to crash on startup for any
unrelated reason (bad env var, missing plugin file, etc.).

## Solution

**Pick:** option (i) from the issue — make `_verify_health` on Linux
hard-fail the sync if the gateway port is not accepting connections
within a short timeout after the unit reports `is-active=active`. Mirror
the macOS poll loop.

### Why not the other options

- **(ii) yellow warning instead of fail.** Rejected. The operator's
  contract for `agent sync` is "after this returns OK, the on-host state
  matches my desired state". A warning that operators may scroll past is
  exactly the failure mode the issue body says is worst. The macOS path
  raises today — Linux should match.
- **(iii) `agent doctor` subcommand.** Useful as a follow-up but doesn't
  fix the immediate symptom. Sync would still print `synced (drift=0)`
  for a dead daemon; the operator only finds out by running a different
  command. Add doctor later if needed; #812 wants sync itself to refuse.

### Why mirror the macOS approach exactly

`verify_health_macos` already solved this problem on macOS. Iterating
the Linux path along the same shape:

- Same call site (`_verify_health` dispatcher, already plumbs
  `gateway_port`).
- Same poll-with-deadline loop.
- Same `CanonicalSyncError` failure mode.
- Same "missing tool" diagnostic shape (raise early with a clear
  message rather than chase the 15s deadline and misdirect).

Maximizes consistency in the codebase and reuses test patterns.

### Probe choice

`bash -c 'exec 3<>/dev/tcp/127.0.0.1/<port>' </dev/null 2>/dev/null`.

Rationale:
- `bash` is universal on every Linux host clawrium targets (Ubuntu /
  Debian — base images ship bash). No extra package required.
- `/dev/tcp/<host>/<port>` is a bash builtin (no real device file).
  Opens a TCP connect; succeeds (exit 0) when something `accept()`s,
  fails (non-zero) on `connection refused` or DNS error.
- Doesn't require `nc` (which Ubuntu cloud images sometimes ship
  without).
- No false-positive on partial bind — TCP connect proves the kernel
  has a listener socket.

Same shape as the macOS `nc -z -w 1` probe semantically.

### Zeroclaw / `#437` invariant

`_verify_health` is called from `sync_agent_canonical` after `restart`,
which fires on every zeroclaw sync (per the "Gateway Token Lifecycle
(zeroclaw)" section in `AGENTS.md`). The new probe runs *after*
`systemctl is-active` succeeds and *before* the zeroclaw re-pair step at
line 1429. If the probe fails, we raise `CanonicalSyncError` and the
re-pair never runs. That's correct: re-pairing a daemon that isn't
listening on its port would also fail. The bearer-rotation behavior is
unchanged for the happy path.

### Native dashboard / `#491` / `#478`

For openclaw the SPA is served by the same `gateway run` process on the
same port (`gateway.port`, bind=wildcard). A probe against the gateway
port implicitly proves the dashboard is reachable. For hermes the
dashboard is a separate unit on a different port (loopback) — we do NOT
probe it; the canonical sync only restarts the gateway unit. That's
fine; the gateway probe is the inner-loop correctness invariant.

## Files to Change

### `src/clawrium/core/lifecycle_canonical.py`

1. Add helper `_verify_gateway_listening_linux(client, *, agent_name,
   gateway_port, timeout) -> None`. Mirrors `verify_health_macos` in
   shape: validate `agent_name` and `gateway_port`, poll bash
   `/dev/tcp` connect with 1s sleeps until success or deadline, raise
   `CanonicalSyncError` on timeout / missing-tool.
2. In `_verify_health` Linux branch, after the existing `is-active`
   block, call the new helper iff `gateway_port is not None`. If
   `gateway_port is None`, retain the current behavior (silent
   success — this keeps backwards-compat for unit-test call sites
   that don't pass a port).

### `tests/core/test_lifecycle_canonical.py`

Add a new `TestVerifyHealthLinuxGatewayProbe` class. Cases:
- Unit active + port bound on first poll → success, exactly one probe.
- Unit active + port bound on third poll → success, exactly three probes.
- Unit active + port never binds → `CanonicalSyncError` matching
  `gateway port N not accepting connections after Ts`.
- Unit active + `bash` missing on host (rc=127, stderr matches
  `bash: not found` / `command not found`) → `CanonicalSyncError`
  matching `bash` not available — break on first probe.
- Unit active + `gateway_port=None` → no probe attempted (preserves
  existing default-arg behavior).
- Invalid port (string, 0, -1, 65536, bool) → `CanonicalSyncError`
  matching `invalid gateway_port`.

## Test Strategy

1. Unit tests above run via `make test`.
2. `make lint` — ruff.
3. Real-host UAT (see below).

## UAT Plan

| Phase | Host | Setup | Expected |
|---|---|---|---|
| Baseline | wolf-i (linux/openclaw) | Already captured: daemon currently healthy, port 40198 listening. | `00-baseline.txt` already saved. |
| Induced repro | wolf-i | Hand-edit `/etc/systemd/system/openclaw-wolf-i.service` ExecStart to `/bin/sleep 9999`, `systemctl daemon-reload`, `systemctl restart openclaw-wolf-i.service`. Confirm unit is `active` but port 40198 silent. Then `clawctl agent sync wolf-i --no-restart` is no good (skips restart); instead bump the env file so files change, then sync. | Fixed code: sync raises `CanonicalSyncError: gateway port 40198 not accepting…` and exits non-zero. Pre-fix code (current main): sync prints `synced (drift=0)`. |
| Restore + happy path | wolf-i | Restore the real ExecStart, restart the unit, re-run sync. | Sync succeeds. |
| Negative control (macOS) | esper-macmini (`esper-mac-oc` openclaw, healthy) | No setup — just sync. | Sync succeeds (macOS probe path unchanged — sanity check we didn't regress it). |
| Negative control (Linux healthy) | wolf-i after restore | Re-run sync several times. | Sync succeeds every time; no false positives. |

Capture each phase's transcript under `.itx/812/evidence/<host>/`.

## Risk

- **Slow daemon start on a low-spec host.** If the daemon takes >15s to
  bind, the new probe will time out and fail an otherwise-recoverable
  sync. Mitigation: 15s default matches the existing `_verify_health`
  timeout; the macOS path uses 30s. Use **15s on Linux** to start; if
  field reports show false positives, bump it. Operators can re-run
  sync if the daemon just needs another beat.
- **A future agent type without a gateway.** Would have `gateway_port=None`
  from `hosts.json` and skip the probe silently. Acceptable —
  zeroclaw / openclaw / hermes all have gateways today.
- **`/dev/tcp` requires bash, not sh.** The probe explicitly invokes
  `bash -c …`. If a host lacks bash (vanishingly rare on the distros
  we target), the probe surfaces a clear "bash not available" error
  rather than silently misdiagnose.

## Out of Scope

- Refactoring `_verify_health` to merge with `verify_health_macos`.
  Worth doing one day; not now — the two will share a lot.
- Adding an `agent doctor` subcommand. Separate issue.
- Fixing #810 (the install-failed sync-permitted bug). Sibling session.
