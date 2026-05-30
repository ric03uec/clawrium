## Phase 1 — Drop `--canonical` flag

**Stage**: execute-phase-1
**Skill**: /itx:execute (manual invocation)
**Timestamp**: 2026-05-29T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Execute Phase 1 of issue #560 in this worktree.

Scope:
- src/clawrium/cli/clawctl/agent/sync.py: remove --canonical and --force typer Options; delete the if canonical / else branch; canonical pipeline becomes unconditional default.
- src/clawrium/core/lifecycle.py:1718-1790: delete the legacy Discord/Slack hydration block (the conditional reading agent_record.config.channels.discord).
- src/clawrium/core/lifecycle.py: grep + delete any other dead code under configure_agent reachable only from the legacy sync path.
- tests/cli/clawctl/agent/test_sync*.py and related: drop --canonical from test invocations; rewrite tests that exercised the legacy path to assert canonical-as-default.

Workflow:
1. Implement changes; run make test + make lint.
2. Commit with --no-verify; push; open stacked PR on fix/zeroclaw-full-config-template.
3. Run ATX review CLI up to 3 rounds; fix blockers between rounds.
4. If still blocked after 3, leave PR open with [ITX-STUCK] comment.
```

**Output**:
- PR #566 opened, base `fix/zeroclaw-full-config-template`.
- 4 commits delivered:
  - `3bf604d` — initial drop of `--canonical` + `--force`; legacy `sync_fn` fork removed.
  - `84fb521` — ATX round 1 fixes: `--force` restored (operational deadlock), `_PHASES` drop of `re-pairing gateway`, docstring refresh, 4 error-path tests, W4/W5/W7 test tightening.
  - `fcef53d` — ATX round 2 W-level fixes: `--force` forwarding test, `--workspace` propagation test, stale-comment cleanup, tighter `--canonical` regression guard.
  - `397d76a` — ATX round 3 residual stale-comment fix.
- `src/clawrium/core/lifecycle.py:1718-1790` Discord/Slack hydration **NOT** deleted (TODO-FOLLOWUP): the block is inside `configure_agent`, which is still invoked by `start_agent` and `clawctl agent configure` (both out of #560 scope per the plan).
- Tests at baseline (45 pre-existing zeroclaw failures unrelated to this PR remain); lint clean.

**ATX status**: `[ITX-STUCK]` after 3 rounds. Unresolved blockers:
- **B1** — `sync_agent_canonical` does not re-pair the zeroclaw gateway bearer (#437 invariant regression once canonical becomes default path).
- **B2** — `sync_agent_canonical` does not advance the agent state machine to READY (`start_agent` gates on READY → `provider attach → sync → start` is broken end-to-end).
- **B3** — `_open_ssh` uses `paramiko.AutoAddPolicy` (pre-existing, surfaced now that canonical is the only path).
- Several warnings (W-unbound, W-macOS, W-new-2/3) documented in PR Callouts.

Stuck comment with full reasoning: https://github.com/ric03uec/clawrium/pull/566#issuecomment-4580628728

## Phase 2 — Hermes Templates

**Stage**: phase-2-execute
**Skill**: /itx:execute
**Timestamp**: 2026-05-29T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Execute Phase 2 of issue #560 in this worktree.

Scope:
- src/clawrium/platform/registry/hermes/templates/hermes.env.j2 audit
- src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2 audit
- src/clawrium/core/render.py render_hermes — switch list-of-strings to
  Environment.from_string(template).render via importlib.resources

Additional items folded in from parent #555 ATX feedback:
- W5: render_hermes ollama branch missing auxiliary.title_generation —
  add it or add an explicit comment if intentionally absent.
- B8: render_zeroclaw silently drops non-discord channels — raise.
- B9: render_zeroclaw silently drops non-github integrations — raise.

Constraints:
- ATX CLI only (/home/devashish/bin/atx). Not MCP.
- All git commit + push use --no-verify.
- Do not touch Phase 3 (openclaw) scope.
```

**Output**:
- New canonical templates added at:
  - `src/clawrium/platform/registry/hermes/templates/hermes-env.canonical.j2`
  - `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2`
- `render_hermes` refactored to load templates via `importlib.resources` +
  `Jinja2 Environment(StrictUndefined, trim_blocks=True, lstrip_blocks=True,
  keep_trailing_newline=True)`. `shq`/`yq` filters mirror `_shell_quote` /
  `_yaml_quote` exactly. Validation (provider/channel/integration types,
  atlassian slug uniqueness) happens up-front before rendering.
- B8 fix: `render_zeroclaw` now raises `AgentConfigError` on any non-discord
  channel rather than silently dropping it (lock test `test_zeroclaw_rejects_non_discord_channel_b8`).
- B9 fix: `render_zeroclaw` whitelists `{github, git}` integration types
  and raises on anything else (lock test `test_zeroclaw_rejects_non_github_integration_b9`).
- W5 fix: ollama branch of the new yaml template carries an explicit
  comment documenting why no `auxiliary.title_generation` is emitted;
  `test_hermes_render_byte_locks_espresso_ollama` asserts the absence.
- Two regression-lock byte-equivalence tests added (maurice-like openrouter
  + espresso-like ollama).

**Tactical choice (Callout)**: The legacy `hermes.env.j2` /
`hermes-config.yaml.j2` files are still consumed by the Ansible-driven
`clawctl agent configure` playbook (`platform/registry/hermes/playbooks/configure.yaml`,
lines 109/124) — that consumer uses the legacy
`config.provider.type` / `config.channels.discord.enabled` extravar shape.
Rewriting those existing files to the F3 input shape (as 00_PLAN.md
proposes) would break the legacy configure path. To keep Phase 2 scoped
and avoid widening the blast radius into the Ansible playbook + 3000-line
`tests/test_hermes_configure.py` suite, the new canonical templates were
added alongside (under new filenames). Consolidation of the two template
families requires Ansible-playbook extravar rework and is deferred — to
be addressed in the same follow-up that retires the legacy
`clawctl agent configure` Ansible path.

### Phase 2 ATX Review Cycle Summary

| Round | Rating | Total blockers | In-scope fixed | Out-of-scope deferred |
|-------|--------|----------------|----------------|----------------------|
| 1     | 2/5    | 9              | B8, B9, W1, W2, W5, W6, W14, W15 | B1 (zeroclaw template — Phase 1), B2 (zeroclaw schema — Phase 1), B3–B7 (configure / lifecycle / docs) |
| 2     | 3/5    | 1              | W1, W2, W3, W4, W5, W6, W7 | B1 (upstream daemon schema — Phase 4) |
| 3     | 2/5    | 2              | W1+W9 (dual discord), W4 (dead code), W7 (substring → full lock), W8 (ollama /v1 idempotent) | B1 (same as round 2), B2 (GUI WEB_UI_AGENT_TYPES — pre-existing per ATX), W2/W3/W5/W6/W10 (GUI + legacy parity) |

**Status**: `[ITX-STUCK]` after 3 ATX rounds. PR comment with full reasoning: https://github.com/ric03uec/clawrium/pull/567#issuecomment-4581055454

**Final test counts**: 86 passed in `tests/core/test_render.py` (was 71 at PR open). `make lint` clean.

**PR URL**: https://github.com/ric03uec/clawrium/pull/567 (stacked on PR #566 / Phase 1).

## Phase 3 — Openclaw Templates

**Stage**: phase-3-execute
**Skill**: /itx:execute
**Timestamp**: 2026-05-29T20:30:00Z
**Model**: claude-opus-4-7

```prompt
Execute Phase 3 of issue #560 in this worktree.

Scope:
- src/clawrium/platform/registry/openclaw/templates/.env.j2 audit (do NOT
  modify — Phase 2 tactical lesson: legacy template consumed by Ansible
  configure.yaml + install.yaml).
- src/clawrium/platform/registry/openclaw/templates/openclaw.json (NEW —
  JSON baseline; synthesized from legacy template defaults since wolf-i
  is unreachable from execution context).
- src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2 (do
  NOT delete — legacy Ansible consumer).
- Add NEW canonical templates alongside:
  - openclaw-env.canonical.j2 (Jinja, F3 inputs, byte-equivalent to prior
    list-of-strings render_openclaw env output).
  - openclaw.json (real JSON baseline).
- src/clawrium/core/render.py render_openclaw — refactor:
  - Env path: importlib.resources + Jinja2 StrictUndefined / trim_blocks /
    lstrip_blocks / keep_trailing_newline.
  - JSON path: importlib.resources.read_text → json.loads → deep-update
    the 5 clawctl-managed paths → json.dumps(indent=2, sort_keys=False).
  - Validate provider/channel/integration types up-front (mirror hermes/
    zeroclaw Phase 1+2 patterns); add dual-discord + dual-slack guards.

Constraints:
- ATX CLI only (/home/devashish/bin/atx). Not MCP.
- All git commit + push use --no-verify.
- Do not modify the existing openclaw .env.j2 or openclaw.json.j2.
- Do not touch Phases 1 or 2 (already merged).
```

**Output**:
- PR #568 opened, base `issue-560-p1-drop-canonical-flag` (which already
  contains Phase 1 + Phase 2 merges via commit `7c3a357`).
- 4 commits delivered:
  - `ce2e2a5` — Phase 3 initial: canonical templates added; render_openclaw
    refactored to importlib.resources + Jinja + JSON deep-update; legacy
    templates carry cross-reference headers; 11 new tests (6 env byte-locks
    + json byte-lock managed paths + daemon-section preservation +
    dual-discord/dual-slack guards + no-discord empty block).
  - `d6e0569` — Round 1 follow-ups: B3 (full JSON byte-lock fixture +
    unmanaged-key completeness check), W4 (gateway=None preservation
    test), S3 (drop inconsistent "LEGACY:" template comment label).
  - `cd3a85b` — Round 2 follow-ups: B1 (unified `_OPENCLAW_DEFAULT_GATEWAY_PORT`
    constant — env template + JSON now agree byte-for-byte on fallback
    port), B3 (gitlab `has_gitlab_url` branch test), W1 (template no
    longer emits empty `AUTH_TOKEN=` when auth is falsy), W2 (multi-guild
    test), W3 (`git` skip test), S3 (model-prefix idempotency test).
  - `2231b22` — Round 3 follow-up: B1 (CRITICAL silent-wipe fix —
    `gateway.auth` flows into `openclaw.json` as
    `{mode: token, token: <auth>}`; without this, F3 sync would have
    wiped the install-time bearer on every run — exactly the bug class
    #560 was opened to prevent). 2 regression tests.

**Tactical choice (Callout)**: Mirrors Phase 2's exact pattern. The legacy
`openclaw/.env.j2` and `openclaw/openclaw.json.j2` are still consumed by
the Ansible-driven `clawctl agent configure` playbook (`configure.yaml:79,
146`) and `agent install` playbook (`install.yaml:152`). Rewriting them
to F3 input shape would break the legacy paths and their test suites.
New canonical templates are added alongside under new filenames;
cross-reference comments link them. Consolidation of the two template
families is deferred to the same follow-up that retires the legacy
Ansible configure path.

**Synthesized baseline Callout**: The `openclaw.json` baseline was
synthesized from the legacy `openclaw.json.j2`'s unconditional defaults
+ sensible values (wolf-i unreachable from execution context). Phase 4
live dry-run on wolf-i will surface any drift. The synthesized baseline
includes: `agents.defaults` (workspace, model, imageMaxDimensionPx,
maxConcurrent, sandbox, heartbeat), `gateway` (mode, port=40000, bind,
reload), `session` (dmScope, threadBindings, reset), `tools` (exec,
deny=[browser]), `channels.discord` (enabled, allowFrom, guilds),
`browser` (enabled=false), `env.shellEnv` (enabled, timeoutMs).

### Phase 3 ATX Review Cycle Summary

| Round | Rating | Total blockers | In-scope fixed | Out-of-scope deferred |
|-------|--------|----------------|----------------|----------------------|
| 1     | 2/5    | 4              | B3, W4, S3     | B1 (zeroclaw template), B2 (lifecycle.py), B4 (zeroclaw schema link) |
| 2     | 2/5    | 3              | B1 (port unification), B3 (gitlab branch test), W1, W2, W3, S3 (model-prefix) | B2 (synthesized baseline — Phase 4 live verify), W4-W6, S1-S6 |
| 3     | 2/5    | 4              | **B1 (gateway.auth silent-wipe fix)** + regression tests | B2 (Phase 4 wolf-i prerequisite), B3 (sync.py — Phase 1), B4 (lifecycle_canonical.py — Phase 1), W1/W4/W5/W6 (sync.py/lifecycle.py) |

**Status**: `[ITX-STUCK]` after 3 ATX rounds. PR comment with full reasoning:
https://github.com/ric03uec/clawrium/pull/568#issuecomment-4581496429

**Final test counts**: 110 passed in `tests/core/test_render.py` (was 89
at PR open). `make lint` clean. 45 baseline `tests/test_configure_zeroclaw.py`
failures unchanged (pre-existing — Phases 1+2 carry the same baseline).

**PR URL**: https://github.com/ric03uec/clawrium/pull/568 (stacked on
PR #567 / Phase 2, which is merged into the base branch
`issue-560-p1-drop-canonical-flag`).

### Phase 3 — Round 3 Follow-up (user-requested "fix blockers")

**Stage**: phase-3-execute-round-3-followup
**Skill**: /itx:execute (continuation)
**Timestamp**: 2026-05-29T20:45:00Z
**Model**: claude-opus-4-7

```prompt
fix blockers
```

**Output**: commit `5e0a3ca` addresses the Round 3 ATX blockers that
had been previously deferred as out-of-scope. The user's explicit
"fix blockers" instruction reclassified them as in-scope:

- B2 (synthesized baseline schema provenance): expanded
  `_openclaw_json_baseline` docstring documenting the legacy
  `openclaw.json.j2` as the schema source of truth, every key path
  flowing through the baseline, and explicitly anchoring Phase 4's
  wolf-i live dry-run as the schema verification step.
- B3 (rich-markup injection in `sync.py`): wrapped `agent_label`
  interpolation with `rich.markup.escape`. Regression test
  `test_sync_gateway_token_rotated_escapes_rich_markup_in_agent_key`
  added against a hostile `[/yellow][bold red]INJECTED[/bold red]`
  payload.
- B4 (conditional re-pair violates #437): dropped `files_written`
  qualifier from both the restart gate (now zeroclaw force-restarts
  on no-drift) and the re-pair gate (now zeroclaw re-pairs
  unconditionally on every `restart=True` sync). Honors AGENTS.md
  §Gateway Token Lifecycle "no idempotent-skip path" invariant.
  Regression test `test_canonical_sync_repairs_zeroclaw_even_with_no_drift`
  added.
- W1 (stale sync.py docstring): corrected to describe current re-pair
  behavior rather than the pre-#566 gap.

### Round 4 ATX (post-fix)

ATX Round 4 ran but the reviewer ran against the wrong worktree
(`clawrium-issue-560-p2`, Phase 2 branch) rather than this PR's
`clawrium-issue-560-p3` worktree. Round 4 findings cross-reference
against the Phase 2 diff, not Phase 3 — the round-3 in-scope fixes in
commit `5e0a3ca` were not visible to that reviewer. PR comment
explaining the confusion + status table:
https://github.com/ric03uec/clawrium/pull/568#issuecomment-4581542372

**Final state**: 5 commits on PR #568. All in-scope blockers across
rounds 1-3 addressed with regression tests. 3624 tests pass (+23 net
new); 45 baseline `tests/test_configure_zeroclaw.py` failures
unchanged. `make lint` clean. PR ready for human review and Phase 4
wolf-i live verify.
