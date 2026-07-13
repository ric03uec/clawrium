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

- Remove ~640 lines of unreachable dead code from `_run_channels_stage` in
  `src/clawrium/cli/agent.py` (#860), plus two helper functions (`_sync_channel_config`,
  `_build_legacy_discord_channels_block`) that were only reachable from that
  dead body. These were behind an unconditional `raise typer.Exit(code=2)`
  in the deprecated channels onboarding wizard and could never execute.

### Documentation
