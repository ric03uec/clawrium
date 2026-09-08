# Issue #985 — Execution Log

Bump zeroclaw upstream pin from v0.8.2 → v0.8.5.

## Changes

- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2` — removed retired `[node_transport]` block; replaced with a 2-line hint comment referencing the upstream deprecation.
- `src/clawrium/platform/registry/zeroclaw/manifest.yaml` — added 5 v0.8.5 platform rows (armv7l Debian 13, aarch64 Ubuntu 22.04/24.04, x86_64 Ubuntu 22.04/24.04) with SHA256s sourced from `https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.8.5/SHA256SUMS`.
- `src/clawrium/core/render.py` — comment wording tweaks (`0.8.2` → `≥0.8.2`) at two hot spots to reflect the version floor is now a range.
- `tests/core/fixtures/zeroclaw_config_*.toml` (7 files) — regenerated from the current render output to match the template change.
- `tests/test_registry_zeroclaw.py` — added `0.8.5` to `supported_versions`.
- `tests/cli/clawctl/agent/test_upgrade.py` — bumped two "manifest max" test writes from `0.8.2` → `0.8.5`.
- `tests/cli/clawctl/provider/test_agent_attach_zeroclaw_litellm.py` — bumped a fleet fixture pin from `0.8.2` → `0.8.5` for consistency (ATX W2).
- `CHANGELOG.md` — BREAKING entry (with explicit upgrade-order guidance) + Changed entry.

## Verification

- `make lint` — clean.
- `make test` — 4851 passed / 2 skipped.
- Real-host UAT on wolf-i (x86_64):
  - `clawctl agent upgrade e2e-zeroclaw --yes --skip-drift-check` → binary v0.8.5 installed.
  - `clawctl agent sync e2e-zeroclaw` → drift=0, unit restarted, gateway re-paired.
  - `zeroclaw --version` → `0.8.5`.
  - `zeroclaw config migrate` → `Config already at current schema version` (no parse errors, zero silent-reset warnings).
  - `zeroclaw doctor` → provider healthy, 431 openrouter models fetched, all `[providers]` and `[cron]` checks green.
  - `clawctl agent chat --once "say only OK"` with a working provider attached → `OK` (round-trip verified end-to-end).

## Post-open regression fix (iteration 2)

The initial iteration removed only `[node_transport]`. Follow-up UAT surfaced two additional v0.8.5 schema breaks that this iteration also drops:

- `[providers]` root with inline `fallback = "..."` — retired; daemon silently reset entire `[providers]` block to defaults.
- Root-level `[cron]` fields (`catch_up_on_startup`, `enabled`, `jobs`, `max_run_history`) — restructured as a map of named `CronJobDecl` sub-tables; clawrium ships none, so the root block is now omitted entirely.

Both discovered via `zeroclaw config migrate` on wolf-i after the initial upgrade.

## ATX

- Session `c9793a22-d138-4484-a546-fda885d81ad4`, iteration 1, rating **3.5/5**, no blockers.
- 2 warnings addressed in-branch (W2 fixed, W1 CHANGELOG guidance tightened).
- Iteration 2 (this fix commit) not re-run through ATX — the fix follows the same pattern (drop obsolete section, regenerate fixtures) and was verified end-to-end on wolf-i.

## Prompt Log

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-09-08T21:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 985
```

**Output**: Bumped zeroclaw manifest to v0.8.5, dropped retired `[node_transport]` block, regenerated 7 fixtures, updated 3 test files, expanded CHANGELOG. Live-verified on wolf-i.
