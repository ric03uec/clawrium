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

- `clawctl host edit --description <text>` sets or updates a free-form description on a host record; passing an empty string clears it (#122).

### Changed

- `clawctl channel registry create/edit --home-channel <id>` now accepts Discord channels in addition to Slack; the Jinja `hermes-env.canonical.j2` template already emitted `DISCORD_HOME_CHANNEL` when the field was set, only the CLI guards blocked it (#642).

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
- `clawctl agent upgrade` now probes the live openclaw version on the host instead of trusting the hosts.json snapshot, closing the false-no-op trap when snapshot and live binary diverge (#754)

### Documentation

- Document `clawctl host validate`, the `RUNTIME` column on `clawctl agent get`,
  and openclaw's mandatory `--provider` flag; correct the `clawctl agent create`
  and `clawctl agent get` reference sections, whose documented signatures and
  options had drifted from the real CLI (#947-#950, #754).

### Internal
