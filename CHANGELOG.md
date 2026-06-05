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

### Changed

### Fixed

- `clawctl agent sync` on hermes agents with multiple provider
  attachments now renders one `auxiliary.<role>:` block per non-primary
  attachment in `~/.hermes/config.yaml`, and emits each non-primary
  provider's credentials into `~/.hermes/.env` (bearer keys for cloud
  providers, AWS triple for bedrock). Previously the canonical render
  path picked only the primary and silently dropped every auxiliary
  slot, causing hermes to fall back to upstream per-primary-type
  defaults for aux models. Single-provider hermes rendering is
  byte-identical; `zeroclaw` and `openclaw` renderers are not touched.
  Same-type collisions with different API keys and multiple bedrock
  attachments now fail loudly at `build_render_inputs` with actionable
  errors. (#621, parent #589)

### Documentation
