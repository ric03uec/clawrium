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
