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

- `clawctl apply` now generates an ed25519 SSH keypair for new Host resources
  that declare `bootstrap: true`, printing the public key with instructions to
  add it to `authorized_keys` on the remote host. Previously the host record
  was written to `hosts.json` but no key was generated, causing every
  subsequent Ansible operation to fail with "No SSH key found for host"
  (#902).

### Changed

### Fixed

### Documentation
