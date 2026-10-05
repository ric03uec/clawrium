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

### Changed

### Fixed

### Documentation

### Internal

- Unblock PyPI publish by pinning `hatchling<1.27` (avoids emitting
  `Metadata-Version: 2.5`, which the previous `pypa/gh-action-pypi-publish`
  SHA rejected) and bumping `pypa/gh-action-pypi-publish` from v1.14.0 to
  v1.14.2 (bundled twine v7 accepts metadata 2.5). The v26.8.0 publish run
  failed on this; v26.8.1 is the republish.
