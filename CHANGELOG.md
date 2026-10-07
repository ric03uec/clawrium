# Changelog

All notable changes to this project are documented here. Per-release frozen
archives live under [`docs/releases/`](docs/releases/) — that directory is
the single place to read the full history of what shipped in each version.

The project follows a `YY.M.PATCH` calendar versioning convention; the
`## [Unreleased]` section below is the working log for the next release
cut. The `itx-release` skill archives this section into a new
`docs/releases/<version>/CHANGELOG.md` and resets this file to an empty
`[Unreleased]` template on every release.

## [Unreleased]

### BREAKING

### Added

- Added the install-only `pi` fleet agent. Pi installs in its own account and runs native commands on demand without a service, port, or dashboard (#1032).
- Added scoped OpenRouter provisioning and finite CLI/GUI chat for Pi agents, including continued and reset conversations without a Pi service or dashboard (#1038).
- Added agent-scoped native OpenAI Codex OAuth selection and interactive login for Pi, with private on-host refresh and CLI/GUI chat support (#1040).

### Changed

### Fixed

### Documentation

### Internal
