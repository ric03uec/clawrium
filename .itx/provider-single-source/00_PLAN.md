# Provider Single-Source-of-Truth — Implementation Plan

> No open GitHub issue tracks this bug; slug `provider-single-source`.
> The BREAKING entry for this change is already written in the root
> `CHANGELOG.md` under `## [Unreleased]`.

## Overview

Provider state is read inconsistently across the codebase. The render /
drift / upgrade path (`build_render_inputs`) reads provider attachments
from exactly **one** place — the tier-1 top-level `providers` list — and
fails fast when it is empty. The display path (`_first_provider`, used by
`clawctl agent get` / `describe`) is more tolerant: it falls back through
**three** tiers (tier-1 `providers` list → tier-2 `config.provider.name`
→ tier-3 vestigial `config.providers` plural).

This asymmetry is the bug: an agent whose provider lives only in tier-2
(the common state for agents onboarded via a sync-only flow, e.g. `vand`
and `doppio` before back-fill) **shows a provider in `agent get` but
fails render/drift/upgrade** with a false-positive
`AgentConfigError: agent '<name>' has no provider attached`.

The fix: make tier-1 (`providers` list) the **single source of truth** for
reading provider state. Collapse `_first_provider` to read tier-1 only and
return `None` (no fallback) when it is empty or malformed. This makes the
display path agree with the render path. `build_render_inputs` already
behaves correctly and needs **no change**.

### Outcome

- Exactly one place provider state is read from: tier-1 `providers` list.
- `_first_provider` and `build_render_inputs` agree on whether a provider
  is attached for every agent record.
- No silent fallback: a record with provider only in tier-2/tier-3 now
  reads as "no provider" everywhere (consistent), so the operator gets a
  clear, uniform signal to run `clawctl agent provider attach`.
- The vestigial tier-3 (`config.providers` plural) handling is removed
  from the code entirely.

## Files to Modify

| File | Change |
|---|---|
| `src/clawrium/cli/clawctl/agent/_shared.py` | Collapse `_first_provider` (lines 111-178) to tier-1 only; delete tier-2 (155-160) and tier-3 (162-177) blocks; rewrite docstring. |
| `tests/cli/clawctl/agent/test_get_describe.py` | Remove/invert the tier-2 and tier-3 fallback cases; add explicit "tier-2-only record reads as None" regression test. |

## Files to Create

None.

## Steps

1. **Collapse `_first_provider` to tier-1 only** in
   `src/clawrium/cli/clawctl/agent/_shared.py:111-178`. New body keeps the
   `_accept` helper (PROVIDER_NAME_PATTERN validation) and the tier-1 read,
   then returns `None`:

   ```python
   def _first_provider(claw_record: dict) -> Optional[str]:
       """Surface the attached provider name for the describe/get row.

       Provider state is read from a SINGLE source of truth: the tier-1
       top-level ``claw_record["providers"]`` attach list (Pattern A;
       #426/#509). This is the same list `build_render_inputs` reads, so
       the display path and the render/drift/upgrade path always agree.

       There is NO fallback to `config.provider` (the materialized render
       payload) or to the vestigial `config.providers` plural key. A record
       with no tier-1 attachment reads as "no provider" everywhere; the
       operator recovers with `clawctl agent provider attach`.

       Accepts both `["name"]` (string entries) and `[{"name": "..."}]`
       (dict entries) shapes. String entries are validated against
       PROVIDER_NAME_PATTERN; mismatches return None.
       """
       from clawrium.core.providers.storage import PROVIDER_NAME_PATTERN

       def _accept(value: object) -> Optional[str]:
           if isinstance(value, str) and value and PROVIDER_NAME_PATTERN.match(value):
               return value
           return None

       attached = claw_record.get("providers")
       if isinstance(attached, list) and attached:
           first = attached[0]
           accepted = _accept(first)
           if accepted:
               return accepted
           if isinstance(first, dict):
               return _accept(first.get("name"))
       return None
   ```

   This deletes the tier-2 block (old lines 155-160) and the tier-3
   vestigial-plural block (old lines 162-177).

2. **Leave `build_render_inputs` (`src/clawrium/core/render.py:243-250`)
   unchanged.** It already reads tier-1 only and raises `AgentConfigError`
   when empty — this is exactly the single-source / fail-fast behavior we
   want. The fix is to bring the *display* reader in line with it, not the
   other way around.

3. **Do NOT remove the tier-2/tier-3 writes in `lifecycle.py`.** See
   Risk R1: `config["provider"]` (and hermes `config["providers"]`) at
   `lifecycle.py:1480` / `:1496` are the **render payload** consumed by
   `configure_agent` / the Ansible templates — not an independent read
   source. They are *derived from* tier-1 (`_build_overlay` reads the
   tier-1 attachments). Removing them would break remote rendering. The
   USER decision "stop writing tier-2" is satisfied by stopping the use of
   tier-2 as a **READ source** (step 1); the writes that remain are render
   inputs, not a competing source of truth.

4. **Sweep for other tier-2/tier-3 *readers*.** `grep -rn
   "config\\[.provider" "config.get(.provider" "config\\[.providers"` in
   `src/` (excluding the lifecycle render-payload writes). Confirm no other
   code reads provider identity from `config.provider`/`config.providers`.
   Known tier-1 readers (`provider.py:63/79`, `lifecycle.py` overlay
   builder, `configure.py:100` writer) are already correct.

5. **Rewrite the tests** (see Test Strategy), then run `make lint` and
   `make test`.

## Test Strategy

### Unit (`tests/cli/clawctl/agent/test_get_describe.py`)

| Existing test | Action |
|---|---|
| `test_first_provider_prefers_attach_list_string` | KEEP (tier-1 string entry resolves; stale tier-2 ignored — now ignored by design). |
| `test_first_provider_prefers_attach_list_dict_entry` | KEEP (tier-1 dict entry resolves). |
| `..._falls_back_to_materialized_config_provider` | INVERT → rename to `..._ignores_materialized_config_provider`; assert returns `None` when provider lives only in tier-2. |
| `..._skips_empty_attach_list_then_uses_materialization` | INVERT → empty tier-1 + populated tier-2 now returns `None`. |
| `..._returns_none_when_nothing_present` | KEEP. |
| `..._vestigial_plural_path_still_resolves` | INVERT → rename to `..._ignores_vestigial_plural_path`; assert `None`. |
| `..._dict_entry_without_name_falls_through_to_materialization` | REWRITE → tier-1 dict entry without `name` now returns `None` (no tier-2 fallback). |
| `..._empty_string_attach_entry_falls_through` | REWRITE → empty/invalid tier-1 string entry returns `None`. |
| `..._never_synced_agent_shape` | KEEP (already expects `None`). |

Add one new regression test:
`test_first_provider_tier2_only_record_reads_as_none` — builds a record
shaped exactly like `vand`/`doppio` before back-fill (`providers` absent,
`config.provider = {"name": "esper-bedrock", ...}`) and asserts
`_first_provider(...) is None`, documenting the display/render agreement.

### End-to-end manual (against host `clawdmin`, 192.168.20.44)

Run all clawctl via `uv run clawctl ...`.

1. `uv run clawctl agent get` — confirm `doppio` (tier-1 back-filled)
   still shows its provider; STATUS unaffected.
2. `uv run clawctl agent sync doppio --diff` — confirm the render path
   still resolves the provider (drift diff renders, no `AgentConfigError`).
3. Construct/inspect a tier-2-only record (or temporarily clear `vand`'s
   tier-1 in a scratch copy of hosts.json) and confirm `agent get` now
   shows **no provider** for it — i.e. display and render agree that it
   needs an attach. Restore afterward.
4. Re-attach if needed: `uv run clawctl agent provider attach
   esper-bedrock --agent vand` and confirm both paths see it again.

## Risks

- **R1 — "stop writing tier-2" could be misread as deleting the render
  payload.** `config["provider"]`/`config["providers"]` at
  `lifecycle.py:1480/1496` are the Ansible render inputs, derived from
  tier-1; they are not a competing read source. DECISION: do not touch the
  writes; only remove tier-2/tier-3 as **read** sources (the actual bug).
  This fully satisfies the single-source-of-truth requirement because the
  only thing reading provider *identity* after this change is tier-1.

- **R2 — back-compat for legacy records with provider only in tier-2.**
  After this change they read as "no provider" in `agent get` (previously
  shown via fallback). This is intentional (hard cutover, no migration —
  USER decision). Recovery is a single `clawctl agent provider attach`.
  Documented as BREAKING in `CHANGELOG.md [Unreleased]`. The render path
  already failed for these records, so `get`/render now simply agree.

- **R3 — handwritten/third-party records using `config.providers`
  plural.** These lose their last reader. Acceptable: the key was
  explicitly vestigial; the BREAKING note instructs operators to attach.

## Subtasks

1. Collapse `_first_provider` to tier-1 only (`_shared.py`).
2. Grep-sweep `src/` for other tier-2/tier-3 provider readers; remove any.
3. Rewrite/invert the `_first_provider` unit tests + add the tier-2-only
   regression test.
4. `make lint && make test`.
5. E2E re-validation against `clawdmin` (doppio render/drift path).

<details>
<summary>Prompt Log</summary>

**Stage**: plan
**Skill**: (none — direct request)
**Timestamp**: 2026-06-02T16:04:41Z
**Model**: claude-opus-4-8

```prompt
whats the fix for th eoriginal issue now
...
create a plan and outcomes and testing strategy first. put in a plan file acording to exising format
```

**Output**: `.itx/provider-single-source/00_PLAN.md` — implementation plan
to collapse `_first_provider` to a single tier-1 source of truth (no
fallback), aligning the display reader with the render reader, with a
test rewrite matrix and an E2E re-validation strategy against the
`clawdmin` host.

</details>
