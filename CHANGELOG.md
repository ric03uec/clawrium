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

- `openclaw` agents can now attach `type=litellm` providers — custom
  OpenAI-compatible endpoints (LiteLLM, vLLM, any `/v1/chat/completions`
  proxy). `clawctl agent configure` / `clawctl agent sync` render a
  `models.providers.<provider-name>` block into `.openclaw/openclaw.json`
  with `api: "openai-completions"`, inline `apiKey`, and `baseUrl`
  normalized to `<endpoint>/v1`. The bearer lives in `openclaw.json`
  exclusively — no new `.openclaw/env` var emitted. Closes #723.
- Right-hand rail on the `/blog` listing (About, Tags, Community sections),
  filling the previously empty `col--2` slot. Sticky-positioned with its own
  scroll on short viewports; hidden below 996px. Individual post pages still
  render the standard table of contents in that column.

### Changed

- `clawctl host create` manual-setup output now prints a macOS preflight
  block instructing operators to enable Remote Login (`sshd`) locally on
  the Mac before running the SSH-paste block. (#718)
- Blog post titles shrunk from 3rem to 2.25rem (1.6rem on screens ≤576px).
  In-post body headings (`h1`–`h4`) reduced by one step. All overrides scoped
  to `.blog-wrapper` so docs typography is unaffected.
- Left blog sidebar now groups posts by month (e.g. "June 2026") instead of
  year and shows every post (`blogSidebarCount: 'ALL'`).
- Sidebar "All posts" label is now a link back to `/blog` so readers can
  navigate back from any post page.

### Fixed

### Documentation

- Document the macOS-only requirement to enable Remote Login (sshd) before
  running the `xclm` host-preparation block, and surface the same preflight
  in the `clawctl host create` manual-setup output. (#718)
