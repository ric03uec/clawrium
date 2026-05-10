# Issue #210 — Phase 2 Plan

CLI surface for openclaw memory operations. Builds on the Phase 1 core
module shipped in #306.

## Scope

Two commands, mounted under `clm agent <name> memory`:

| Command | Purpose |
|---------|---------|
| `clm agent <name> memory show` | Display total size, workspace path, per-file size table |
| `clm agent <name> memory delete --file <f>` | Delete a single memory file (confirmation unless `--force`) |
| `clm agent <name> memory delete --all` | Delete every existing memory file (refused without `--force`; `--force` still requires typed agent-name confirmation per Gap #6) |

## New files

- `src/clawrium/cli/memory.py` — command implementations
- `tests/test_cli_memory.py` — CliRunner-based tests

## Modified files

- `src/clawrium/cli/agent.py` — register `memory_app` subcommand following the `secret_app` pattern

## UX invariants

- **Resolution**: `get_installed_claw` looks up the agent in hosts.json; an unknown name exits 1 with a clear error.
- **Offline degradation**: `show` distinguishes "agent not found" from "core returned None" (host unreachable, status=installing) so users debugging a still-installing agent do not chase a red herring.
- **Delete safety (Gap #6)**:
  - `--file <f>` deletes one file; prompts unless `--force`.
  - `--all` without `--force` refuses outright.
  - `--all --force` still requires a typed confirmation matching the agent name. This mirrors how cloud consoles gate destructive bulk operations.
- **Size formatting**: bytes → human-readable (B / KB / MB).

## Out of scope (Phase 3+)

- TUI MEMORY card (Phase 3)
- TUI edit → sync → restart (Phase 4)
- Compaction/truncation (separate follow-up issue)
