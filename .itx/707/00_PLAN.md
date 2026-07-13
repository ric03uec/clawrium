# Issue #707 — Remove legacy `clm` CLI + parallel `cli/` modules

## Scope

Issue #707 tracks the removal of ~9,200 LOC of hybrid `src/clawrium/cli/*.py`
modules left over after `cli/main.py` and its tests were deleted in #706.
The removal is phased — several modules are still imported by live
`clawctl/`, `tui/`, or test code and require real refactor work before
they can go.

## Dependency audit (2026-07-13)

Grep for `from clawrium.cli.<mod>` / `clawrium.cli.<mod> import` across
`src/` and `tests/`, excluding legacy siblings under `src/clawrium/cli/*.py`:

| Legacy file | LOC | Live importers (outside legacy siblings) |
|---|---:|---|
| `cli/skill.py`       |   189 | **none** |
| `cli/host.py`        | 1,041 | **none** |
| `cli/integration.py` |   590 | **none** |
| `cli/provider.py`    | 1,091 | **none** |
| `cli/agent.py`       | 3,317 | `tests/cli/agent/test_legacy_discord_channels_block.py` |
| `cli/agent_skill.py` |   352 | `tests/test_cli_agent_skill.py` |
| `cli/chat.py`        |   956 | `cli/tui/widgets/chat_panel.py` (`_sanitize_exception_text`), `cli/clawctl/agent/chat.py` (`chat as _legacy_chat`) |
| `cli/install.py`     |   360 | `cli/agent.py`, `tests/test_install_prompts.py` |
| `cli/memory.py`      |   518 | `cli/agent.py` |
| `cli/registry.py`    |   163 | `cli/agent.py` |
| `cli/secret.py`      |   217 | `cli/agent.py` |
| `cli/status.py`      |   287 | `cli/agent.py` |
| `cli/init.py`        |    58 | `cli/service.py` (live `clawctl service init`) |

## Phased plan

### Phase 1 (this PR) — pure orphans

Delete files with **zero** importers anywhere in the tree:

- `src/clawrium/cli/skill.py`
- `src/clawrium/cli/host.py`
- `src/clawrium/cli/integration.py`
- `src/clawrium/cli/provider.py`

Net delta: **-2,911 LOC**, zero migration, zero risk.

### Phase 2 (follow-up) — `cli/agent.py` cluster

`cli/agent.py`, `cli/agent_skill.py`, `cli/memory.py`, `cli/registry.py`,
`cli/secret.py`, `cli/status.py`, `cli/install.py` form a closed cycle:
the only non-legacy importer of any of them is the single test file
`tests/cli/agent/test_legacy_discord_channels_block.py` +
`tests/test_cli_agent_skill.py` + `tests/test_install_prompts.py`.

Steps:
1. Confirm the discord-channels block, agent_skill CLI, and install prompts
   are already exercised through the wired `clawctl` code paths (or migrate
   the tests to hit the live paths).
2. Delete the cluster in one commit.

### Phase 3 (follow-up) — `cli/init.py` + `cli/service.py`

Inline the ~40 lines of `cli/init.py` implementation into `cli/service.py`
(or move to `core/`) and delete `cli/init.py`.

### Phase 4 (follow-up) — `cli/chat.py`

Real migration. Move `_sanitize_exception_text` to `core/` (or
`cli/_shared/`); either promote the legacy `chat()` function into
`clawctl/agent/chat.py` or extract shared helpers to `core/`.
Update `cli/tui/widgets/chat_panel.py` + `cli/clawctl/agent/chat.py`
importers, then delete `cli/chat.py`.

## Why phased

The issue body itself says: *"Land as a multi-commit PR or a sequence
of small PRs."* Bundling ~9K LOC + real refactor work into a single PR
would be un-reviewable and un-revertable. Phase 1 is the safe base
case; every subsequent phase requires a distinct migration and is best
reviewed in isolation.
