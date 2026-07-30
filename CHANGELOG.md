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

- **gui**: Harden static-file handler against path traversal — all candidate
  paths in the catch-all frontend route are now resolved and verified to
  stay inside the frontend directory via `Path.resolve()` +
  `is_relative_to()` (issue #418).
- **gui**: Add `TrustedHostMiddleware` to reject requests with foreign
  `Host` headers, closing a DNS rebinding exposure (issue #418).
- **gui**: Remove `secrets_file`, `hosts_file`, and `providers_file` from
  the `/api/settings` response; replace with `secrets_configured` (bool)
  to avoid leaking absolute filesystem paths (issue #418).

### Documentation

### Internal
