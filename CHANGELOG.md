# Changelog

All notable changes to this project are documented here. Per-release frozen
archives live under [`docs/releases/`](docs/releases/) — that directory is
the single place to read the full history of what shipped in each version.

The project follows a `YY.M.PATCH` calendar versioning convention; the
`## [Unreleased]` section below is the working log for the next release
cut. The `itx:release` skill archives this section into a new
`docs/releases/<version>/CHANGELOG.md` and resets this file to an empty
`[Unreleased]` template on every release.

## [Unreleased]

### BREAKING

- The legacy `clm` CLI entry point has been removed. The wired CLI is now exclusively `clawctl`. (#706)
  - **No automated migration.** Update scripts, shell aliases, and CI invocations from `clm <command>` to `clawctl <command>`. Argument surfaces are unchanged — only the binary name differs.
  - The same cleanup removed 21 legacy test files. Out-of-tree integrations that targeted `src/clawrium/cli/main.py` must be re-pointed at `src/clawrium/cli/clawctl/`.
  - **No compatibility shim.** If you cannot migrate immediately, pin `clawrium==26.6.1` (the last release that ships the `clm` entry point) until your scripts and aliases are updated.

### Added

- New `litellm` provider type for OpenAI-compatible proxies (LiteLLM, vLLM, etc.). `clawctl provider add --type litellm --url <proxy> --model <id>` registers a provider with a bearer master key; `clawctl provider refresh` populates `available_models` from the proxy's `/v1/models` endpoint. Supported on hermes agents — `render_hermes` emits `provider: "custom"` with `base_url: <url>/v1` (matching the existing ollama OpenAI-bypass shape) plus `LITELLM_API_KEY=` for the primary attachment and `LITELLM_<ROLE_UPPER>_API_KEY=` for each auxiliary attachment. (#705)

### Changed

- Hermes bedrock multi-attach is now allowed when every bedrock attachment shares the same `(access_key, secret_key, region)` triple — previously any second bedrock attachment raised. Divergent credentials or regions still raise upfront with an updated error message. (#692)
- GUI Providers page reworked — Configured providers now render as a table (provider, type, default model, used by, created, actions) with an inline "describe" row-expand, and the model catalog moved to a new "Registry" tab. Adding/editing a Bedrock provider now prompts for AWS Access Key ID, Secret Access Key, and Region (free text, default `us-east-1`) instead of an API key; the API surface gains `requires_aws_credentials` / `default_region` on `/types` and `region` / `has_aws_credentials` on `/providers`. (#694)
- GUI Providers page follow-ups — registry dropdown, fleet-style table, and button-label refinements on top of #694. (#697)
- GUI sidebar reorganized — added an **Agents** entry (after Dashboard) that hosts the fleet table previously embedded on the Dashboard; **Integrations** moved above the not-yet-built rows; added placeholder **Scheduled Jobs** and **Agent Builder** entries alongside the existing **MCPs**. (#701)
- GUI sidebar — **MCPs**, **Scheduled Jobs**, and **Agent Builder** rows render as grayed-out clickable buttons that open a "coming soon" modal with three actions: **Upvote on GitHub** (per-item issue #698 / #699 / #700), **Join the discussion on Discord**, and **Request a different feature** (feature-request template). **Settings** moved out of the main nav into the footer section above GitHub / Docs / Discord (gear icon, active-state highlighting). Modal close restores focus to the triggering button (WCAG 2.4.3). (#702)

### Fixed

- Test-isolation race in the GUI's fleet-health route surfaced after the pytest collection order shifted in 26.6.2-prep. The module-level `asyncio.Semaphore` latched to whichever event loop touched it first, so subsequent tests on a different loop crashed with "is bound to a different event loop"; the lifespan-managed `ThreadPoolExecutor` was shut down on every lifespan exit, racing concurrent TestClient lifespans into "cannot schedule new futures after shutdown". Both resources are now lazy per-loop / process-singleton with no lifespan-driven shutdown. (#710)

### Documentation
