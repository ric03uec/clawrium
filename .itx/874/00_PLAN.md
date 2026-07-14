# Implementation Plan — Issue #874

**Customer outcome**: After installing Clawrium, the user can bring up the local GUI with a single command (`clawctl server start`) and manage its lifecycle with `stop` / `status` / `run`.

## Scope (Locked)

- **No auto-start.** Installation flow (`uv tool install clawrium`) is unchanged. User explicitly runs `clawctl server start`.
- **POSIX only.** Linux + macOS. Two PRs — this plan is Linux (PR 1); PR 2 will remove the darwin guard and record the mac-test UAT.
- **Port 36000 required.** No auto-pick, no port fallback. If :36000 is occupied by a foreign process, fail loudly with a clear error and exit 1.
- **`clawctl gui` is deleted outright.** No alias, no deprecation. This is a documented BREAKING change.
- **`clawctl server {start,stop,status,run}`** is the sole surface. No REST API in this iteration (deferred to #367).

## Current State

- `src/clawrium/cli/gui.py:14` runs foreground uvicorn on `127.0.0.1:36000`, opens the browser via `threading.Timer`.
- Registered as `clawctl gui` in `src/clawrium/cli/__init__.py:79`.
- No PID file, no detached mode.
- FastAPI app object at `clawrium.gui.server:app` — reused unchanged.

## Files

**New**
- `src/clawrium/cli/clawctl/server/__init__.py` — Typer sub-app, registered as `server`.
- `src/clawrium/cli/clawctl/server/start.py` — detached spawn, state-file write, 36000-occupied guard, idempotent behavior when PID file is alive.
- `src/clawrium/cli/clawctl/server/stop.py` — SIGTERM → wait → SIGKILL fallback → unlink state file.
- `src/clawrium/cli/clawctl/server/status.py` — read state file, probe PID alive + TCP :36000, print host/port/URL/status.
- `src/clawrium/cli/clawctl/server/run.py` — foreground uvicorn on 127.0.0.1:36000 (systemd/Docker mode; no state file writes).
- `src/clawrium/core/server_lifecycle.py` — reusable PID file mgmt, detached `Popen(start_new_session=True)`, TCP probe, health check. Isolated for testability.
- `tests/cli/clawctl/test_server.py` — CliRunner smoke for each subcommand.
- `tests/core/test_server_lifecycle.py` — unit tests for state-file round-trip, stale-PID detection, port probe, idempotency.

**Modify**
- `src/clawrium/cli/clawctl/__init__.py` — register `server` group.
- `src/clawrium/cli/__init__.py` — remove `gui_cmd` entry (lines ~62–98); no replacement wrapper.
- `CHANGELOG.md` `[Unreleased]`:
  - `### Added` — `clawctl server {start,stop,status,run}` group.
  - `### BREAKING` — `clawctl gui` removed. Migration: run `clawctl server start`. No automated migration.
- `docs/installation.md` — add "Start the GUI" section pointing at `clawctl server start`.
- `website/docs/installation.md` — mirror body verbatim per AGENTS.md rule.

**Delete**
- `src/clawrium/cli/gui.py` — replaced by `server/run.py` (foreground) + `server/start.py` (detached). Browser-open logic dropped; user opens the printed URL themselves.

## State File

`~/.config/clawrium/server.json`:

```json
{
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 36000,
  "url": "http://127.0.0.1:36000",
  "started_at": "2026-07-12T10:30:00Z"
}
```

Config dir resolution reuses whatever mechanism the rest of clawrium already uses (`platformdirs` or the project's own `CLAWRIUM_CONFIG` env var — matched to whatever the existing codebase does; will confirm during execute).

## Command Contracts

| Command | Behavior |
|---|---|
| `server start` | 1) Read state file. If PID alive → print `Server already running at http://127.0.0.1:36000` (exit 0, idempotent). 2) Probe `:36000`. If occupied by foreign process → `error: port 36000 already in use` + exit 1. 3) `subprocess.Popen([sys.executable, "-m", "uvicorn", ...], start_new_session=True, stdout/stderr → log file)`. 4) Wait up to 5s for TCP :36000 to accept. 5) Write state file. 6) Print URL. |
| `server stop` | 1) Read state file. If absent → `Server is not running` (exit 0). 2) `os.kill(pid, SIGTERM)`, wait up to 5s. 3) If still alive → `SIGKILL`. 4) Unlink state file. 5) Print confirmation. |
| `server status` | 1) Read state file. If absent → `stopped` (exit 0). 2) Probe PID + TCP :36000. 3) Print table: status, host, port, URL, PID, uptime. |
| `server run` | Foreground `uvicorn.run(...)` on 127.0.0.1:36000. No state file writes. Ctrl-C stops. Intended for systemd/Docker/`--foreground` use. |

## Detached Process Model

- `subprocess.Popen(cmd, start_new_session=True, stdout=log, stderr=log, stdin=DEVNULL)` — the standard POSIX daemon pattern. Works identically on Linux and macOS. No `os.fork()` double-fork required for this use case; the parent shell exits, the process is orphaned to init cleanly.
- Log file: `~/.config/clawrium/logs/server.log` (append, truncate on start). No rotation in v1.
- Health check after spawn: poll `socket.connect(("127.0.0.1", 36000))` up to 5s at 100ms cadence. If probe fails, kill the child, unlink state, print startup error + last 20 log lines, exit 1.

## Platform Gate (PR 1)

At the top of `server_lifecycle.py`:

```python
if sys.platform not in ("linux",):
    raise typer.Exit("clawctl server is Linux-only in this release. macOS support ships in a follow-up PR.")
```

Removed in PR 2.

## Test Strategy

**Unit** (`tests/core/test_server_lifecycle.py`):
- State-file round-trip.
- Stale-PID detection (PID file exists but process gone).
- TCP port probe: free vs. occupied.
- Idempotent `start` when already running.
- `start` fails loud when :36000 held by foreign process.
- Detached-spawn interface (mock `Popen`; assert `start_new_session=True`).

**CLI smoke** (`tests/cli/clawctl/test_server.py`):
- `CliRunner` invocation of each subcommand under isolated `CLAWRIUM_CONFIG` tmp dir.
- Exit codes + stdout format.
- `start` → `status` → `stop` full lifecycle.

**Real-host UAT** (per no-PR-without-real-host-UAT memory):
- Linux host: fresh `uv tool install clawrium` from the branch, run `clawctl server start`, hit `http://127.0.0.1:36000`, verify fleet view loads.
- `clawctl server status` shows running with correct URL.
- `clawctl server stop` cleanly stops.
- Re-run `clawctl server start` after stop: idempotent success.
- Occupy :36000 with `nc -l 36000` and verify `start` errors cleanly.
- `clawctl gui` errors with `No such command` (breaking-change confirmation).

## Acceptance Criteria (Reworded to Match Scope)

- [ ] `clawctl server start` starts the GUI server on `127.0.0.1:36000`; second call while running is a no-op with a clear message.
- [ ] `clawctl server stop` stops cleanly; second call is a no-op with `not running`.
- [ ] `clawctl server status` prints running/stopped, host, port, URL, PID.
- [ ] `clawctl server run` runs in the foreground (blocking).
- [ ] Server binds `127.0.0.1` only.
- [ ] Port 36000 in use → clear error, exit 1, no state file written.
- [ ] `clawctl gui` no longer exists (BREAKING, documented in CHANGELOG).
- [ ] `make test` covers lifecycle + idempotent start + status + port-in-use failure.
- [ ] Existing GUI routes / auth / fleet view unchanged.
- [ ] Installation docs updated to mention `clawctl server start` as the next step.

## Risks

- **Detached process on macOS**: same POSIX primitives, but PR 2 must UAT on `mac-test` because launchd's session semantics differ subtly. Deferred to PR 2.
- **`uvicorn` on PATH**: detached spawn uses `subprocess.Popen([sys.executable, "-m", "uvicorn", ...])` — never relies on `uvicorn` binary being on PATH.
- **Config-dir race**: `os.makedirs(..., exist_ok=True)` before opening log file.

## Subtask Decision

Single-issue execution. No subtasks. Files are tightly coupled through `server_lifecycle.py`.

## PR Split Reminder

- **PR 1 (this plan)**: Linux + platform guard. Ship first, ATX review required.
- **PR 2 (follow-up)**: Remove the guard, add macOS UAT record on `mac-test`. Open after PR 1 merges.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-12T00:00:00Z
**Model**: claude-opus-4-7

```prompt
874. plan only. no file creation
```

Follow-ups from user:
- No auto-start; keep install as-is; user runs `clawctl server start`.
- Linux + macOS as two PRs.
- Port 36000 must work (no auto-pick).
- Status shows IP+URL.
- Delete `clawctl gui` outright, no deprecation.
- Create plan in a worktree; execute via `/itx-execute` in the worktree; use `atx` CLI for review.

</details>
