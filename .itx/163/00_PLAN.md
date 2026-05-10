# Issue #163 — Implementation Plan

**Title**: OpenClaw: Skip reinstall when same version exists + add `--force` flag
**Milestone**: Beta-26.4.2
**Scope**: OpenClaw only (ZeroClaw / NemoClaw out of scope)

---

## Overview

Today the OpenClaw install playbook skips installation whenever any `openclaw` binary is on `PATH` (`src/clawrium/platform/registry/openclaw/playbooks/install.yaml:16-39`). It does not compare the installed version with the requested target version, so upgrades silently no-op. There is also no escape hatch for users to force a clean reinstall.

This plan introduces:

1. **Version-aware skip** in the install playbook — only skip when the installed binary's version matches the requested `claw_version`.
2. **A `--force` CLI flag** on `clm agent install` that propagates through `core.install.run_installation` to the playbook, bypassing the skip and forcing a fresh install.
3. **Full skip semantics** — on the skip path, also bypass `openclaw.json` template rewrite, gateway-token slurp/parse, the entire device-pairing block (`npm install ws`, `pair_device.mjs`), and the credential fact-save. Existing credentials in `hosts.json` are preserved verbatim. This is what makes "completes in seconds" actually true and prevents gateway-token / device-credential rotation that would invalidate any client holding the previous token.

---

## Current State (verified)

| Area | Reference | Behavior |
|------|-----------|----------|
| Install playbook | `src/clawrium/platform/registry/openclaw/playbooks/install.yaml:5-39` | Sets `openclaw_target_version` from `claw_version`. Sets `openclaw_already_installed = (which openclaw rc == 0)` — version is **not** compared. |
| Install download/run/cleanup tasks | `install.yaml:41-73` | Gated by `when: not openclaw_already_installed`. |
| Skip detection (Python) | `src/clawrium/core/install.py:155-174` (`_openclaw_install_was_skipped`) | Looks for the "Mark install as skipped..." task or the `openclaw_already_installed` fact in event stream. |
| Skip surfaced to caller | `src/clawrium/core/install.py:570-579` | Sets `install_skipped` + `skip_reason="already_installed"` in `InstallResult`. |
| Inventory `extra_vars` building | `src/clawrium/core/install.py:486-506` | Already passes `claw_version`, `claw_sha256`, `agent_name`, etc. — `force` would slot in here. |
| `run_installation` signature | `src/clawrium/core/install.py:177-184` | Currently accepts `cleanup_failed` and `resume`; needs new `force` kwarg. |
| CLI option layer | `src/clawrium/cli/install.py:175-200` and `src/clawrium/cli/agent.py:73-95` | Two entrypoints (`clm install` and `clm agent install`) both call `install_command(...)`. Both need `--force/-f`. **Note**: `-f` is already used as `--force` shorthand for *other* commands (e.g., `agent remove`, `agent start`) — pattern is consistent. |
| Existing skip tests | `tests/test_install_skip.py:80-281` | Asserts skip works regardless of version (the bug). Will need updates: rename/repurpose `test_install_existing_agent_any_version_reports_skip` to assert the *new* version-mismatch behavior. |

### `--version` output assumption

The plan in the issue uses `regex_search('([0-9]+\\.[0-9]+\\.[0-9]+)')` against the first line of `openclaw --version`. There is no fixture in the repo that documents the actual output. **Open question** captured in *Risks* below — implementation will defensively pick the first SemVer-like token from the first stdout line and fall back to forcing reinstall (treated as "version unknown ⇒ not a match") if parsing fails.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/clawrium/platform/registry/openclaw/playbooks/install.yaml` | (a) Add tasks to read installed version, parse it, and gate `openclaw_already_installed` on `installed_version == target_version`. (b) Honor `force_install` var to override skip. (c) Add `when: not openclaw_already_installed` gate to template-write, gateway-token slurp/parse/validate, the entire pairing block, and the credential fact-save (see Step 1.b below for the exact task list). |
| `src/clawrium/core/install.py` | Add `force: bool = False` param to `run_installation`. When true, inject `force_install: true` into inventory `vars`. Update `InstallResult.skip_reason` enum to include `"version_mismatch"` outcome path (no skip — proceeds with install). |
| `src/clawrium/cli/install.py` | Add `--force/-f` typer option to `install()`. Pass through to `_run_installation_with_progress` and `run_installation`. |
| `src/clawrium/cli/agent.py` | Add `--force/-f` typer option to the wrapper `install()` (line 73-95). Forward to `install_command(force=force)`. |
| `tests/test_install_skip.py` | (a) Update `test_install_existing_agent_any_version_reports_skip` → split into two tests: one for *matching* version (skip), one for *mismatching* version (no skip). (b) Add test that `force=True` causes installation to run even when version matches. |
| `tests/test_cli_install.py` | Add CLI-level test for `--force` flag presence and propagation. |
| **NEW** `tests/test_openclaw_version_check.py` *(optional)* | Pure-playbook fact assertions are hard without ansible — instead cover the parsing logic via small Python unit if any helper is extracted. Likely **not needed**; coverage will live in playbook integration through the existing test pattern. |

---

## Implementation Steps

### Step 1 — Playbook: version validation

In `install.yaml`, between the existing "Discover openclaw binary in PATH" task and "Set install skip condition":

```yaml
- name: Get installed openclaw version
  ansible.builtin.command: "{{ openclaw_which_result.stdout }} --version"
  register: openclaw_version_check
  changed_when: false
  failed_when: false
  when: (openclaw_which_result.rc | default(1)) == 0

- name: Parse installed openclaw version
  ansible.builtin.set_fact:
    openclaw_installed_version: >-
      {{ (openclaw_version_check.stdout | default('')) | regex_search('([0-9]+\.[0-9]+\.[0-9]+)') | default('', true) }}
  when:
    - openclaw_version_check is defined
    - (openclaw_version_check.rc | default(1)) == 0
```

Then update `Set install skip condition`:

```yaml
- name: Set install skip condition
  ansible.builtin.set_fact:
    openclaw_already_installed: >-
      {{ (openclaw_which_result.rc | default(1)) == 0
         and (openclaw_installed_version | default('')) == openclaw_target_version
         and not (force_install | default(false) | bool) }}
    openclaw_runtime_binary: "{{ openclaw_which_result.stdout if (openclaw_which_result.rc | default(1)) == 0 else '/home/' ~ agent_name ~ '/.openclaw/bin/openclaw' }}"
```

Keep the existing "Mark install as skipped" debug task; it remains valid and is what `_openclaw_install_was_skipped` keys off.

Add a parallel debug task for the new "force" path so logs are clear when a user passes `--force`:

```yaml
- name: Note that --force was supplied (overriding skip)
  ansible.builtin.debug:
    msg: "force=true: reinstalling OpenClaw at {{ openclaw_which_result.stdout | default('<no prior install>') }}"
  when:
    - (openclaw_which_result.rc | default(1)) == 0
    - force_install | default(false) | bool
```

### Step 1.b — Playbook: extend skip to template + pairing

In `install.yaml`, add `when: not openclaw_already_installed` to the following existing tasks (currently unconditional, lines from the file as it stands today):

| Line | Task |
|------|------|
| 95   | `Write openclaw config from template` *(prevents gateway-token rotation in `openclaw.json`)* |
| 163  | `Read gateway authentication token from config file` (slurp) |
| 170  | `Parse gateway token from config` |
| 175  | `Validate gateway token format` |
| 183  | `Copy device pairing script` |
| 191  | `Install ws package for pairing script` *(the `npm install ws` cost — primary motivation)* |
| 198  | `Run device pairing via localhost` *(rotates device credentials — must not run on skip)* |
| 206  | `Parse device credentials` |
| 211  | `Validate device credentials` |
| 226  | `Save all credentials to fact for retrieval` |

Tasks deliberately **NOT** gated (kept idempotent across skip and install paths):

- `Create agent user` — idempotent (`state: present`).
- `Create workspace directory`, `Create OpenClaw config directory` — idempotent.
- `Calculate unique port` — pure fact set.
- `Write exec approvals policy from template` — tracked separately by the `configure` flow; safe to keep in install for first-time bootstrap, idempotent if content matches.
- `Verify exec approvals JSON is valid` — read-only check.
- `Create environment file for agent` — `force: no`, never overwrites.
- `Create systemd service file` — uses computed `openclaw_runtime_binary`; idempotent if content matches; lets us recover if the unit file was deleted.
- `Enable and start openclaw service` — idempotent.
- `Wait for gateway port to be listening` — read-only, validates the existing service is healthy. Acts as a sanity check on the skip path.
- `Clean up pairing script`, `Clean up node_modules from pairing` — `state: absent` is idempotent (no-op when nothing to remove). Can stay ungated.

**Python side (`core/install.py`)** — no behavioral changes required for credential preservation:

- The credential extraction at lines 583-689 is best-effort; when the playbook does not emit the `openclaw_*` facts (skip path), all values stay `None`.
- `set_installed` (lines 717-734) only writes gateway/device config when `gateway_token and gateway_url` are truthy. So existing `hosts.json` credentials are preserved automatically. The existing test `test_install_reuses_existing_installed_name_and_reports_skip` already asserts this preservation.

One small refinement worth doing: when `install_skipped=True`, suppress the warnings at lines 691-701 ("Gateway token not captured") and lines 686-689 ("Gateway token capture failed - manual pairing may be needed"). They're misleading on the skip path — there was nothing to capture, by design.

### Step 2 — Core: `run_installation(force=...)`

In `src/clawrium/core/install.py`:

- Add `force: bool = False` to `run_installation` signature (line 177-184) and docstring.
- In the inventory `vars` block (line 496-505), inject:
  ```python
  "force_install": force,
  ```
- No changes needed to the skip-detection path — when `force=True`, the playbook will not emit the skip marker, so `_openclaw_install_was_skipped` returns `False` naturally.
- Suppress the "gateway token not captured" warnings (lines 691-701) and the "Gateway token capture failed" warning (lines 686-689) when `install_skipped is True`. Replace with a single info-level emit: `"Reusing existing gateway credentials (skip path)."` — only if `claw_record["config"]["gateway"]` already has `auth` + `device`. Otherwise keep the warning (corrupt state worth surfacing).

### Step 3 — CLI surface

In `src/clawrium/cli/install.py:175`:

```python
force: bool = typer.Option(
    False,
    "--force",
    "-f",
    help="Force reinstall even if the same version is already present",
),
```

Plumb `force` into both `_run_installation_with_progress(...)` calls (the initial and the cleanup-retry path) and through to `run_installation(... force=force)`. The `_run_installation_with_progress` helper signature also needs the new param.

In `src/clawrium/cli/agent.py:73-95`, mirror the same option on the wrapper `install()` and pass through:

```python
install_command(
    claw=claw, host=host, name=name,
    cleanup_failed=cleanup_failed, yes=yes, force=force,
)
```

**Decision: `-f` short flag.** Already used as short for `--force` in `agent remove`/`agent start`/etc. — keep the convention. (No collision in this command.)

### Step 4 — Tests

**`tests/test_install_skip.py`**:

1. Update `test_install_reuses_existing_installed_name_and_reports_skip`: keep as-is — installed `version: "2026.4.2"` matches manifest `2026.4.2`, so skip is still expected. The mocked playbook events should be augmented to include the new `Get installed openclaw version` and `Parse installed openclaw version` events with matching version. The skip detection should still fire.
2. **Repurpose** `test_install_existing_agent_any_version_reports_skip` (current name describes the bug) → rename to `test_install_existing_agent_different_version_proceeds_with_install`. Mock the playbook events such that `openclaw_installed_version != openclaw_target_version` and the "skip" marker is NOT emitted. Assert `result["skipped"] is not True` (or `False`/`None`) and that install proceeds.
3. Add `test_install_with_force_skips_skip_logic`: same setup as the matching-version test, but call `run_installation(..., force=True)` and assert the playbook receives `force_install=True` in inventory and the result is not skipped.
4. (Optional) Add `test_install_with_unparseable_version_proceeds_with_install`: covers the defensive fallback.
5. Strengthen `test_install_reuses_existing_installed_name_and_reports_skip` to also assert that `config.gateway.device` (id/token/privateKey) is preserved unchanged across the skip — proves pairing did not re-run and rotate credentials. Mock the playbook event stream to NOT include the `openclaw_device_token` / `openclaw_device_id` facts on the skip path (mirrors the new gating).

**`tests/test_cli_install.py`**: add a test that invokes the typer command with `--force` and asserts it propagates to `run_installation` (mock and inspect kwargs). Mirror for `clm agent install --force` if there is matching coverage.

### Step 5 — Docs

Update `docs/agent-support/openclaw.md` and `website/docs/agent-support/openclaw.md` if they describe install behavior. Add a short note about version-aware skip and the `--force` flag. (Only if existing docs cover install — quick check during execution, skip if absent.)

---

## Test Strategy

| Layer | Test |
|-------|------|
| Unit / mock | `tests/test_install_skip.py` covers the four scenarios: matching version → skip, mismatching version → install, `force=True` → install, unparseable version → install. |
| CLI | `tests/test_cli_install.py` verifies `--force` is recognized and forwarded. |
| Lint | `make lint` passes (typer option formatting). |
| Make targets | `make test` then `make lint`. |
| Manual (deferred) | On a real host with OpenClaw v2026.4.2 installed: re-running `clm agent install --type openclaw --host <h>` completes in seconds with skip message. Running with `--force` re-downloads. Installing a manifest pointing at a different version triggers a download. (Owner to perform; not part of CI.) |

---

## Risks & Open Questions

1. **`openclaw --version` output format is not documented in this repo.** If the binary prints something non-trivial (e.g., multiline, includes a `v` prefix, prints to stderr), the regex may fail to match. Mitigations:
   - `regex_search` returns empty string on no match → `openclaw_already_installed` becomes `false` → install proceeds (safe-default to "reinstall").
   - Document the expected format in a comment in the playbook.
   - Suggested follow-up: run `openclaw --version` against the current pinned version once and add a fixture in `tests/fixtures/`.
2. **Pairing & template rewrite are now also skipped** — addressed in Step 1.b. Side-effect: the existing gateway token in `openclaw.json` and the device credentials in `hosts.json` are now stable across re-runs. If a user has somehow lost their local credentials (manual edit, partial deletion), they must use `--force` to trigger a fresh pair. This is the correct trade-off — silent rotation on every install was the riskier behavior.
3. **`force_install` variable name** — `extra_vars` already use snake_case (`agent_name`, `claw_version`, `claw_sha256`); `force_install` keeps the convention and avoids colliding with Ansible's built-in `force` semantics on individual modules.
4. **Backwards compat with PR #175 tests** — the second skip test today asserts the *bug* (skip on any version). Renaming + flipping the assertion is intentional; PR description should call this out so reviewers know it is a deliberate behavior change.

---

## Subtask Decision

**No subtasks.** Scope touches 4 files (1 playbook + 1 core module + 2 CLI shims) plus tests; concerns are tightly coupled and best landed atomically (the playbook change without the `force` flag would leave users no escape hatch when version parsing breaks). Single-PR execution preferred.

---

## Definition of Done

- [ ] Playbook validates installed version against `claw_version` and only skips on match.
- [ ] On the skip path, no template rewrite, no `npm install ws`, no pairing — gateway token and device credentials in `hosts.json` are byte-identical before/after.
- [ ] `--force/-f` flag added to both `clm install` and `clm agent install`.
- [ ] `run_installation(force=...)` plumbs the flag into ansible inventory `vars` as `force_install`.
- [ ] Tests cover: match-skip (with credential preservation), mismatch-install, force-install, parse-failure-install.
- [ ] `make test` and `make lint` pass.
- [ ] PR body documents the test-rename / behavior change called out in Risks #4 and the silent-rotation fix in Risks #2.
- [ ] `.itx/163/00_PLAN.md` committed.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-09T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 163
```

</details>
