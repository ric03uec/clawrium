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

- Ethos agents stuck in `onboarding.state=pending` (e.g. due to SSH drop or provider API
  unreachable during configure) now auto-recover when `clawctl agent start` is called.
  `start_agent` re-runs configure before raising `LifecycleError`; if recovery succeeds
  the start proceeds normally. If it fails the error message includes the configure failure
  reason instead of the previous opaque "Run clawctl agent configure first" hint (#904).

### Documentation
