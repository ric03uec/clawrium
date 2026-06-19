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

- OpenCode inference provider support. `clawctl provider registry create` now
  accepts `--type opencode` and `--type opencode-go`, with model catalog
  entries for both hosted gateways and renderer wiring for hermes, zeroclaw,
  and openclaw agents (#722).

### Changed

### Fixed

### Documentation
