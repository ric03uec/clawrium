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

- GUI lifecycle endpoints (`start`, `stop`, `restart`) now return HTTP 502 instead of HTTP 200 with `success: false` when the underlying lifecycle operation fails without raising an exception (#712)

### Documentation

- Synced the website agent-support pages for Hermes, OpenClaw, and ZeroClaw with the shipped Slack integration docs so the release blog's Slack links resolve and the docs site can build again.
