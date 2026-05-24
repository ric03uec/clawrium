# Changelog

All notable changes to Clawrium are documented in this file. Versions
follow [SemVer](https://semver.org/), and the project tracks a calendar
versioning convention: `YY.M.PATCH`.

The breaking changes for the next release land under the **Unreleased**
heading; on cut they become the new version's section.

## [Unreleased]

### BREAKING

This release renames the CLI binary and reshapes the entire command
surface to follow kubectl-style verb grammar. There is **no `clm` alias**
and **no deprecation period** — the move is a hard cutover, and existing
installs require a `clawctl agent sync` pass to pick up the new template
filenames.

See the full BEFORE → AFTER table in
[`.itx/435/00_PLAN.md` §5](.itx/435/00_PLAN.md) for every command remap.
Highlights:

- **Binary renamed `clm` → `clawctl`.** Both `uv tool install clawrium`
  and `uvx --from clawrium clawctl --help` now expose the binary as
  `clawctl`. The old `clm` script is no longer published.
- **Verb grammar standardized.** Every top-level group exposes the same
  kubectl-like verbs: `get` / `describe` / `create` / `delete` /
  `edit`. Action verbs (`start`, `stop`, `restart`, `sync`, `configure`,
  `logs`, `open`, `chat`, `attach`, `detach`) live where they map to
  real lifecycle operations.
- **`channel` extracted from `agent configure`.** Discord and Slack are
  now first-class attachables managed under
  `clawctl channel registry create` / `clawctl agent channel attach`
  instead of being prompted-for inside the interactive `agent configure`
  flow. Configure is now fully non-interactive.
- **Templates carry their agent-type prefix.** The four templates below
  were renamed; existing installs carry stale dropin files until the
  next `clawctl agent sync` is run.
  - `zeroclaw/clm-env.conf.j2` → `zeroclaw/zeroclaw-env.conf.j2`
  - `zeroclaw/config.toml.j2` → `zeroclaw/zeroclaw-config.toml.j2`
  - `hermes/config.yaml.j2` → `hermes/hermes-config.yaml.j2`
  - `hermes/.env.j2` → `hermes/hermes.env.j2`
  - Systemd drop-in destination renamed:
    `/etc/systemd/system/zeroclaw-<n>.service.d/10-clm-env.conf` →
    `/etc/systemd/system/zeroclaw-<n>.service.d/10-zeroclaw-env.conf`.
- **`sync` semantics redefined.** `clawctl agent sync <name>` is now a
  drift-to-zero flush — it re-renders configuration, restarts the
  daemon if files changed, and waits for the agent to converge. The
  default timeout is **2 minutes**; override with `--timeout <seconds>`.
- **No migration tooling.** A clean reinstall is the expected upgrade
  path. Existing hosts can be brought up with
  `clawctl agent sync <name>` per agent — this also rotates the gateway
  bearer (issue #437), so remote `clawctl agent chat` sessions will see
  a clean 401 and must reconnect.

### Added

- Top-level `channel` noun with `clawctl channel registry {create, get,
  describe, edit, delete}` for Discord and Slack.
- `clawctl service` group: `init`, `snapshot` (stub), `start` / `stop`
  (stubs reserved for #N).
- `clawctl completion <bash|zsh|fish>` emits shell completion scripts.
- Output format contract: `-o table | json | yaml | wide | name` on
  every `get`, plus `--no-headers` and `-l KEY=VALUE` label selectors.
- Guard test `tests/platform/test_template_naming.py` prevents future
  templates from regressing the `clm-` prefix.

### Changed

- All `get` verbs render kubectl-style padded columns with `NAME` /
  `TYPE` / `STATUS` / `AGE` etc. AGE is humanized (e.g. `2m`, `4h`,
  `9d`). Status vocabulary aligned: `Running` / `Stopped` / `Failed` /
  `Pending`.
- Action streaming output is line-oriented and can emit NDJSON via
  `-o json` for scripting.

### Documentation

- `README.md`, `AGENTS.md`, `docs/installation.md`, and the website
  mirror at `website/docs/installation.md` reflect the new binary.
- Every `clm`-rooted snippet under `docs/` and `website/docs/` has been
  remapped per §5. The introducing-Clawrium blog post is preserved
  verbatim for historical accuracy.
- New blog post:
  [`website/blog/2026-05-24-clawctl-kubectl-ux.md`](website/blog/2026-05-24-clawctl-kubectl-ux.md).

### Migration notes

For each existing agent on each host:

```bash
# Reload the renamed templates (drift-to-zero flush). This also rotates
# the gateway bearer for zeroclaw agents.
clawctl agent sync <agent-name>
```

Remote `clawctl agent chat` sessions will see a one-time 401 after the
sync; reconnecting picks up the fresh bearer transparently.
