# Release 26.8.1

Archived changelog for the **26.8.1** release. This is the frozen record of
everything that shipped in this version; the working changelog for the next
release lives at the repository root in [`CHANGELOG.md`](../../../CHANGELOG.md).

Versions follow [SemVer](https://semver.org/), and the project tracks a
calendar versioning convention: `YY.M.PATCH`.

## [26.8.1]

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
  failed on this; the next patch cut republishes.
