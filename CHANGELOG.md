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

- Added the install-only `pi` fleet agent. Pi installs in its own account and runs native commands on demand without a service, port, or dashboard (#1032).
- Added scoped OpenRouter provisioning and finite CLI/GUI chat for Pi agents, including continued and reset conversations without a Pi service or dashboard (#1038).
- Added agent-scoped native OpenAI Codex OAuth selection and interactive login for Pi, with private on-host refresh and CLI/GUI chat support (#1040).
- Added AWS Identity Center SSO profile provisioning for Pi Bedrock selections. Pi uses only its dedicated account's profile and region; it never receives controller AWS caches or static Bedrock keys (#1039).
- Add the daemonless, dedicated-account Codex CLI agent with pinned native command execution on supported Ubuntu and macOS hosts (#1034).
- Add selection-only `codex-oauth` providers that safely import a local file-backed Codex ChatGPT login into the chosen Codex agent's encrypted secrets (#1035).
- Activate Codex OAuth credentials privately on configure and sync while preserving tokens refreshed on the remote agent; re-attaching explicitly replaces remote credentials (#1036).

### Changed

### Fixed

### Documentation

- Document fail-closed recovery steps for an interrupted Codex OAuth activation without exposing native auth credentials (#1036).

### Internal
