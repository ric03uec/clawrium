# Changelog

All notable changes to Clawrium are documented in this file. Versions
follow [SemVer](https://semver.org/), and the project tracks a calendar
versioning convention: `YY.M.PATCH`.

This file is the **working changelog for the current, unreleased version
only**. Everything that has already shipped is archived per release under
[`docs/releases/<version>/CHANGELOG.md`](docs/releases/). On each release
cut, the contents below are moved into a new `docs/releases/<version>/`
folder and this file is reset to the empty template you see here.

See [docs/releases/](docs/releases/) for the changelog of every past
release.

## [Unreleased]

### BREAKING

- **Provider state has a single source of truth.** An agent's provider is
  now read from exactly one place — the top-level `providers` list on the
  agent record (tier-1, written by `clawctl agent provider attach` and
  `clawctl agent configure`). The vestigial `config.providers` field
  (tier-3) has been removed from the code, and there is **no fallback** to
  the materialized `config.provider` block (tier-2). If no provider is
  attached, the render path fails fast with `AgentConfigError` instead of
  silently resolving from another tier.
  - **No migration.** This is a hard cutover. Legacy records whose provider
    lives only in `config.provider` must be repaired by running
    `clawctl agent provider attach <provider> --agent <name>`, which
    populates the canonical top-level `providers` list.

### Added

### Changed

### Fixed

### Documentation
