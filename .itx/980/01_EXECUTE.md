# Issue #980 — Execution

**PR**: https://github.com/ric03uec/clawrium/pull/981
**Branch**: `issue-980-zeroclaw-alias-sanitize` → `main`
**Worktree**: `/home/devashish/workspace/ric03uec/clawrium-issue-980`
**UAT host**: `wolf-i` / `clawrium-d01` (zeroclaw 0.8.2)

## Commits

- `57037ff` — fix(zeroclaw): sanitize alias for [agents.<alias>] and [providers.models.<type>.<alias>]
- `6822077` — fix(chat): sanitize zeroclaw agent_alias for /ws/chat ?agent= param (caught during wolf-i UAT)
- `bfe120a` — fix(#980): ATX iter-1 — cover empty-alias guard + toq consistency + edge tests

## Execution notes

- **Renderer + template**: three sites swapped `agent_name` → `agent_alias`; empty-alias guard added in parallel with the pre-existing `discord_alias` guard.
- **Chat client fix**: the renderer-only change failed the E2E chat probe with HTTP 400 because `_build_zeroclaw_backend` was still passing the raw `agent_name` on the `/ws/chat?agent=` query param. Fix: apply `_sanitize_zeroclaw_alias` in the same place. This is a client-side symmetry to the renderer's sub-table key sanitization — the two ends must move together.
- **BREAKING migration**: manual per-agent procedure documented inline in `CHANGELOG.md`. Automation deferred deliberately — the daemon creates `~/.zeroclaw/agents/<alias>/` under whatever alias is in `config.toml`, so an unmoved state directory would lose all per-alias state on the alias rename. Safer behind an operator's eyes than embedded in a lifecycle op.
- **Byte-locked fixtures**: regenerated once (comment updates from the template rewrite). `| toq` filter added to `provider.type` on line 245 produced byte-identical output — all supported provider types are alphanumeric identifiers.
- **ATX**: iter-1 rating 3/5 (1 blocking, 3 warnings). All resolved in iter-1 except W3 (cross-module private import) — deferred per Callout because Python fails imports at import time (caught by test suite), not runtime. Iter-2 rating 4/5, no blockers. Cleared the > 3/5 + no-blockers gate on iter-2.

## Wolf-i UAT verification (post-fix)

```
$ clawctl agent shell clawrium-d01 -- "grep -E '^\[(agents|providers\.models|channels\.discord)\.' ~/.zeroclaw/config.toml"
[providers.models.litellm.clawrium_d01]
[channels.discord.clawrium_d01]
[agents.clawrium_d01]

$ clawctl agent chat clawrium-d01 --once "reply with just the word ok" --timeout 60
ok

$ # daemon_state.json components
channel:discord ok 0 None
channels        ok 0 None
daemon          ok 0 None
gateway         ok 0 None
heartbeat       ok 0 None
mqtt            ok 0 None
scheduler       ok 0 None
```

Heartbeat side-effect confirmed clean (was 7188 restart_count pre-fix per the plan).

## Test/lint status

- `make lint` — ruff clean, ESLint clean
- `make test` — 4847 python passed, 2 skipped; 329 GUI passed

---

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-09-07T20:35:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 980
```

**Output**: PR #981 opened against `main`, ATX iter-2 rating 4/5 with no blockers, wolf-i UAT (clawrium-d01) fully verified end-to-end including chat E2E probe.
