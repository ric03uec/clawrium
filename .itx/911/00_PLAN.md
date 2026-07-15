# #911 — Parameterize hardcoded operator-home paths in the zeroclaw config template

## Issue

`src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
ships with seven keys hardcoded to a specific operator's home,
`/home/clawrium-d01/…`. When `render_zeroclaw` produces
`.zeroclaw/config.toml` for a new agent (e.g. `e2e-zeroclaw`), those
seven daemon-owned paths still resolve to `/home/clawrium-d01/.zeroclaw/…`.
Every zeroclaw agent on every host writes its knowledge db, plugins,
reports, e-stop state, security-ops playbooks + reports, and workspaces
into the same operator's home — cross-agent data collision, and on any
host where that operator does not exist, the daemon fails to open the
paths at all. Also blocks the reproducer in `#913`.

## Root cause

The template was seeded from a real host's rendered config and the
operator-specific home never got parameterized. Every existing test asserts
section presence or key names — none inspects the raw path values — so the
leak survived review and every render matrix run to date.

The seven offending lines (line numbers as of `main` @ 26.7.2):

| Line | Section          | Key                 |
|------|------------------|---------------------|
| 419  | `[knowledge]`    | `db_path`           |
| 601  | `[plugins]`      | `plugins_dir`       |
| 612  | `[project_intel]`| `report_output_dir` |
| 668  | `[security.estop]`| `state_file`       |
| 710  | `[security_ops]` | `playbooks_dir`     |
| 711  | `[security_ops]` | `report_output_dir` |
| 807  | `[workspace]`    | `workspaces_dir`    |

## Fix

1. Replace each hardcoded `/home/clawrium-d01/` with
   `{{ home_root }}/{{ agent_name }}/`.
2. Pass `home_root` into `_render_zeroclaw_config_template`. The variable
   already exists in `render_zeroclaw`'s scope (`/Users` for darwin,
   `/home` for linux — same os_family branch used for
   `slack_mcp_binary` at line ~1505).

Total surface area: one template file, three call-site changes in
`src/clawrium/core/render.py`.

## Definition of done

- All 7 hardcoded paths in the zeroclaw template are parameterized.
- Two new render tests (`test_zeroclaw_config_paths_use_agent_home_linux`,
  `_darwin`) render for `test-agent` and assert:
  - zero occurrences of `clawrium-d01` in the output;
  - every previously-hardcoded key resolves under
    `/home/test-agent/.zeroclaw/…` (linux) or
    `/Users/test-agent/.zeroclaw/…` (darwin).
- One new cross-agent hygiene test
  (`tests/platform/test_template_hygiene.py`) walks every bundled
  agent's `templates/` directory and asserts no forbidden literal
  (starting with `clawrium-d01`) appears anywhere. Prevents the same
  class of bug landing in future agents.
- CHANGELOG under `## [Unreleased] → ### Fixed` references `#911` and
  notes it also recovers `#913`.
- `make lint` + `make test` clean.
- Draft PR opened against `main`; body records UAT-PENDING and lists
  the two real-host targets (wolf-i linux, mac-test darwin).

## Not in scope

- Automated migration for zeroclaw agents that already ran with the
  wrong paths. Their `knowledge.db` / `plugins/` / `workspaces/` sit
  under `/home/clawrium-d01/.zeroclaw/` and will remain there after
  sync. Operators can `mv` manually. Documented in the PR migration
  note.

## Prompt Log

## Execute

**Stage**: execute
**Skill**: (agent-driven — no slash-command invocation)
**Timestamp**: 2026-07-14T21:40:00Z
**Model**: claude-opus-4-7[1m]

```prompt
Ship a draft PR that fixes GitHub issue #911 in the clawrium repo.
(See PR body for full task description.)
```

**Output**: Draft PR `fix(zeroclaw): parameterize hardcoded operator-home paths in config template` opened against `main`.
