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

- openclaw renderer no longer emits `{"allow": true}` for entries in
  `channels.discord.guilds.<id>.channels.<id>`. openclaw 2026.5.28+
  rejects `allow` as an additional property
  (`must not have additional properties: "allow"`); presence in the
  channels map alone permits the channel under
  `groupPolicy: "allowlist"`. The legacy `clm` CLI's discord setup
  prompt (`cli/agent.py`) emitted the same shape and is patched in
  the same change.

### Documentation

- Landing page audit: restructured the GitHub README first-success path —
  added a Support Matrix near the top (control/host OS, agent runtimes,
  providers, channels), dropped the deliberate `xclm SSH verification
  failed` step from the 5-Minute Setup, added **Tested on Ubuntu** and
  **Tested on macOS** badges, and updated FAQ #1 to reflect macOS
  end-to-end support.
- Renamed the generic noun "Claw" / "Claws" → "Agent" / "Agents" across
  the README, AGENTS.md, the Docusaurus landing (tagline, hero,
  HomepageFeatures), website docs (intro, architecture, configuration,
  CLI reference, skills, fleet management, hermes/memory pages), and the
  repo-rooted docs index. Brand names (Clawrium, OpenClaw, ZeroClaw,
  IronClaw, NemoClaw, Hermes) are preserved, as are real on-disk
  identifiers (`*claw` systemd glob, `claw_supports_memory` Python
  symbol).
- Replaced remaining `clm` references with `clawctl` on the website
  landing's `HomepageFeatures` ASCII diagram and sample output, and in
  the `troubleshooting.md` setup-snippet placeholder. Dated migration
  blog posts and `docs/releases/*/CHANGELOG.md` archives are intentionally
  left untouched.
- Added the **"Agent Fleet Manager"** subtitle to the Clawrium hero on
  the Docusaurus landing (via the site tagline) and to the centered
  intro on the GitHub README.
- Upgraded Hermes and ZeroClaw status from 🚧 in-development to ✅
  fully supported across the README Support Matrix, README "What is an
  Agent?", `HomepageFeatures` TSX card, `website/docs/intro.md` (list +
  FAQ #2), and `website/docs/architecture.md`. OpenClaw / Hermes /
  ZeroClaw are now uniformly listed as the three fully-supported
  agent types; IronClaw remains planned.
- Rewrote the README 5-Minute Setup to surface the xclm bootstrap as
  explicit numbered steps: (1) `clawctl service init` on the control
  machine, (2) `clawctl host create` on the control machine to generate
  the per-host keypair and print the host setup commands, (3) SSH into
  the host and paste the printed block (Linux example inlined), (4)
  re-run `clawctl host create` to register the host, (5) provider +
  agent install + start + chat. Replaces the implicit "prerequisite"
  callout that hid the bootstrap step.
