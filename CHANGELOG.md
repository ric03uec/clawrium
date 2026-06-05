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

### Added

- `clawctl agent provider attach --role <role>` for hermes agents.
  Required on hermes (`primary` for the first attachment, plus one of
  nine upstream auxiliary slots — `vision`, `web_extract`,
  `compression`, `session_search`, `skills_hub`, `approval`, `mcp`,
  `title_generation`, `curator` — for any subsequent attachment).
  Rejected on `zeroclaw`/`openclaw`. `clawctl agent provider get`
  renders the additional `role` and `model` columns for hermes; the
  legacy flat output is unchanged for singleton agents. `clawctl agent
  provider detach <primary-name>` now refuses to remove the primary
  attachment while auxiliary attachments remain — detach those first.
  Singleton agents keep the `single-provider invariant` rejection
  message verbatim. (#612, parent #589)
- `configure_agent` now hydrates per-attachment provider credentials
  into `ansible_vars` for hermes: `provider_api_keys` (dict keyed by
  provider name) carries API keys for non-bedrock attachments, and
  `provider_aws_credentials` (dict of `{access_key, secret_key,
  region}` keyed by provider name) carries AWS creds for bedrock
  attachments. The legacy singleton `provider_api_key` /
  `aws_access_key` / `aws_secret_key` vars continue to reflect the
  primary attachment for back-compat with un-migrated canonical
  templates. Zeroclaw/openclaw `ansible_vars` are unchanged. (#613,
  parent #589)
- Hermes manifest now lists `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY` under `secrets.optional` so the configure
  wizard surfaces them for bedrock attachments. (#613)

### Changed

### Fixed

### Documentation
