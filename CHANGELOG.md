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

### Documentation

- Website blog UI improvements: post titles shrunk to 2.25rem; in-post body
  headings (`h1`–`h4`) reduced by one step; left sidebar groups posts by
  month (e.g. "June 2026") instead of year and shows all posts; the
  sidebar's "All posts" title now links back to `/blog`; the `/blog` listing
  page gains a right-hand rail with About, Tags, and Community sections so
  the previously empty `col--2` slot is no longer dead space.
