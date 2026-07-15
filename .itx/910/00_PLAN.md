# Implementation Plan — #910

## Issue

`fix(zeroclaw): config template hardcodes completed_sections = [] — chat broken after sync`

After `clawctl agent sync` on a zeroclaw agent, `clawctl agent chat`
fails with a "Quickstart" protocol error because the rendered
`~/.zeroclaw/config.toml` overwrites `[onboard_state] completed_sections`
with `[]`. The zeroclaw daemon tracks onboarding completion in that
section at runtime; wiping it forces the daemon back into pre-onboard
state, refusing chat.

## Root Cause

Template `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2:579-580`:

```jinja
[onboard_state]
completed_sections = []
```

The literal `[]` is not driven by any variable. Every `configure` /
`sync` re-renders the file and writes an empty list, discarding the
daemon's live state.

- `_render_zeroclaw_config_template` in `src/clawrium/core/render.py:1621`
  receives no onboarding context.
- `render.py`'s docstring (line 12) explicitly requires renderers to
  stay pure functions with zero I/O, so the remote read must happen
  outside the renderer.
- Remote read machinery already exists: `read_remote_file` +
  `diff_files` in `src/clawrium/core/render_diff.py:185`, invoked
  after render from `sync_agent_canonical`
  (`lifecycle_canonical.py:2043`).

## Approach

**Preserve the on-host `[onboard_state] completed_sections` array
across renders.** Fresh installs render `[]`; sync/reconfigure reads
whatever is currently on the host and threads it back through render
context.

### Files to Modify

| File | Change |
|---|---|
| `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2` | Replace literal `[]` with `{{ onboard_completed_sections \| default([]) \| tojson }}` |
| `src/clawrium/core/render.py` | Extend `ZeroclawRenderInputs` (or the local kwargs struct) with `onboard_completed_sections: list[str] = field(default_factory=list)`; thread it into `_render_zeroclaw_config_template` context |
| `src/clawrium/core/lifecycle_canonical.py` | **Before** calling `renderer(inputs, os_family=...)` for zeroclaw, read the on-host `~/.zeroclaw/config.toml`, parse `[onboard_state].completed_sections`, and set `inputs.onboard_completed_sections`. On first sync (file absent) fall back to `[]`. |
| `src/clawrium/core/render_diff.py` (or new helper) | Small helper `read_remote_toml(host, remote_path) -> dict | None` — thin wrapper over `read_remote_file` + `tomllib.loads`, returns `None` on absent file. Existing `RemoteReadError` handling reused. |

### Steps

1. Add `read_remote_toml` helper (10 LOC) alongside `read_remote_file`.
   Returns `None` when file absent, propagates `RemoteReadError` on
   ssh failures. Parses via `tomllib` (stdlib, 3.11+).
2. Add `onboard_completed_sections: list[str]` field to the zeroclaw
   render inputs dataclass. Default `[]`. Type: list of strings.
3. Thread the field into `_render_zeroclaw_config_template` context.
4. Update the template line to `completed_sections = {{ onboard_completed_sections | tojson }}`.
5. In `sync_agent_canonical` (zeroclaw branch, before the
   `renderer(...)` call): call `read_remote_toml`, extract
   `["onboard_state"]["completed_sections"]` defensively (missing
   section → `[]`, non-list value → `[]` with a debug log). Assign
   onto `inputs.onboard_completed_sections`.
6. `configure_agent` path: leave unchanged (first install has no
   remote file; the default `[]` is correct).

### Test Strategy

Unit tests in `tests/platform/test_render_zeroclaw.py`:

1. `test_onboard_state_defaults_empty_on_first_render` — no context
   value → template emits `completed_sections = []`. Regression fence
   for fresh installs.
2. `test_onboard_state_preserved_when_supplied` — context
   `["memory","providers","identity","channels","validate"]` →
   template emits that list verbatim.
3. `test_onboard_state_quoting` — sections with unusual chars are
   json-quoted correctly (defensive against future daemon changes).

Unit test in `tests/core/test_render_diff.py`:

4. `test_read_remote_toml_absent_file_returns_none`.
5. `test_read_remote_toml_parses_valid_body`.
6. `test_read_remote_toml_propagates_ssh_error`.

Unit test in `tests/core/test_lifecycle_canonical.py`:

7. `test_sync_zeroclaw_preserves_onboard_state` — stub remote reader
   returning a config with 3 completed sections; assert
   `inputs.onboard_completed_sections` reaches the renderer with all 3.
   **Also assert `gateway_token_rotated` event is emitted** per
   AGENTS.md gateway-token-lifecycle contract (issue #437 — sync
   always rotates, no skip path). Follow the pattern in
   `test_zeroclaw_sync_restart_false_still_repairs_bearer` at
   `tests/core/test_lifecycle_canonical.py:828`.
8. `test_sync_zeroclaw_first_sync_defaults_empty` — stub reader
   returning `None`; assert renderer sees `[]` **and** the
   `gateway_token_rotated` event is emitted (same rotation contract).

## Definition of Done

- [ ] Template no longer hardcodes `completed_sections = []`.
- [ ] `sync` reads remote `[onboard_state].completed_sections` and
      preserves it across re-render.
- [ ] `configure` (first install) still emits `completed_sections = []`.
- [ ] All new unit tests pass; existing `make test` suite passes.
- [ ] `make lint` clean.
- [ ] Real-host UAT on wolf-i:
  - Create a fresh zeroclaw agent → configure → sync → start → chat
    responds without "Quickstart" error.
  - Run `sync` a second time — chat still works, no re-onboarding.
  - `grep completed_sections ~/.zeroclaw/config.toml` shows the
    populated list after the second sync.
- [ ] CHANGELOG entry under `[Unreleased] → Fixed`, referencing #910.
- [ ] Draft PR opened, linked from #910, marked ready once UAT recorded
      in the PR body per project rule.

## Risks / Non-Goals

- **Non-goal:** exposing `completed_sections` in `clawctl agent describe`
  output. The control plane (`hosts.json`) has its own onboarding
  state; zeroclaw's on-host `[onboard_state]` is a daemon-internal
  concern.
- **Risk:** if a future zeroclaw release renames `[onboard_state]` or
  changes the field shape, the preserve step becomes a no-op. Mitigated
  by defensive extraction (missing section or wrong type → `[]`) with
  a debug log; sync does not fail.
- **Risk:** two operators running `sync` concurrently could race on
  the toml file. Existing sync path already races on the whole config
  file — this change does not widen the window.

## Prompt Log

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-14T14:35:00Z
**Model**: claude-opus-4-7[1m]

```prompt
reivew all agent-created isues in last 24 hours one by one and validate if they'er real. if they are add a plan to fix them adn sned prs for the plan use /itx-plan-create for each of these witch lear definition of done
```

**Output**: `.itx/910/00_PLAN.md` — implementation plan for preserving
zeroclaw `[onboard_state].completed_sections` across renders.
