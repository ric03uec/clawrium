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

- `tape.output_format` key in `docs/demos/<demo>/scenes.yaml` — set to
  `gif` to emit `recording.gif` from `vhs`; defaults to `mp4` (existing
  behavior). GIF outputs skip the `narrate.py` step since GIF has no
  audio container. The `/create-vhs` skill documents this in its
  scenes.yaml template and Step 6 (narration).

### Changed

### Fixed

### Documentation
