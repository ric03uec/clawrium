# Release 26.6.0

Archived changelog for the **26.6.0** release. This is the frozen record of
everything that shipped in this version; the working changelog for the next
release lives at the repository root in [`CHANGELOG.md`](../../../CHANGELOG.md).

Versions follow [SemVer](https://semver.org/), and the project tracks a
calendar versioning convention: `YY.M.PATCH`.

## [26.6.0]

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

### Fixed

- **#555 — silent on-host config wipe on every `clawctl agent
  sync|configure|restart|skill attach|channel attach|integration
  attach`.** Templates emitted provider, channel, and integration
  blocks conditionally on `hosts.json.agents.<n>.config.*` being
  populated; when those fields were null (the common state after the
  attachment-list refactor), every sync silently dropped the
  `OPENROUTER_API_KEY`, `DISCORD_*`, `SLACK_*`, and integration env
  vars from `~/.hermes/.env` and `[channels.discord]` /
  `[providers.models.*]` blocks from `~/.zeroclaw/config.toml` while
  reporting `drift=0`.

  **Regression window:** from the conditional-emit commit that
  introduced the `config.channels` / `config.provider` reads through
  the F1–F6 canonical render pipeline (PR #556, #557, #559) and
  legacy read-path drop (PR #566, #567, #568 — this release).

  **Affected agents:** anyone whose
  `hosts.json.agents.<n>.config.provider` or
  `hosts.json.agents.<n>.config.channels` was ever null (the default
  state when the agent was last attached using the new
  `clawctl channel registry create` / `clawctl agent channel attach`
  flow without a prior legacy-stage write).

  **Recovery:**

  ```bash
  # 1. Re-derive provider_id / channels[] / integrations[] from
  #    onboarding + secrets.json + on-host .env grep. Idempotent.
  clawctl admin migrate-agent <agent-name>

  # 2. Confirm the agent's declared attachments resolve cleanly.
  clawctl agent doctor <agent-name>

  # 3. Dry-run the sync to see exactly what will land on the host.
  clawctl agent sync <agent-name> --dry-run --diff

  # 4. Apply.
  clawctl agent sync <agent-name>
  ```

  After this release, `clawctl agent sync` reads from clawctl's own
  stores (`providers.json` + `channels.json` + `integrations.json` +
  `secrets.json` + `hosts.json.agents.<n>.{provider_id, channels[],
  integrations[]}`), renders the full canonical bundle deterministically,
  and refuses to remove a host-side secret without `--force` or an
  explicit detach. There is no `drift=0` success path that depends on
  clawctl's own incomplete model — drift is computed against what's
  actually on the host.

### Migration notes

For each existing agent on each host:

```bash
# Reload the renamed templates (drift-to-zero flush). This also rotates
# the gateway bearer for zeroclaw agents.
clawctl agent sync <agent-name>
```

Remote `clawctl agent chat` sessions will see a one-time 401 after the
sync; reconnecting picks up the fresh bearer transparently.

**Anyone who ran `clawctl agent sync|configure|restart` against an
agent during the regression window:** follow the recovery sequence
above to re-derive lost attachments and re-render the on-host config
from the canonical pipeline.
