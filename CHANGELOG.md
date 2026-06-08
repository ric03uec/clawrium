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

- Skills desired state now stores **agent-local skill names** instead of
  registry refs. `~/.config/clawrium/agents/<agent>/skills.json` entries
  such as `"clawrium/tdd"` are no longer valid; re-add those templates with
  `clawctl agent skill add <agent> --from-template clawrium/tdd` to create the
  local `skills/tdd/SKILL.md` copy, then run `clawctl agent sync <agent>`.
  The old `clawctl agent skill attach|detach|get --agent ...` surface has
  been removed in favor of `add|remove|list <agent>`. There is no automated
  migration because registry refs are now template sources only. (#411)
- hermes: legacy ansible-side templates
  `src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2`
  and `hermes.env.j2` have been **removed**. The configure playbook no
  longer renders them server-side; `~/.hermes/config.yaml` and
  `~/.hermes/.env` are now produced client-side by `render_hermes`
  (`src/clawrium/core/render.py`) and deployed via
  `ansible.builtin.copy`. **Operator action: none** — every `clawctl`
  command keeps its exact contract, and single-provider rendered output
  is byte-identical to the previous release. **Downstream / vendor
  action**: anyone importing or templating against the deleted `.j2`
  files must switch to calling `render_hermes(build_render_inputs(name))`
  and reading the `RenderedFiles` dict at `.hermes/config.yaml` /
  `.hermes/.env`. There is no automated migration; vendored copies of
  the legacy templates will continue to work standalone but will not
  receive multi-provider auxiliary-block rendering or any future fix.
  (#622, parent #589)

### Added

- `clawctl agent skill add <agent> --from-template <registry>/<name>` copies a
  catalog template into the agent-local control-plane skill directory in that
  agent's native format. `clawctl agent skill add <agent> <path>`, `edit`,
  `remove`, and `list` manage those local skill files without touching the
  host until `clawctl agent sync <agent>` is run. (#411)
- `clawctl skill add <path> --registry <registry>` adds a user overlay skill
  under `~/.config/clawrium/skills/<registry>/<name>/`; `clawctl skill
  registry get/describe` now includes overlay entries with overlay copies
  taking precedence over bundled catalog entries of the same ref. (#411)
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
- GUI: **Add skill** modal on the Agent Detail → Skills tab with three
  input modes — **From catalog** (template picker), **From file** (paste
  raw `SKILL.md`), and **Inline** (name + description + body form). Each
  mode writes a per-agent local skill without immediately syncing the
  host. (#411)
- GUI: **Edit** button on `LOCAL`-origin installed skill rows opens an
  in-browser `SKILL.md` editor; re-validates the schema before writing.
  (#411)
- GUI: origin chips (**LOCAL** / **BUNDLED** / **OVERLAY**) on every
  installed skill row so the provenance of each skill is visible at a
  glance. (#411)
- GUI: **Add to catalog** button on the Skills page writes a skill to the
  user overlay (`~/.config/clawrium/skills/<registry>/<name>/`) via a new
  `POST /api/skills` endpoint; the skill appears in the catalog picker
  immediately. (#411)

### Changed

- hermes: `~/.hermes/config.yaml` and `~/.hermes/.env` are now rendered
  client-side by `clawctl` (via `render_hermes`) and copied to the
  agent host by the configure playbook, instead of being templated
  server-side by Ansible. Unifies the rendering path between
  `clawctl agent configure` and `clawctl agent sync`, so multi-provider
  attachments now work on both commands (previously only `sync`
  rendered them correctly). No operator action required; existing
  CLI commands keep their exact contract, single-provider output is
  byte-identical. (#622, parent #589)

### Fixed

- `clawctl` skill-not-found guidance now references
  `clawctl skill registry get` instead of the removed legacy
  `clm skill list` command. (#411)
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
- `clawctl agent sync <hermes-agent>` crashed with
  `ModuleNotFoundError: No module named 'jinja2'` on a fresh
  `uv tool install clawrium`. `jinja2` was declared only under
  `[dependency-groups].dev`, which `uv tool install` does not install.
  Moved `jinja2>=3.0.0` into `[project].dependencies` and added a
  guard test (`tests/test_runtime_imports.py`) so future drift back
  to dev-only fails CI. (#620)

### Documentation

- Documented the hermes multi-provider attachment model in the
  Hermes Support Matrix (`docs/agent-support/hermes.md` and its
  website mirror): the 1 `primary` + 9 auxiliary slot enumeration,
  the `clawctl agent provider attach --role <role>` workflow, the
  per-slot single-provider invariant, the primary-detached-last
  invariant, and the rendered `auxiliary.<role>:` shape. The macOS
  install walkthrough (`docs/installation.md` + website mirror)
  now shows `--role` in the `provider attach` example and links to
  the new section. Closes documentation drift identified after
  #612 / #621 / #622 landed multi-provider support in the CLI
  without updating user-facing docs.
