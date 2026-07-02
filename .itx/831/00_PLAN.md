# Issue #831 — Hermes litellm `context_length` rendering

## Customer outcome

Operators who attach a litellm-typed provider to a hermes agent and set a
`context_window` on the provider record see the rendered
`~/.hermes/config.yaml` emit `model.context_length: <window>` so the
hermes daemon uses the proxy's actual context capacity instead of a
silent ~65k fallback.

## Why now

`clawrium-gtm` on `wolf-i` is attached to a litellm proxy fronting
Qwen3-Next-80B (`max_input_tokens=131072`) but hermes is operating with
a ~65k window. Upstream hermes docs document `model.context_length` as
the supported override for `provider: custom`, but clawrium's renderer
does not emit it today.

## Scope

### In
- `ProviderInputs.context_window` already exists; reuse — no new field.
- `AttachedProviderInputs` gains `context_window: int = 0` for aux slots.
- `build_render_inputs` populates aux `context_window` from each aux
  litellm provider's `providers.json` record.
- `render_hermes` passes `provider.context_window` + aux attachments
  through to template context (no new template var beyond existing
  attachment list).
- Template `hermes-config.canonical.yaml.j2`: litellm branch (primary
  + aux-loop litellm path) emits `context_length` conditionally on
  truthy value; omitted entirely otherwise.
- CLI: `clawctl provider registry create --type litellm
  --context-window N` and `clawctl provider registry edit … --context-window
  N` write `providers.json.<name>.context_window`. Flag is rejected for
  non-litellm types (parity with `--litellm-url`).
- Tests: byte-locked render tests (4 cases) + CLI roundtrip (create +
  edit).
- Changelog: `### Added` entry under `[Unreleased]`.

### Out (explicit non-goals)
- `max_tokens` (output cap) — separate knob, tracked separately if
  needed.
- openclaw / zeroclaw render paths and templates.
- workspace overlay (hermes excludes `config.yaml` by design).
- gateway bearer rotation (sync on hermes does not rotate; rotation is
  zeroclaw-only per memory note).

## Product output

```yaml
# .hermes/config.yaml (litellm primary, context_window=131072)
model:
  provider: "custom"
  base_url: "http://192.168.1.17:4000/v1"
  api_key: 'sk-…'
  default: 'writer'
  context_length: 131072
```

When `context_window` is unset on the provider record, the
`context_length` line is absent — no `null`, no `0`.

## Technical details

### Files modified
- `src/clawrium/core/render.py`
  - `AttachedProviderInputs`: add `context_window: int = 0` (frozen
    dataclass field).
  - `build_render_inputs` (hermes branch): when assembling
    `AttachedProviderInputs`, pull `context_window` from each entry's
    `providers.json` record (`int(entry_record.get("context_window") or
    0)`).
- `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2`
  - Litellm branch (lines 132-159): emit `context_length: …` after
    `default:` when truthy. Mirror in aux loop where `entry.type ==
    'litellm'`.
- `src/clawrium/cli/clawctl/provider.py`
  - `create`: add `--context-window` int option; persist to record when
    type is litellm; reject for other types.
  - `edit`: add `--context-window` int option; reject for non-litellm.
- `CHANGELOG.md`: one `### Added` line.

### Tests added (`tests/core/test_render.py`)
1. `test_hermes_litellm_primary_no_context_window_omits_context_length`
2. `test_hermes_litellm_primary_with_context_window_emits_context_length`
3. `test_hermes_litellm_aux_with_context_window_emits_context_length`
4. `test_hermes_openrouter_with_litellm_aux_only_aux_emits_context_length`
   (regression guard that openrouter primary stays clean)

### CLI tests (`tests/cli/clawctl/test_provider.py` or equivalent)
- Create roundtrip: `--context-window 131072` persisted to
  providers.json.
- Edit roundtrip: starts unset → edit `--context-window 131072` → stored.
- Reject on non-litellm: `--context-window` on `--type anthropic` exits
  non-zero.

### Risks / contracts
- `provider.context_window` is `int = 0` (zero means renderer default).
  Template branches on truthiness, so `0` is treated as "unset". This
  matches the openclaw render path semantics already in tree.
- No changes to env file rendering — `context_length` is YAML-only.
- Aux `AttachedProviderInputs.context_window` defaults to 0 for any
  caller that builds the struct by hand (preserves existing tests'
  byte locks for non-litellm cases).

## Verification

- `make lint && make test`
- Real-host UAT on `clawrium-gtm` (wolf-i):
  1. `clawctl provider registry edit clawrium-gtm-litellm --context-window 131072`
  2. `clawctl agent sync clawrium-gtm`
  3. Verify rendered YAML on host contains `context_length: 131072`
  4. `clawctl agent doctor clawrium-gtm` → Status: ok
  5. `clawctl agent restart clawrium-gtm` → dashboard back up

## ATX review

`.claude/itx-config.json` has `mcp.review_enabled: true`. Request ATX
review iterations after first commit, document each round in PR body.
