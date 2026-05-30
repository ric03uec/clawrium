# #560 — Drop `--canonical` flag, full-template hermes + openclaw renders

Parent: #555.

## Problem

Two outstanding gaps from #555's design:

1. **`clawctl agent sync` still has a `--canonical` flag.** Canonical is the
   only correct behavior; without the flag, sync runs the legacy
   ansible-driven path that contains the original #555 silent-wipe bug
   (`src/clawrium/core/lifecycle.py:1718–1790`, conditional Discord/Slack
   hydration that reads the deprecated `agent_record.config.channels.discord`
   shape). The flag is a wart from the incremental F3 rollout in #563.
2. **`render_hermes` and `render_openclaw` still build their output as
   list-of-strings**, not from a full canonical template. The zeroclaw-side
   fix in #565 (lifecycle/render template) is not yet applied to hermes
   or openclaw. For hermes the on-disk surface is small (~16 lines `.env`,
   ~8 lines `config.yaml`) so the silent-wipe risk is low, but the pattern
   inconsistency is real. For openclaw, **`render_openclaw` does not render
   `~/.openclaw/openclaw.json` at all today** — that file is daemon-managed
   (111 lines on wolf-i) with five clawctl-managed fields embedded. The
   Discord allowlist for openclaw lives in `openclaw.json`, not in env, so
   F3 cannot update it for openclaw agents.

## Approach

One PR. Stacked on `fix/zeroclaw-full-config-template` (PR #565). Three
phases plus verification.

### Single source of truth for managed values

Registry stores flat (`allowed_users[]`, `allowed_guilds[]`,
`allowed_channels[]`). The renderer reshapes to whatever the agent format
requires — hermes csv env var, zeroclaw flat TOML array, openclaw nested
JSON (`allowFrom[]` + `guilds.<G>.users[]` + `guilds.<G>.channels.<C>.allow=true`).

### Phase 1 — Drop `--canonical` flag + delete legacy code

| File | Change |
|---|---|
| `src/clawrium/cli/clawctl/agent/sync.py` | Remove `--canonical` and `--force` typer Options. Remove the `if canonical:` / `else:` branch. Canonical pipeline becomes the unconditional default. |
| `src/clawrium/core/lifecycle.py:1718–1790` | Delete the legacy Discord/Slack hydration block — the conditional reads from `agent_record.config.channels.discord`. This is the original #555 bug site. |
| `src/clawrium/core/lifecycle.py` (rest) | grep + delete any other dead code under `configure_agent` reachable only from the legacy sync path. |
| `tests/cli/clawctl/agent/test_sync*.py` | Drop `--canonical` from any test invocations; rewrite tests that exercised the legacy path to assert canonical-as-default. |

### Phase 2 — Hermes templates

| File | Action |
|---|---|
| `src/clawrium/platform/registry/hermes/templates/hermes.env.j2` (existing, 122 lines) | Audit + adapt. Rename legacy variable names (`channels.discord.enabled`, `config.provider.type`) to F3 inputs (`discord_channel.*`, `provider.type`). Drop any conditional-emission of clawctl-managed structure that risks silent wipe. Keep the file at its existing path; this stays the canonical hermes env template. |
| `src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2` (existing, 138 lines) | Same — adapt variable names to F3 inputs. |
| `src/clawrium/core/render.py:render_hermes` | Replace list-of-strings construction with `Environment.from_string(template).render(...)` loaded via `importlib.resources`. `StrictUndefined` so missing context vars raise. Same mechanism as `render_zeroclaw` post-#565. |

### Phase 3 — Openclaw

| File | Action |
|---|---|
| `src/clawrium/platform/registry/openclaw/templates/.env.j2` (existing, ~4.4 KB) | Audit + adapt variable names to F3 inputs. Stays the canonical openclaw env template. |
| `src/clawrium/platform/registry/openclaw/templates/openclaw.json` **(NEW — real JSON, not Jinja)** | Full baseline structure of `openclaw.json` (111 lines from wolf-i's live file). Values for the 5 clawctl-managed fields zeroed/placeholder; everything else verbatim. |
| `src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2` (existing legacy 218-line Jinja file) | Delete. The Python dict path replaces it. |
| `src/clawrium/core/render.py:render_openclaw` | Env path: load `.env.j2` via Jinja2 (same as hermes/zeroclaw). JSON path: `importlib.resources.files(...).read_text()` → `json.loads(baseline)` → deep-update the 5 managed paths from `inputs` → `json.dumps(indent=2, sort_keys=False)`. Add `.openclaw/openclaw.json` to `RenderedFiles`. |

The 5 clawctl-managed paths in `openclaw.json`:

- `channels.discord.enabled`
- `channels.discord.allowFrom` (from `inputs.channels[discord].allowed_users`)
- `channels.discord.guilds` (nested reshape from `allowed_guilds` + `allowed_channels`)
- `gateway.port` + `gateway.bind` (from `inputs.gateway.*`)
- `agents.defaults.model.primary` (from `inputs.provider.default_model` with type prefix)

### Phase 4 — Tests + live verify

| Step | What |
|---|---|
| Regression-lock tests | For each agent type, fix a known `RenderInputs` and assert byte-equivalence between (a) the new template output and (b) maurice's / espresso's / wolf-i's current canonical on-host files. Any mismatch fails the test. |
| Daemon-section preservation tests | Add positive assertions in hermes/openclaw test cases that previously-unmanaged sections survive the render (mirrors what #565 added for zeroclaw). For openclaw.json: assert `env.shellEnv`, `tools.exec`, `commands.native`, `session.*`, `agents.defaults.heartbeat` are present byte-identical post-render. |
| Drop `--canonical` test artifacts | Remove any test that calls `sync --canonical`; rewrite the bare invocations. |
| Dry-run live | `clawctl agent sync maurice --dry-run --diff` → empty diff expected. Same for espresso, wolf-i (env path). Wolf-i openclaw.json diff: shows only the 5 managed fields converging onto registry-derived values. |
| Apply live | All three agents. Confirm services healthy; Discord reachable; daemon-managed openclaw.json sections byte-preserved. |
| Commit + PR | Stacked on `fix/zeroclaw-full-config-template`. PR title: `fix(render): drop --canonical flag, full-template hermes + openclaw renders (#555)`. |

## Files touched (summary)

```
src/clawrium/cli/clawctl/agent/sync.py                          (modify)
src/clawrium/core/lifecycle.py                                   (modify — delete L1718-1790)
src/clawrium/core/render.py                                      (modify — render_hermes, render_openclaw)
src/clawrium/platform/registry/hermes/templates/hermes.env.j2    (modify)
src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2 (modify)
src/clawrium/platform/registry/openclaw/templates/.env.j2        (modify)
src/clawrium/platform/registry/openclaw/templates/openclaw.json  (NEW)
src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2 (DELETE)
tests/core/test_render.py                                        (modify — hermes + openclaw sections)
tests/cli/clawctl/agent/test_sync_diff.py                        (modify — drop --canonical)
tests/cli/clawctl/agent/test_sync*.py                            (modify — drop --canonical)
.itx/560/01_EXECUTION.md                                         (prompt log per AGENTS.md)
```

## Phases with entry/exit criteria

| Phase | Entry | Exit |
|---|---|---|
| 1 | `fix/zeroclaw-full-config-template` checked out (PR #565). `make test` green on baseline. | `--canonical` removed from CLI. `sync` runs canonical unconditionally. Legacy hydration in lifecycle.py deleted. All existing tests pass after rewrites. |
| 2 | Phase 1 complete. | Hermes templates adapted to F3 inputs. `render_hermes` uses Jinja. Byte-equivalence test passes for maurice + espresso baseline. |
| 3 | Phase 2 complete. | `openclaw.json` baseline file added. `render_openclaw` emits both env (Jinja) and openclaw.json (dict deep-update). Byte-equivalence test passes for wolf-i baseline. Daemon-section assertions pass. |
| 4 | Phase 3 complete. | Live dry-run shows empty diffs for maurice + espresso, and only 5 managed-field deltas for wolf-i openclaw.json. Live apply succeeds for all three. PR opened. |

## Out of scope (NOT touched in this PR)

- `clawctl agent configure` — wizard-based command; not gated by `--canonical`.
- `clawctl agent install` — agent provisioning; separate Ansible flow.
- `clawctl channel registry` / `clawctl agent doctor` — unchanged.
- Updating downstream docs (`docs/agent-support/channels/*.md`, etc.) — F9 from #555, separate.
- CHANGELOG entry — F10 from #555, separate.

If F9 + F10 belong in this PR, expand scope on user request.

## Risks

1. **`agent configure` may share lifecycle code with sync.** If deleting
   `lifecycle.py:1718–1790` breaks configure, options are: keep the
   function but rename it to make its sole caller clear, or fold
   configure's hydration into F3 inputs. Decision deferred to time of
   coding; recorded as Callout on PR.
2. **`openclaw.json` baseline is wolf-i-specific.** wolf-i is the only
   openclaw on this control plane. Local quirks in its file will become
   the baseline for all openclaw renders. Alternative is hand-curating a
   "vanilla" baseline, which is worse. Documented as Callout.
3. **Hermes/openclaw byte-equivalence regression.** The Phase 2/3
   conversions must produce byte-identical output to the current
   `render_hermes` / `render_openclaw` for the same inputs. Locked by
   regression test; any mismatch fails CI.
4. **Live verify against a non-trivial number of agents.** maurice,
   espresso, wolf-i. Backups created on host before each apply.

## Verification commands

```bash
# Unit
make test
make lint

# Live dry-runs (each must show acceptable diff)
uv run clawctl agent sync maurice --dry-run --diff
uv run clawctl agent sync espresso --dry-run --diff
uv run clawctl agent sync wolf-i --dry-run --diff

# Live apply + health check
uv run clawctl agent sync maurice
uv run clawctl agent sync espresso
uv run clawctl agent sync wolf-i

# Post-apply: confirm Discord still works on each
# (manual: @-mention in respective home channel)
```
