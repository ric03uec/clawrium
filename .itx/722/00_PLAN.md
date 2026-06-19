# Plan: OpenCode inference provider support

## Issue

#722 — User can configure OpenCode as an inference provider for agents

## Customer Outcome

User can add an OpenCode provider (`opencode` / `opencode-go`) and attach it to hermes, zeroclaw, or openclaw agents, with `clawctl agent configure` rendering a working on-host config.

## Background

OpenCode exposes two hosted OpenAI-compatible gateways under one API key (`OPENCODE_API_KEY`):

- `opencode` — `https://opencode.ai/zen/v1`
- `opencode-go` — `https://opencode.ai/zen/go/v1`

Both use the standard `@ai-sdk/openai-compatible` shape: a `base_url`, bearer `api_key`, and model ID.

## Proposed Solution

1. Register `opencode` and `opencode-go` in `PROVIDER_MODELS` with their default endpoints and API-key requirements.
2. Add model catalog entries for both providers in `models.json`.
3. Add the types to all renderer allow-lists (`_HERMES_SUPPORTED_PROVIDERS`, `_ZEROCLAW_PROVIDER_KINDS`, `_OPENCLAW_SUPPORTED_PROVIDERS`, `_AGENT_TYPE_PROVIDER_SUPPORT`, `_BEARER_API_KEY_TYPES`).
4. Render the on-host configs:
   - **hermes**: `provider: "custom"` with `base_url`, inline `api_key`, and `HERMES_INFERENCE_PROVIDER='custom'` in `.env`.
   - **zeroclaw**: `[providers.models.<type>]` with both `base_url` and `api_key`.
   - **openclaw**: `OPENCODE_API_KEY` in `.openclaw/env`, unprefixed model ID in `openclaw.json`.
5. Add connectivity tests (`verify_provider_connectivity`) hitting `<endpoint>/models`.
6. Update CLI help text and hard-coded test assertions.

## Acceptance Criteria

- [x] `clawctl provider registry create myoc --type opencode` succeeds and validates the model ID.
- [x] `clawctl agent configure <agent>` renders a valid config for hermes/zeroclaw/openclaw when attached to an OpenCode provider.
- [x] `make test` passes (modulo pre-existing environment failures).
- [x] `make lint` passes.

## Files Changed

- `src/clawrium/core/providers/storage.py`
- `src/clawrium/core/providers/models.json`
- `src/clawrium/core/render.py`
- `src/clawrium/core/validation.py`
- `src/clawrium/cli/provider.py`
- `src/clawrium/cli/clawctl/provider.py`
- `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2`
- `src/clawrium/platform/registry/hermes/templates/hermes-env.canonical.j2`
- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
- `src/clawrium/platform/registry/openclaw/templates/openclaw-env.canonical.j2`
- `src/clawrium/platform/registry/openclaw/templates/.env.j2`
- `tests/core/test_render.py`
- `tests/test_core_providers.py`
- `tests/test_core_providers_models.py`
- `tests/test_core_validation.py`
- `tests/test_gui_route_providers.py`
- `CHANGELOG.md`
