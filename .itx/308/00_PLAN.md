# Issue #308 — `clm agent memory edit` (CLI)

## Overview

Add a `clm agent <name> memory edit <file>` command that fetches a memory file
from a remote openclaw agent, opens it in `$EDITOR`, and on a successful save
syncs the content back and (optionally) restarts the agent. This is the
CLI-only first iteration of the Phase 4 "edit" capability from #210; the TUI
flow tracked under #210 will later wrap the same primitives.

All core primitives already exist:

- `clawrium.core.memory.read_memory_file` (issue #307)
- `clawrium.core.memory.write_memory_file` (issue #307)
- `clawrium.core.lifecycle.restart_agent`

The work is **glue + UX**: a new CLI handler in `src/clawrium/cli/memory.py`,
wiring in `src/clawrium/cli/agent.py`, and a comprehensive test pass in
`tests/test_cli_memory.py`. No new core module surface, no new playbook.

## Files to Modify

| File | Change |
|------|--------|
| `src/clawrium/cli/memory.py` | Add `edit_cmd(...)` handler + `_resolve_editor()` + `_run_editor()` helpers. Reuse existing `_resolve_agent_for_memory_cli`, `_stdin_is_tty`. Export `edit_cmd` in `__all__`. |
| `src/clawrium/cli/agent.py` | Add `@memory_app.command(name="edit")` wrapper that delegates to `edit_cmd`. Mirrors existing `memory_show` / `memory_delete` pattern at lines 2113-2146. |
| `tests/test_cli_memory.py` | Add tests covering every acceptance-criteria scenario. |

No new files. No changes to `src/clawrium/core/memory.py` or `lifecycle.py`.

## Implementation Steps

### Step 1 — Editor resolution helper (`cli/memory.py`)

```python
def _resolve_editor(explicit: str | None) -> list[str]:
    """Resolve editor command to argv list.

    Precedence: --editor > $VISUAL > $EDITOR > 'vi'.
    Returned as a list so subprocess.run(...) can be invoked without shell=True.
    Uses shlex.split so users may set 'EDITOR=code --wait' and have it parsed
    safely (still no shell expansion).
    """
```

- Precedence matches git's editor resolution as called out in the issue's
  Implementation Notes.
- `shlex.split` lets users pass flags (e.g. `code --wait`, `nvim -p`) without
  introducing shell injection.
- Final fallback is `["vi"]`. Do **not** silently default to anything that
  could exist as an unexpected binary on PATH.

### Step 2 — Editor invocation helper

```python
def _run_editor(editor_argv: list[str], file_path: str) -> int:
    """Spawn editor as a child process. Returns exit code.

    Wrapped so tests can monkey-patch a single function rather than each
    subprocess.run call site.
    """
    return subprocess.run([*editor_argv, file_path], check=False).returncode
```

`shell=False` is implicit (default). Issue's acceptance criterion explicitly
forbids `shell=True`.

### Step 3 — Main `edit_cmd` handler

Signature:

```python
def edit_cmd(
    claw_name: str,
    file: str,
    editor: Optional[str] = None,
    no_restart: bool = False,
    force: bool = False,
) -> None:
```

Flow (mirrors the issue's "Flow" section verbatim — the issue is the spec):

1. `hostname, agent_name, claw_type = _resolve_agent_for_memory_cli(claw_name)`
   — reuses existing non-memory-capable / not-found rejection. The helper
   returns a 3-tuple (the 2-tuple shim `_resolve_openclaw_for_cli` was
   deleted in #358).
2. `original = read_memory_file(hostname, agent_name, file)`. If `None`,
   print **the same** "Memory unavailable" pair of lines as `show_cmd` and
   `raise typer.Exit(code=1)`. Use the existing wording so error messaging
   is consistent across `show`/`delete`/`edit`.
3. `original_hash = hashlib.sha256(original.encode("utf-8")).digest()` —
   used both for change-detection (step 6) and for conflict detection
   (step 7).
4. Create a temp file:
   - Use `tempfile.NamedTemporaryFile(delete=False, mode="w",
     encoding="utf-8", suffix=Path(file).suffix)` so editors get correct
     syntax highlighting from the suffix.
   - Prefer `dir=os.environ.get("XDG_RUNTIME_DIR")` when that var is set
     and the directory exists; otherwise default tempfile location.
   - Immediately `os.chmod(path, 0o600)` after creation.
   - Wrap the entire post-creation flow in `try` / `finally`; the `finally`
     unconditionally `os.unlink`s the temp path (suppress
     `FileNotFoundError` if the editor deleted it).
5. Write `original` to the temp file, flush, close handle.
6. `exit_code = _run_editor(_resolve_editor(editor), tmp_path)`.
7. Post-edit checks (in order — first-match short-circuits):
   - **Editor exit non-zero** → print `"Editor exited non-zero ({code}). No
     changes."` and `Exit(code=0)`. Non-zero from the editor is a user
     cancellation, not a clm error — exit 0 to match the "no-op" semantics.
   - **Temp file gone** (`FileNotFoundError` on read) → print `"Edit
     cancelled (temp file removed)."` and `Exit(code=0)`.
   - **Content unchanged** (sha256 of new == `original_hash`) → print
     `"No changes."` and `Exit(code=0)`.
8. `new_content = tmp_path.read_text(encoding="utf-8")`.
   `len(new_content.encode("utf-8")) > MAX_MEMORY_CONTENT_BYTES` → print
   `"Error: edit exceeds maximum size (... bytes). Aborted; remote file
   unchanged."` and `Exit(code=1)`. Don't even attempt the write — keep
   the agent's copy of the file pristine.
9. `ok, err = write_memory_file(hostname, agent_name, file, new_content)`.
   On `not ok`, print `f"[red]Error:[/red] {rich_escape(str(err))}"` and
   `Exit(code=1)` — same surface as `delete_cmd`. **No conflict
   detection** — last writer wins. Trade-off explicitly accepted to keep
   the first iteration simple; revisit if it becomes a real problem in
   practice.
10. Restart logic:
    - If `no_restart`: print `f"[green]Saved '{file}' to '{claw_name}'.
      Skipping restart (--no-restart).[/green]"` and return.
    - If `force`: skip prompt, restart immediately.
    - Else: gate on `_stdin_is_tty()`. Non-TTY without `--force` → print
      `"Error: restart requires either --force or an interactive TTY.
      File saved; agent NOT restarted."` and `Exit(code=1)`. (Mirrors the
      `delete_cmd --all` TTY gate. Saving is fine; silently restarting a
      live agent on piped input is not.)
    - On TTY, prompt `typer.confirm(f"Restart agent '{claw_name}' to apply
      changes?", default=False)`. If declined, print `"Saved. Agent not
      restarted; new memory takes effect on next restart."` and exit 0.
11. On confirmed restart, call `restart_agent(hostname, claw_type,
    agent_name=agent_name)` — `_resolve_agent_for_memory_cli` returns
    the claw_type, so this handler now works for any memory-capable
    type (openclaw, hermes, zeroclaw after #358). Surface
    result['success'] / error in the standard `[green]/[red]` style.

### Step 4 — Wire into Typer (`cli/agent.py`)

Add immediately after `memory_delete` (line ~2146), before
`agent_app.add_typer(memory_app, name="memory")` at line 2149:

```python
@memory_app.command(name="edit")
def memory_edit(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    file: str = typer.Argument(..., help="Workspace-relative file (e.g., SOUL.md or memory/2026-05-09.md)."),
    editor: Optional[str] = typer.Option(
        None, "--editor",
        help="Editor command. Defaults to $VISUAL, then $EDITOR, then 'vi'.",
    ),
    no_restart: bool = typer.Option(
        False, "--no-restart",
        help="Save the edit but skip restarting the agent.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Skip the restart confirmation prompt.",
    ),
) -> None:
    """Edit a memory file in $EDITOR; sync changes back and restart agent."""
    from clawrium.cli.memory import edit_cmd

    edit_cmd(
        claw_name=claw_name,
        file=file,
        editor=editor,
        no_restart=no_restart,
        force=force,
    )
```

### Step 5 — Tests (`tests/test_cli_memory.py`)

Add a class `TestMemoryEdit` (or a flat test block) with these cases. Use
the same `hosts_with_installed_claw` fixture used by existing memory
tests. Patch `clawrium.cli.memory._run_editor` to simulate editor
behaviour without spawning a real subprocess.

Required tests (one per acceptance-criteria scenario):

| # | Test | What it asserts |
|---|------|-----------------|
| 1 | `test_edit_happy_path_writes_and_restarts` | TTY=on, `_run_editor` mutates the temp file → confirm prompt accepted → `write_memory_file` called with new content → `restart_agent` called → exit 0, "Saved" + "Restarted" output. |
| 2 | `test_edit_unchanged_does_not_write_or_restart` | `_run_editor` returns 0 without changing the file → "No changes." printed → `write_memory_file` and `restart_agent` NOT called → exit 0. |
| 3 | `test_edit_editor_nonzero_exit_does_not_write` | `_run_editor` returns 1 → "Editor exited non-zero" message → no write/restart → exit 0. |
| 4 | `test_edit_temp_file_deleted_does_not_write` | `_run_editor` deletes the temp file → "Edit cancelled (temp file removed)." → no write/restart → exit 0. |
| 5 | `test_edit_oversized_content_aborts_before_write` | `_run_editor` writes content > `MAX_MEMORY_CONTENT_BYTES`. → exceeds-size error → no write/restart → exit 1. |
| 6 | `test_edit_unreachable_on_initial_read` | `read_memory_file` returns None → "Memory unavailable" → editor never spawned → exit 1. |
| 7 | `test_edit_write_failure_surfaces_error` | `write_memory_file` returns `(False, "playbook failed")` → red error printed → restart NOT called → exit 1. |
| 8 | `test_edit_restart_confirmation_declined` | TTY=on, edit succeeds, prompt input is "n" → write happens, restart NOT called → exit 0. |
| 9 | `test_edit_no_restart_flag_skips_restart` | `--no-restart` → write happens, restart NOT called, no prompt shown → exit 0. |
| 10 | `test_edit_force_skips_confirmation` | `--force`, write succeeds → restart called without prompt → exit 0. |
| 11 | `test_edit_non_tty_without_force_refuses_restart` | Patch `_stdin_is_tty` False, no `--force` → write succeeds, restart refused, error message, exit 1. |
| 12 | `test_edit_temp_file_always_cleaned_up` | After a write failure, assert the temp file path no longer exists. Also assert mode 0o600 while it does exist (capture in the patched `_run_editor`). |
| 13 | `test_edit_rejects_path_traversal` | `<file>=../../../etc/passwd`. Re-uses `_validate_memory_filename` via `read_memory_file` returning None → "Memory unavailable" exit. (Lighter than re-asserting the validator; the gate is enforced inside the core primitive.) |
| 14 | `test_edit_rejects_non_openclaw_agent` | Mirror of `test_show_rejects_non_openclaw_agent`. |
| 15 | `test_edit_no_shell_invocation` | Patch `subprocess.run` directly, assert `shell` not in kwargs OR explicitly False, and that argv is a list. |

Tests 1, 8, 10, 11 require a TTY mock — patch
`clawrium.cli.memory._stdin_is_tty` per the established pattern (see
`test_delete_all_force_refuses_when_stdin_not_tty`).

### Step 6 — Verification

```bash
make format
make lint
make test
```

All must pass. Then update `AGENTS.md` only if there is a CLI surface
catalogue (there is not — skip).

## Test Strategy

- **Unit tests** above cover every acceptance-criteria bullet. The
  `_run_editor` seam is the key to keeping tests fast (no subprocess).
- **Manual smoke** (recommended before commit, not gated):
  1. Install an openclaw on a test host.
  2. `clm agent memory edit <agent> SOUL.md` → modify in `vi` → `:wq` →
     observe restart.
  3. Repeat with `EDITOR='code --wait'` to confirm `shlex.split` parses
     the flag correctly.
  4. `--no-restart`: edit, exit, confirm no restart line in output.
  5. Pipe `yes ""` into `clm agent memory edit ...` (no `--force`) →
     should refuse with the TTY error.

## Risks

| Risk | Mitigation |
|------|------------|
| User sets `$EDITOR` to a non-blocking GUI editor (`code` without `--wait`, `subl` without `-w`). Editor returns immediately, content unchanged → silently treated as no-op. | Document in `--help`: "GUI editors must be invoked with their wait flag (e.g., `--editor 'code --wait'`)." Out of scope to detect. |
| Editor preserves an unrelated trailing newline policy that hash-flips the file → spurious write/restart. | Acceptable. Hash compares raw bytes; if the editor changed the file, it changed the file. |
| `XDG_RUNTIME_DIR` exists but is unwritable. | `tempfile.NamedTemporaryFile` raises `OSError` → caught at top level, surfaced as red error, exit 1. Fallback to default tempfile dir if `XDG_RUNTIME_DIR` is unset. |
| Concurrent-edit race: agent writes to `memory/<today>.md` while user is editing → user's save clobbers the agent's interim writes (or vice versa). | **Accepted** for the first iteration. Last writer wins. Keeps the implementation simple; revisit only if it bites in practice. Diverges from the issue's "Concurrent-edit safety" section — captured below in *Deviations from issue*. |

## Deviations from issue

The issue's "Concurrent-edit safety" section mandates a re-read + hash
compare before write, with a special-case allowlist for identity files.
This plan **drops conflict detection entirely**. Last writer wins.

Rationale: the safety net is partial anyway (race window remains between
re-read and write), the implementation cost is non-trivial (extra
round-trip + branching error paths + 2 extra tests), and the surface
where it actually matters (`memory/<today>.md` while the agent is live)
is narrow. Defer until there's evidence it's needed.

The corresponding acceptance-criterion bullet ("Conflict detection:
re-read before write…") is not satisfied by this plan. Confirm with
issue owner before merging if this matters.

## Subtasks

None — single task execution. Two-file change with a contained test pass.

## Out of Scope (per issue)

- TUI edit flow (Phase 4 of #210).
- 3-way merge / conflict resolution UI.
- Diff preview before write.
- Multi-file edit in one invocation.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-09T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 308
```

</details>
