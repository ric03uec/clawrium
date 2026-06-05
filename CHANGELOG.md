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

- `clawctl agent sync <hermes-agent>` crashed with
  `ModuleNotFoundError: No module named 'jinja2'` on a fresh
  `uv tool install clawrium`. `jinja2` was declared only under
  `[dependency-groups].dev`, which `uv tool install` does not install.
  Moved `jinja2>=3.0.0` into `[project].dependencies` and added a
  guard test (`tests/test_runtime_imports.py`) so future drift back
  to dev-only fails CI. (#620)

### Documentation
