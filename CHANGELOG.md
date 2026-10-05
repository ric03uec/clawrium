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

- Mirror the #1019 Herdr documentation onto the website: `website/docs/agent-support/hermes.md` gained the "Herdr integration" section and `website/docs/agent-support/claude.md` the "Herdr runtime" section (the canonical `docs/` sections shipped with #1019 but were never mirrored).
- Correct the Claude Code credential-mode table to the shipped artifact-based credential state (#1022, #1023): OAuth mode renders Claude's native `~/.claude/.credentials.json` document and API-key mode renders `~/.claude/clawrium-credentials.env`; also fixed the README's remaining "explicitly supplied OAuth token" wording (#1020, #1023).

### Internal
