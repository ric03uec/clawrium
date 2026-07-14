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

- `clawctl agent doctor <name>` — read-only health diagnostics command that
  runs five checks in dependency order (SSH reachable → unit running →
  gateway reachable → token stored → onboarding complete) and prints a
  pass/fail table with per-check remediation hints.  If a check fails,
  downstream checks are marked "skipped" rather than reporting spurious
  failures (closes #903).

### Changed

### Fixed

### Documentation
