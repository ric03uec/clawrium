# Release 26.7.2

Archived changelog for the **26.7.2** release. This is the frozen record of
everything that shipped in this version; the working changelog for the next
release lives at the repository root in [`CHANGELOG.md`](../../../CHANGELOG.md).

Versions follow [SemVer](https://semver.org/), and the project tracks a
calendar versioning convention: `YY.M.PATCH`.

## [26.7.2]

### BREAKING

### Added

### Changed

### Fixed

- **Publish pipeline unbroken.** The v26.7.1 PyPI publish workflow failed
  because the sdist was empty (`[tool.hatch.build.targets.sdist] include`
  from PR #779 turned hatch's default file selection into an exclusive
  whitelist, dropping `skills/`, `src/clawrium/**`, tests, and everything
  else) and the wheel would have shipped with `__version__ = 'standard'`
  (the hatch_build hook mis-used hatchling's build-scheme arg as the
  package version). Both fixed in #892; v26.7.2 is the first successful
  publish since v26.7.0.

### Documentation
