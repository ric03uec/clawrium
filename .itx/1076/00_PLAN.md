# Issue #1076 — Channels fold into Integrations (OpenClaw-only gate preserved)

## Overview

Discord and Slack messaging collapse their **user-facing surface**
into integrations (one CLI verb group, one on-disk store, one
type catalog entry), but keep their **internal code path**
independent — a dedicated module `core/channels.py` (kept, not
deleted; repurposed from storage-layer to render-layer) owns the
Discord/Slack render logic and is called from the integration
apply path. `core/integrations.py`, `cli/clawctl/integration.py`,
and `core/render.py` do not grow Discord- or Slack-specific
branches; they delegate.

What goes away (user-facing):
- `clawctl channel` + `clawctl agent channel` CLI groups.
- `channels.json` on-disk store.
- `agent.channels[]` list on host records.
- `channel:<name>` secret namespace.

What stays (internal):
- A `core/channels.py` module — but repurposed as a
  render/apply helper, not a storage layer. It exports the
  Discord/Slack config shape, the `inputs → openclaw.json
  channels.discord.*` emitter, and the Slack equivalent. It is
  **only** reachable from the integration apply path; nothing
  else imports it.

This is the D8 bundle: executed after D3 agent removals (#1071)
and D7 description metadata land. Legacy on-disk channel state is
**not migrated** — operators re-attach as integrations under the
wipe-on-upgrade stance stated in the issue.

## Current state (survey)

- `src/clawrium/core/channels.py` (530 LOC) — storage layer:
  `channels.json`, per-agent `channels[]` list on host record,
  secrets at instance key `channel:<name>`.
- `src/clawrium/cli/clawctl/channel.py` (567 LOC) — `clawctl channel
  registry {create,get,describe,update,remove}`.
- `src/clawrium/cli/clawctl/agent/channel.py` — `clawctl agent
  channel {attach,detach,get}`.
- `src/clawrium/cli/clawctl/agent/__init__.py:19,122` — registers
  the `channel` sub-app on `clawctl agent`.
- `src/clawrium/core/render.py`:
  - `ChannelInputs` dataclass (line 215).
  - `RenderInputs.channels` tuple (line 264).
  - `get_agent_channels` → `ChannelInputs` build (lines 634, 798,
    827-834, 1166).
  - Per-agent-type consumers emit channel blocks into the agent's
    rendered config: openclaw's `openclaw.json`
    (`channels.discord.*`, lines 2165-2170, 2641-2666), zeroclaw's
    `config.toml` (`[channels.<type>.<alias>]`, lines 1774-1900),
    hermes/ethos's `.env` (lines 2800-2864).
- `src/clawrium/platform/registry/{hermes,zeroclaw}/manifest.yaml`
  — DEPRECATED `channels:` onboarding stage (already gated out).
- `tests/core/test_channels.py`,
  `tests/cli/clawctl/channel/`,
  `tests/cli/agent/test_configure_no_channel_prompts.py`,
  `tests/cli/clawctl/agent/test_pi_rejections.py`,
  `tests/core/test_render.py` (channel-specific assertions),
  `tests/integration/test_render_matrix.py` (channel inputs).
- `src/clawrium/core/integrations.py` (875 LOC) — target destination.
  Already has `SINGLETON_INTEGRATION_TYPES` (`git`) and
  `SLACK_INTEGRATION_TYPES` (`slack-user`, `slack-cookie` — the
  Slack MCP server, unrelated to channel messaging).
- `src/clawrium/core/lifecycle_canonical.py` — integration apply
  path lives here (`_openclaw_install_plugins`,
  `_hermes_install_slack_mcp`, etc.). This is where the channel
  apply logic needs to land once channels.py is gone.

**Post-#1071 agent set** (confirmed by #1071 title): hermes +
nemoclaw removed. openclaw + zeroclaw survive. Issue #1076 narrows
channel messaging to openclaw only, so zeroclaw channel code is
*also* removed as part of this bundle.

## Approach

### 1. Add `category` to the integration catalog (CLI + GUI surface)

Each entry in `INTEGRATION_TYPES` grows a `category` field. Values
and the type → category mapping:

| Category | Types |
|---|---|
| `channel` | `discord`, `slack` |
| `vcs` | `github`, `gitlab` |
| `project` | `atlassian`, `linear`, `notion` |
| `search` | `brave` |
| `mcp` | `slack-user`, `slack-cookie` |
| `identity` | `git` |

Add a thin query API in `core/integrations.py`:

```python
INTEGRATION_CATEGORIES = ("channel", "vcs", "project", "search", "mcp", "identity")

def types_in_category(category: str) -> list[str]: ...
def category_of_type(integration_type: str) -> str: ...
```

Nothing in the catalog treats any individual type specially — the
new field is pure metadata. Discord/Slack channel semantics still
live in `core/channels.py` behind the integration apply path (see
step 3). Category is the one new cross-type dimension, exposed
identically in CLI and GUI.

**CLI surface changes:**

- `clawctl integration list` adds a `TYPE` column (already
  shown? verify) and a `CATEGORY` column. Rows group / sort by
  category by default.
- `clawctl integration list --category <name>` filters. Invalid
  category → one-line error listing valid categories.
- `clawctl integration create` interactive flow:
  1. Prompt for category (picker from `INTEGRATION_CATEGORIES`).
  2. Prompt for type within that category
     (`types_in_category(category)`).
  3. Prompt for credentials per the type's schema.
  Non-interactive form stays the same:
  `clawctl integration create --type discord <name>` (category
  is inferred; no `--category` flag needed in non-interactive
  mode).
- `clawctl integration registry describe <type>` shows the
  category.

**GUI surface changes:**

- Integrations tab: column for Category, filter dropdown
  populated from `INTEGRATION_CATEGORIES`.
- "Add Integration" modal: two-step picker — Category then Type —
  driven by the same `types_in_category` endpoint.
- New backend route exposing the catalog grouped by category
  (`GET /api/integrations/registry`). Frontend consumes it; no
  category list hardcoded in the SPA.

This is the ONLY place the "channel" concept surfaces to the
operator after this issue — as a category label grouping
`discord` and `slack` in the integration picker.

### 2. Add `discord` + `slack` integration types (catalog only)

Edit `src/clawrium/core/integrations.py:INTEGRATION_TYPES` — add
two entries matching the issue's credential schema:

```python
"discord": {
    "description": "Discord bot for OpenClaw channel messaging",
    "credentials": [
        {"key": "DISCORD_BOT_TOKEN", "description": "...", "required": True},
    ],
},
"slack": {
    "description": "Slack bot for OpenClaw channel messaging",
    "credentials": [
        {"key": "SLACK_BOT_TOKEN", "description": "...", "required": True},
        {"key": "SLACK_APP_TOKEN", "description": "Socket-mode app token (optional)", "required": False},
    ],
},
```

These are the ONLY Discord/Slack-aware edits in
`core/integrations.py`. The file keeps its generic storage API —
no branches on `type == "discord"`. (The openclaw-only attach
gate lives below as a separate constant.)

Add a new `OPENCLAW_ONLY_INTEGRATION_TYPES = frozenset({"discord",
"slack"})` next to `SINGLETON_INTEGRATION_TYPES`.

Extend `add_agent_integration` (or the CLI attach command — pick
the layer that matches how web-UI tunnel gating landed in #1071)
to reject non-openclaw agent types for these two types with the
one-line error: `channels are OpenClaw-only (agent '<name>' is
'<type>')`. The check is one `if integration_type in
OPENCLAW_ONLY_INTEGRATION_TYPES and agent_type != "openclaw":
raise ...` — it does not know about Discord or Slack specifically.

### 3. Repurpose `core/channels.py` as a render module

Keep `src/clawrium/core/channels.py` as a module, rewritten from
scratch. Delete its entire current contents (storage layer,
validation, agent list mutations — all gone). Replace with a
narrow render-oriented API:

```python
# core/channels.py (new shape)

from clawrium.core.integrations import (
    IntegrationInputs,  # existing dataclass
)

# Type set this module handles. The ONLY place Discord/Slack as
# "channel messaging types" are named.
CHANNEL_INTEGRATION_TYPES = frozenset({"discord", "slack"})

def render_discord_channels_toml(
    integrations: tuple[IntegrationInputs, ...],
) -> dict:
    """Return the `channels.discord.*` subtree for openclaw.json
    built from attached discord integrations. Enforces one-per-agent."""

def render_slack_channels_toml(
    integrations: tuple[IntegrationInputs, ...],
) -> dict:
    """Return the `channels.slack.*` subtree."""

def channel_config_schema(integration_type: str) -> dict:
    """Shape of the `config:` sub-dict an operator supplies when
    creating a discord/slack integration (allowed_users,
    allowed_guilds, allowed_channels, require_mention,
    home_channel, stream_mode, ...). Used by the integration CLI
    to prompt / validate."""
```

The config fields currently stored on `channels.json`
(`allowed_users`, `allowed_guilds`, `allowed_channels`,
`require_mention`, `home_channel`, `stream_mode`, etc.) move onto
the integration record's existing `config:` sub-dict. Same shape,
different file, same module owns the schema.

### 4. Rewire render.py to delegate

In `src/clawrium/core/render.py`:

- Delete `ChannelInputs` (line 215) and `RenderInputs.channels`
  (line 264).
- Delete the `get_agent_channels` → `ChannelInputs` build in
  `build_render_inputs` (lines ~634, 798, 827-834, 1166).
- Delete all per-agent-type channel emitters that live on
  non-openclaw code paths (hermes `.env` `channels_dict` block
  2800-2864, zeroclaw `[channels.<type>.<alias>]` block
  1774-1900, dual-channel-of-same-type guard 1381-1391).
- At the openclaw `channels.discord.*` emission point
  (2641-2666), replace the existing body with a one-line
  delegation: `channels["discord"] =
  render_discord_channels_toml(tuple(i for i in
  inputs.integrations if i.type == "discord"))`. Same shape for
  slack.

`render.py` ends up with zero Discord- or Slack-specific
knowledge. The integration apply path (`core/render.py` openclaw
emitter → `core/channels.py`) is the only route by which channel
config lands in `openclaw.json`.

### 5. Delete the channel domain (user-facing surface only)

- `rm src/clawrium/cli/clawctl/channel.py`
- `rm src/clawrium/cli/clawctl/agent/channel.py`
- (Keep `src/clawrium/core/channels.py` — rewritten per step 2.)
- `rm` the on-disk `channels.json` store code path — this is
  inside the old `core/channels.py`, so it disappears when step
  2 rewrites the file.
- Remove the `channel as _channel` import + `agent_app.add_typer`
  call in `src/clawrium/cli/clawctl/agent/__init__.py:19,122`.
- Remove the `channel_app` registration from the top-level
  `clawctl` CLI (check `src/clawrium/cli/clawctl/__init__.py` or
  wherever the top-level app is composed; the __init__.py docstring
  references it but the actual wire-up is likely elsewhere).
- Update the top-level `clawctl` __init__.py docstring to drop
  `channel` from the noun-group list.
- Remove channel references from `src/clawrium/cli/clawctl/agent/describe.py`
  (lines 90-98, 106) and `doctor.py` (lines 122, 146-159, 197,
  244, 276, 299-312) — these render the per-agent `channels` block
  in describe/doctor output.
- Remove the `channels:` deprecated onboarding stage from
  `src/clawrium/platform/registry/hermes/manifest.yaml` (lines
  125-156) and `zeroclaw/manifest.yaml` (lines 84-104). These are
  dead code today but reference `clawctl channel` in comments.
- Remove channel refs from `src/clawrium/core/manifest/differ.py`,
  `src/clawrium/core/lifecycle.py`,
  `src/clawrium/core/lifecycle_canonical.py` if any — the two
  grep hits need visual inspection but are expected to be
  descriptive comments only.
- Remove legacy `clawctl channel` routing from
  `src/clawrium/cli/__init__.py` and `src/clawrium/cli/agent.py`
  (the hybrid pre-#707 CLI paths — these are already partly dead
  per the "clawctl vs legacy CLI split" memory, but any channel
  entry point there must go for the grep-zero criterion to hold).

### 6. Delete channel tests, add integration-channel + category tests

- Delete: `tests/cli/clawctl/channel/` (entire dir),
  `tests/cli/agent/test_configure_no_channel_prompts.py`.
- Rewrite `tests/core/test_channels.py` to target the new
  render-module API (`render_discord_channels_toml`,
  `render_slack_channels_toml`, `channel_config_schema`) driven
  by `IntegrationInputs`, not `ChannelInputs`. Keep the file name
  so the domain's unit-test suite stays easy to locate.
- Update: `tests/core/test_render.py`,
  `tests/integration/test_render_matrix.py`,
  `tests/cli/clawctl/agent/test_pi_rejections.py`,
  `tests/cli/test_non_interactive.py`,
  `tests/cli/clawctl/agent/test_doctor.py`,
  `tests/cli/clawctl/agent/test_doctor_audit.py`,
  `tests/fixtures/audit_2026_05_29.json` — strip channel
  dataclass usage; where tests covered channel render output,
  rewrite to assert the same output comes from an attached
  integration instead.
- Add new tests under `tests/cli/clawctl/integration/` (or
  wherever integration tests already live):
  - `discord` type registers + attach to openclaw renders
    `channels.discord.*` in `openclaw.json`.
  - `slack` type registers + attach to openclaw renders the
    Slack channel block.
  - Attach `discord` to a zeroclaw agent → rejected with the
    `channels are OpenClaw-only` error.
  - Attach `slack` to a zeroclaw agent → same rejection.
  - `types_in_category("channel")` returns `["discord", "slack"]`
    (sorted). `category_of_type("discord") == "channel"`.
  - `clawctl integration list --category channel` filters.
  - `clawctl integration list --category <invalid>` fails with
    the listing-valid-categories error.
  - `GET /api/integrations/registry` returns entries grouped
    (or tagged) by category — single source of truth for the
    GUI picker.

### 7. CHANGELOG + docs

- `CHANGELOG.md` `[Unreleased]`:
  - `### BREAKING` — `clawctl channel` and `clawctl agent channel`
    removed. Legacy `channels.json` records are ignored on
    upgrade. Operators must re-register as integrations:
    `clawctl integration create --type discord <name>` then
    `clawctl agent integration attach <agent> <name>`.
    OpenClaw is the only supported agent type for `discord` and
    `slack` integrations.
- Scan `docs/` + `website/docs/` for every `clawctl channel`
  reference and replace with the integration form. Pay attention
  to the host-preparation and installation mirror pairs — neither
  is touched by channels today, but do verify.

## Files to Modify / Delete

**Delete** (5):
- `src/clawrium/cli/clawctl/channel.py`
- `src/clawrium/cli/clawctl/agent/channel.py`
- `tests/cli/clawctl/channel/` (dir)
- `tests/cli/agent/test_configure_no_channel_prompts.py`
- *(the old `tests/core/test_channels.py` is rewritten, not
  deleted — see Test Strategy below)*

**Modify** (~18):
- `src/clawrium/core/channels.py` — full rewrite from storage
  layer to render module.
- `src/clawrium/core/integrations.py` — add `category` field to
  every type, `INTEGRATION_CATEGORIES`, `types_in_category`,
  `category_of_type`, `discord`+`slack` types, OpenClaw-only gate.
- `src/clawrium/cli/clawctl/integration.py` — add Category column
  to list output, `--category` filter flag, two-step interactive
  create (category → type), category in `registry describe`.
- `src/clawrium/cli/clawctl/agent/integration.py` — surface
  category in attach prompts if that path has an interactive
  picker (verify first).
- `src/clawrium/gui/routes/integrations.py` — new/updated route
  exposing categorized catalog + list filtering.
- `gui/src/app/integrations/...` (SPA source lives at
  `gui/src/`, built into `src/clawrium/gui/frontend/`) —
  Integrations page: add Category column + filter dropdown +
  two-step Add modal (Category → Type). Consumes the new
  `GET /api/integrations/registry` route; no category list is
  hardcoded in the SPA. Rebuild via existing gui build pipeline.
- `src/clawrium/core/render.py` — remove ChannelInputs, delegate
  openclaw emitter to `core/channels.py`.
- `src/clawrium/core/lifecycle_canonical.py` — integration apply
  path, if any new work is needed (likely just removal of channel
  refs).
- `src/clawrium/core/lifecycle.py`,
  `src/clawrium/core/manifest/differ.py` — scrub channel refs.
- `src/clawrium/cli/clawctl/__init__.py` — docstring; group
  wire-up removal.
- `src/clawrium/cli/clawctl/agent/__init__.py` — drop channel
  import + add_typer.
- `src/clawrium/cli/clawctl/agent/describe.py`,
  `src/clawrium/cli/clawctl/agent/doctor.py` — strip channel
  rendering.
- `src/clawrium/cli/__init__.py`, `src/clawrium/cli/agent.py` —
  scrub legacy channel entry points.
- `src/clawrium/platform/registry/hermes/manifest.yaml`,
  `src/clawrium/platform/registry/zeroclaw/manifest.yaml` —
  remove deprecated `channels:` stage.
- Multiple test files (listed above).
- `CHANGELOG.md`.
- `docs/` + `website/docs/` as needed.

## Test Strategy

Unit:

1. `tests/core/test_integrations.py` — new cases for `discord` and
   `slack` type schema, OpenClaw-only gate.
2. Rewrite channel render assertions in `tests/core/test_render.py`
   and `tests/integration/test_render_matrix.py` to drive via
   integration inputs.
3. Grep assertions:
   - `rg -n "clawctl channel\|agent channel\|channels.json\|channel:<" src/
     tests/` → zero hits (acceptance criterion — the CLI groups
     and on-disk store are gone).
   - `rg -n "ChannelInputs\|RenderInputs\.channels\|agent\.channels\[\]" src/ tests/` → zero hits.
   - `rg -n "discord\|slack" src/clawrium/core/render.py` → zero
     hits outside of comments (the delegation-to-channels.py
     invariant — render.py has no Discord/Slack-specific
     knowledge).
   - `rg -n "discord\|slack" src/clawrium/core/integrations.py` →
     only the two type-catalog entries from step 1 (plus the
     unchanged `slack-user` / `slack-cookie` MCP types) — no
     branches on Discord/Slack semantics.
   - `rg -ln "from clawrium.core.channels" src/` → exactly one
     hit: the openclaw emitter in `core/render.py`.

CLI transcript (real-host UAT — required per memory
`no_pr_without_real_host_uat`):

1. On a host with openclaw installed:
   - `clawctl integration create --type discord mydiscord`
     (provide bot token when prompted).
   - `clawctl agent integration attach <openclaw-agent>
     mydiscord`.
   - `clawctl agent sync <openclaw-agent>` — verify
     `~/.openclaw/openclaw.json` on host has the
     `channels.discord.*` block.
2. On a zeroclaw agent:
   - `clawctl agent integration attach <zeroclaw-agent>
     mydiscord` → one-line rejection.

Lint + full test suite: `make lint && make test`.

## Risks

- **Scope coupling to #1071.** Hermes/nemoclaw removal (D3) must
  land first — otherwise the channel-emitter deletions in
  `render.py` for hermes/ethos leave render output broken on
  surviving agents. Verify #1071 is merged before starting.
- **Zeroclaw BC break.** Zeroclaw currently supports Discord
  channels through this system. After this issue, it does not.
  This is intentional per the "channels are OpenClaw-only" gate,
  but it is a real behavior change that must be explicit in the
  `BREAKING` section.
- **openclaw config shape stability.** The `channels.discord.*`
  emitter already deals with only-one-of-same-type-per-agent
  (render.py:2219). Preserve that guard after the integration
  rewire so two attached `discord` integrations fail cleanly.
- **Secret key rename.** Channel tokens live under
  `channel:<name>:DISCORD_BOT_TOKEN`; integration tokens live
  under `integration:<name>:DISCORD_BOT_TOKEN`. The wipe-on-
  upgrade stance says no automatic migration, but the CHANGELOG
  must say so explicitly so operators don't waste time looking.
- **`slack` vs `slack-user`/`slack-cookie` type collision.** The
  new `slack` type is distinct from the existing MCP Slack types.
  Keep the type names exact; do not alias.

## Subtasks

None — single-task execution. The scope is large (~500 LOC removed,
~100 LOC added, ~15 files touched) but all edits are tightly
coupled (removing a domain and rewiring its consumers), so
splitting would just create merge-order friction without buying
parallelism.

## Prompt Log

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-11-26T00:00:00Z
**Model**: claude-opus-4-7

```prompt
plan 1076
```

**Output**: Implementation plan for folding Discord/Slack channels
into the integration domain with an OpenClaw-only gate.
