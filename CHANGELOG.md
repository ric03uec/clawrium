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

### Added

### Changed

### Fixed

- `clawctl agent exec`, `clawctl agent sync`, and the sync validate-phase
  unit-path probe now work correctly for ethos agents (#898). Previously,
  `agent exec` rejected ethos with "does not support exec", `sync` raised
  `ValueError` from the unit-path probe, and attaching an `openrouter`,
  `anthropic`, or `openai` provider to an ethos agent caused a
  `ProviderType not in _AGENT_TYPE_PROVIDER_SUPPORT` error. The `codex`
  device-auth provider is now also wired through `build_render_inputs`
  without requiring a stored API key.

### Documentation
