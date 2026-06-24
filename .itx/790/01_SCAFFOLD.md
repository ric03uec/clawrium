# Execution Scaffolding — Issue #790

[bug] GUI shows stale model on agent landing page — eliminate `config.*` mirror in `hosts.json`

**Mode**: multi-phase (4 phases, sequential)

The high-level plan and test strategy live in the issue body itself (no `00_PLAN.md`; the plan was drafted inline). This scaffold defines the entry/exit gates for each phase so PRs can be reviewed against a fixed contract instead of "looks done."

## Phase summary

| Phase | Goal | Risk | Reverts cleanly? |
|---|---|---|---|
| 1 | Fix the GUI read path — ships the user-visible bug fix | low | yes |
| 2 | Stop writing `config.provider` / `config.providers` / `config.channels` | medium (touches lifecycle persistence) | yes (revert restores writes) |
| 3 | Prune existing `config.*` mirrors from `hosts.json` on load | medium (touches `load_hosts` — high blast radius) | yes (revert leaves keys in place) |
| 4 | Delete now-unreachable code + defensive comments | low | yes |

Phases are **sequential** — each phase's exit is the next phase's entry. No parallelism. Phase 3 in particular MUST be its own PR so its loader change can be reverted in isolation if a downstream tool breaks.

---

## Phase 1: Fix the read path

**Files affected**:
- `src/clawrium/cli/tui/data.py` — add helper, replace 3 duplicated provider-resolution blocks, update `_resolve_provider_name` docstring
- `src/clawrium/cli/clawctl/agent/describe.py` — drop `config.get("channels")` fallback at line 83
- `tests/test_tui/test_tui_data.py` — unit tests for the helper + regression test for tier-2 stale immunity
- `tests/test_gui_routes_fleet.py` — end-to-end serializer assertion

**Entry criteria**:
- Issue #790 open with label `ready`
- Working tree clean on a fresh branch off `main`
- Local `~/.config/clawrium/hosts.json` contains at least one agent whose tier-1 attached provider differs from tier-2 `config.provider` (for manual reproduction). If not, attach a different provider to any agent and skip the post-attach sync.

**Exit criteria**:
- Helper `_resolve_provider_display(claw_record)` exists in `cli/tui/data.py`, returns `(provider_name, provider_type, model)` with the documented precedence (tier-1 entry `model` > `providers.json` `default_model`; `provider_type` always from `providers.json`).
- Zero occurrences of `provider_cfg.get("default_model"` or `config.get("provider")` remain in `cli/tui/data.py`.
- `cli/clawctl/agent/describe.py` no longer reads `config.get("channels")`.
- `_resolve_provider_name` docstring no longer mentions "display-only enrichment."
- New tests (each MUST be present and passing):
  - `test_resolve_provider_display_attachment_override` — tier-1 `model` wins over `providers.json` `default_model`
  - `test_resolve_provider_display_falls_back_to_providers_json` — when attachment has no `model`, `providers.json[name].default_model` is used
  - `test_resolve_provider_display_missing_provider_record` — unresolved attachment → `("-", None, "-")` + logged warning, no exception
  - `test_resolve_provider_display_no_attachment` — `(None, None, "-")`
  - `test_build_agent_identity_ignores_stale_tier2_provider` — **regression test for the original bug**; fixture has tier-1 = `glm51` AND a leftover `config.provider.default_model = "openai/gpt-4o"`; `_build_agent_identity` returns `model == "z-ai/glm-5.1"`. Keep forever.
  - `test_fleet_endpoint_returns_tier1_model` — `/fleet` JSON response carries the tier-1 model for the same fixture
- `make lint && make test` clean.
- Manual verification: hit `http://127.0.0.1:36000/agents?key=clawrium-exec` against the running GUI and confirm the model column matches `clawctl agent get clawrium-exec`.
- PR opened, reviewed, merged. PR body cross-references #790.

**Dependencies**: None.

**Complexity**: moderate (one helper + tests, three duplicated callsite collapses).

---

## Phase 2: Stop writing Group A

**Files affected**:
- `src/clawrium/core/lifecycle.py` — `sync_agent` (1410–1682) stops mutating `existing_config["provider"]` / `existing_config["providers"]`; channels persistence at 2878–2892 deleted
- `src/clawrium/cli/agent.py` — channels writes at `:379` and `:745` deleted
- `tests/test_lifecycle.py`, `tests/cli/clawctl/agent/test_sync_hermes_multi_provider.py` — assertions tightened to confirm Group A keys are absent from persisted state

**Entry criteria**:
- Phase 1 merged to `main`.
- A real-host agent available (wolf-i or mac-test) where Phase 2 can be exercised end-to-end before merge.

**Exit criteria**:
- `configure_agent` accepts a `provider_extravars` kwarg (or equivalent) so the legacy ansible-extravar path receives the overlay without folding it into the persisted config dict.
- After `lifecycle.sync_agent` completes, `claw_record["config"]` for the synced agent contains no `provider`, `providers`, or `channels` key (asserted in test 5 and test 6 from the issue body).
- The ansible-extravar payload still contains the overlay (asserted via mocked ansible-runner call args).
- Updated tests:
  - `test_sync_agent_does_not_persist_provider_overlay` — covers singleton (openclaw/zeroclaw)
  - `test_sync_agent_does_not_persist_providers_overlay_hermes` — covers multi-provider (hermes)
  - `test_sync_agent_does_not_persist_channels` — covers the channels writer at `lifecycle.py:2878-2892`
  - `test_configure_agent_passes_provider_extravars` — confirms the new kwarg reaches ansible
- Real-host verification (integration test 8 from issue, MUST be run on wolf-i for at least hermes + openclaw):
  1. Baseline: `clawctl agent get <name>` + dump agent record from `hosts.json`.
  2. `clawctl agent provider attach <other> --agent <name>` → `clawctl agent sync <name>`.
  3. Confirm: model on host == model in `clawctl agent get` == model in GUI; `hosts.json` agent record has no fresh `config.provider/providers/channels` writes (existing stale entries from before Phase 3 may persist).
- `make lint && make test` clean.
- PR opened, reviewed, merged. PR body links the wolf-i transcript.

**Dependencies**: Phase 1.

**Complexity**: complex (touches the persistence path through `lifecycle.sync_agent` which has several call sites and historical comments).

---

## Phase 3: Prune existing `hosts.json` on load

**Files affected**:
- `src/clawrium/core/hosts.py` — normalizer in `load_hosts()` strips Group A keys
- `tests/core/test_hosts.py` — round-trip pruning test
- `CHANGELOG.md` (root, `### Changed` under `[Unreleased]`)

**Entry criteria**:
- Phase 2 merged. (Otherwise Phase 2's writers would immediately repopulate the keys this phase prunes.)

**Exit criteria**:
- `load_hosts()` returns agent records where `config.provider`, `config.providers`, `config.channels` are absent regardless of whether they exist on disk.
- `save_hosts()` after a `load_hosts()` round-trip produces a file without those keys (idempotent — second round trip is a no-op).
- Group B keys (`config.gateway.*`, `config.dashboard.*`, `config.api_server.*`) preserved byte-for-byte (asserted via diff in test 4 from issue).
- New tests:
  - `test_load_hosts_strips_config_provider`
  - `test_load_hosts_strips_config_providers`
  - `test_load_hosts_strips_config_channels`
  - `test_load_hosts_preserves_group_b` — gateway/dashboard/api_server keys round-trip unchanged
  - `test_load_save_round_trip_is_idempotent`
- Real-host integration suite (tests 8–10 from issue) green on wolf-i AND mac-test:
  - For each agent type (hermes, zeroclaw, openclaw): attach a different provider → sync → confirm model parity across host/CLI/GUI AND `hosts.json` agent record has none of `config.provider/providers/channels`.
  - `clawctl agent chat` works for hermes + openclaw (depends on `config.gateway.auth`, Group B).
  - `clawctl agent open` works for hermes, zeroclaw, openclaw (depends on `config.dashboard.port` / `config.gateway.port`, Group B).
- `CHANGELOG.md` updated under `### Changed` describing the on-disk shrink (no operator action required).
- `make lint && make test` clean.
- PR opened, reviewed, merged. PR body links the wolf-i + mac-test transcripts.

**Dependencies**: Phase 2.

**Complexity**: moderate (single change to `load_hosts`; risk is in the test sweep and the real-host verification matrix).

---

## Phase 4: Delete now-unreachable code

**Files affected**:
- `src/clawrium/core/lifecycle.py` — drop comments at `:1393-1394, 1671-1672` and any code branches whose only purpose was feeding the deleted writes
- `src/clawrium/cli/clawctl/agent/_shared.py` — drop the defensive note at `:120`
- `src/clawrium/cli/agent.py` — drop the defensive note at `:737`
- `src/clawrium/cli/clawctl/agent/provider.py` — drop the "last-known-good" comment at `:261, 311`

**Entry criteria**:
- Phase 3 merged.

**Exit criteria**:
- `grep -rn 'config\["provider"\]\|config\.get("provider")\|config\["providers"\]\|config\.get("providers")\|config\["channels"\]\|config\.get("channels")' src/clawrium/` returns zero hits (excluding Group B references like `config["gateway"]`).
- No comments in `src/clawrium/` mention "config.provider stays populated for back-compat" or "NO fallback to config[\"provider\"]" — both rationales are obsolete once the field doesn't exist.
- Full test suite still passes (the regression test from Phase 1 keeps the immunity gate alive even after the dead code is removed).
- `make lint && make test` clean.
- PR opened, reviewed, merged. PR closes #790.

**Dependencies**: Phase 3.

**Complexity**: simple (pure deletion + comment removal, no behavior change).

---

## Out of scope (tracked separately)

Retiring `lifecycle.sync_agent`'s ansible-extravar path entirely — routing `clawctl agent configure`'s per-stage flow through `build_render_inputs` + canonical renderer the way `clawctl agent sync` already does — is a larger refactor that touches Ansible templates and the onboarding walk. Worth its own issue. Track as a follow-up after Phase 4 lands.

---

## Prompt Log

### Scaffolding

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-06-23T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 790 crate file and send pr once scaffold is created
```

**Output**: `.itx/790/01_SCAFFOLD.md` with four-phase entry/exit criteria; phase sub-issues created and linked; issue #790 relabeled from `planned` → `ready`; PR opened against `main` carrying just the scaffold file.
