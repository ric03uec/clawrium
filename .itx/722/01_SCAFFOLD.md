# Execution Scaffold: OpenCode provider support

## Phase 1: Research

**Goal**: Confirm OpenCode API shape and endpoints.

- [x] Inspect OpenCode source fixture (`models-api.json`) to discover `opencode` / `opencode-go` provider IDs, endpoints, and model lists.
- [x] Confirm env var (`OPENCODE_API_KEY`) and OpenAI-compatible transport.

**Exit criteria**: Have authoritative endpoint URLs and model IDs.

## Phase 2: Provider registration

**Goal**: Make `clawctl` recognize the new types.

- [x] Add `opencode` / `opencode-go` to `PROVIDER_MODELS` in `storage.py`.
- [x] Add model catalog entries to `models.json`.
- [x] Update CLI help strings in `cli/provider.py` and `cli/clawctl/provider.py`.

**Exit criteria**: `validate_provider_type("opencode")` passes; catalog lists the providers.

## Phase 3: Renderer wiring

**Goal**: Produce working on-host configs for all three agent types.

- [x] Add types to `_BEARER_API_KEY_TYPES`, `_AGENT_TYPE_PROVIDER_SUPPORT`, `_HERMES_SUPPORTED_PROVIDERS`, `_ZEROCLAW_PROVIDER_KINDS`, `_OPENCLAW_SUPPORTED_PROVIDERS`.
- [x] Compute `opencode_base_url` in `render_hermes` and pass it to templates.
- [x] Add `opencode` / `opencode-go` branches to hermes config + env templates.
- [x] Update zeroclaw `config.toml` template to emit `base_url` + `api_key`.
- [x] Update openclaw env templates to emit `OPENCODE_API_KEY` and leave model unprefixed.

**Exit criteria**: `render_hermes`, `render_zeroclaw`, and `render_openclaw` produce non-empty, valid output for OpenCode providers.

## Phase 4: Validation and connectivity

**Goal**: Add `clawctl provider verify` support.

- [x] Add `_test_opencode_connectivity` in `validation.py` using the provider's registered endpoint.

**Exit criteria**: `verify_provider_connectivity` returns success on mocked 200 and failure on 401 for both types.

## Phase 5: Tests and quality

**Goal**: Keep the suite green.

- [x] Update `_baseline_inputs` / `_zeroclaw_inputs` and parameterized renderer tests.
- [x] Add explicit render assertions for hermes, zeroclaw, and openclaw.
- [x] Update hard-coded provider lists in `test_core_providers.py`, `test_core_providers_models.py`, and `test_gui_route_providers.py`.
- [x] Add OpenCode connectivity tests.
- [x] Run `make test` and `make lint`; fix failures.

**Exit criteria**: `make lint` passes; `make test` passes except for pre-existing ansible-dependency failures.

## Phase 6: Documentation

**Goal**: Record the change.

- [x] Add `### Added` entry to root `CHANGELOG.md`.
- [x] Commit `.itx/722/` planning artifacts.
