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

- Right-hand rail on the `/blog` listing (About, Tags, Community sections),
  filling the previously empty `col--2` slot. Sticky-positioned with its own
  scroll on short viewports; hidden below 996px. Individual post pages still
  render the standard table of contents in that column.

### Changed

- Blog post titles shrunk from 3rem to 2.25rem (1.6rem on screens ≤576px).
  In-post body headings (`h1`–`h4`) reduced by one step. All overrides scoped
  to `.blog-wrapper` so docs typography is unaffected.
- Left blog sidebar now groups posts by month (e.g. "June 2026") instead of
  year and shows every post (`blogSidebarCount: 'ALL'`).
- Sidebar "All posts" label is now a link back to `/blog` so readers can
  navigate back from any post page.

### Fixed

### Documentation
