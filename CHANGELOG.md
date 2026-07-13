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

- Removed the legacy `src/clawrium/cli/skill.py`, `host.py`,
  `integration.py`, and `provider.py` modules (#707, Phase 1). These
  four files were orphaned when the `clm` entry point was deleted in
  #706 — no code in `src/` or `tests/` imported them. Deleting them
  removes ~2.9k LOC of dead code without touching any behavior.
  Remaining hybrid `cli/*.py` modules (chat, agent, memory, etc.) are
  tracked for staged removal in follow-up phases on #707.

### Fixed

### Documentation
