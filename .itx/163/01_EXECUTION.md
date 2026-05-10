# Issue #163 — Execution Scaffolding

**Mode**: single-phase

**Rationale**: 6 files (1 playbook + 1 core + 2 CLI shims + 2 tests). Per the plan (`.itx/163/00_PLAN.md`), the changes are tightly coupled — the playbook version-match logic, the pairing-skip gates, and the `--force` plumbing must land together. Splitting into separate PRs would either ship a half-feature (e.g., playbook tightened without an escape hatch) or silently rotate credentials between intermediate states. One PR, one phase.

---

## Phase 1: Version-aware skip + `--force` + pairing skip

**Entry Criteria** (must be true to start):

- [x] `.itx/163/00_PLAN.md` exists and is current
- [x] Issue #163 has `planned` label
- [ ] Working tree is clean
- [ ] Branch created from `main`: `issue-163-openclaw-skip-force`

**Files Affected**:

| File | Change Type | Notes |
|------|-------------|-------|
| `src/clawrium/platform/registry/openclaw/playbooks/install.yaml` | Modify | Add version parse, gate `openclaw_already_installed` on version-match + `force_install`, add `when: not openclaw_already_installed` to template-write + slurp/parse/validate-token + pairing block + credential fact-save |
| `src/clawrium/core/install.py` | Modify | Add `force: bool = False` to `run_installation`, inject `force_install` into inventory `vars`, suppress credential warnings on skip path |
| `src/clawrium/cli/install.py` | Modify | Add `--force/-f` typer option, plumb to `run_installation` |
| `src/clawrium/cli/agent.py` | Modify | Mirror `--force/-f` on the `clm agent install` wrapper, forward to `install_command` |
| `tests/test_install_skip.py` | Modify | Rewrite the buggy "any-version-skips" test into match-skip + mismatch-install pair; add force test; add parse-failure test; assert credential preservation |
| `tests/test_cli_install.py` | Modify | Add `--force` propagation test |

**Internal Sequencing** (within the phase, in order):

1. **Playbook — version detection**
   - Add `Get installed openclaw version` task (gated on `openclaw_which_result.rc == 0`)
   - Add `Parse installed openclaw version` task (regex_search for SemVer)
   - Update `Set install skip condition` to require `installed_version == target_version` AND `not (force_install | default(false) | bool)`
   - Add `Note that --force was supplied` debug task for log clarity
   - **Verify**: playbook YAML parses (`ansible-playbook --syntax-check`)

2. **Playbook — extend skip to template + pairing**
   - Add `when: not openclaw_already_installed` to the 10 tasks listed in `00_PLAN.md` Step 1.b table
   - **Verify**: playbook YAML parses

3. **Core — `force` plumbing**
   - Add `force: bool = False` parameter to `run_installation` (signature + docstring)
   - Inject `"force_install": force` into inventory `vars` block
   - On skip path, suppress the "gateway token not captured" / "Gateway URL not captured" / "Gateway token capture failed" warnings; emit a single info-level "Reusing existing gateway credentials" message instead
   - **Verify**: `python -c "from clawrium.core.install import run_installation"` imports clean

4. **CLI — `--force` flag**
   - `cli/install.py`: add `force` typer option, pass to `_run_installation_with_progress` and `run_installation` (both the initial call and the cleanup-retry call)
   - `cli/install.py`: update `_run_installation_with_progress` signature to accept and forward `force`
   - `cli/agent.py`: add matching `--force/-f` option to wrapper `install()`, forward via `install_command(force=force)`
   - **Verify**: `clm agent install --help` shows `--force/-f` in output

5. **Tests — update existing**
   - `tests/test_install_skip.py::test_install_reuses_existing_installed_name_and_reports_skip`: add events for `Get installed openclaw version` + `Parse installed openclaw version` returning matching version; add assertion that `config.gateway.device` is preserved unchanged (proves pairing did not re-run)
   - `tests/test_install_skip.py::test_install_existing_agent_any_version_reports_skip`: rename to `test_install_existing_agent_different_version_proceeds_with_install`; flip events to mismatching version + no skip marker; assert `result["skipped"] is not True`

6. **Tests — add new**
   - `tests/test_install_skip.py::test_install_with_force_skips_skip_logic`: matching-version setup, call `run_installation(..., force=True)`, assert `force_install=True` was in inventory `vars` and result is not skipped
   - `tests/test_install_skip.py::test_install_with_unparseable_version_proceeds_with_install`: defensive fallback coverage
   - `tests/test_cli_install.py::test_install_force_flag_propagates`: invoke typer with `--force`, mock `run_installation`, assert `force=True` was passed

7. **Verification**
   - `make test` — all green
   - `make lint` — clean
   - `make format` if needed
   - Manual: `clm install --help` and `clm agent install --help` both show `--force/-f`

**Exit Criteria** (must be true to complete):

- [ ] All 6 files modified per the plan
- [ ] `make test` passes (existing + 4 new test cases)
- [ ] `make lint` passes
- [ ] `clm agent install --help` shows `--force, -f` option
- [ ] `clm install --help` shows `--force, -f` option
- [ ] No new TODOs / commented-out code
- [ ] `.itx/163/` directory committed alongside source changes
- [ ] PR body documents:
  - The buggy-test rewrite (Risks #4 in plan)
  - The silent-rotation fix in pairing path (Risks #2 in plan)

**Dependencies**: None (single phase)

**Complexity**: moderate

**Estimated Effort**: 2-3 hours implementation + 1 hour testing/iteration

---

## Risks Carried Forward From Plan

1. `openclaw --version` output format unverified in repo — defensive regex falls back to "reinstall" on parse failure (safe).
2. Skip path now preserves credentials — manual corruption requires `--force` recovery (intentional trade-off, accepted).
3. `cleanup_failed` and `force` remain orthogonal flags — compose naturally.

---

## Manual Verification Checklist (deferred to owner; not part of CI)

On a real host with OpenClaw installed at the manifest's pinned version:

- [ ] `clm agent install --type openclaw --host <h>` completes in < 10s, log shows "OpenClaw already installed... Skipping binary install"
- [ ] `hosts.json` `config.gateway.device` field is byte-identical before/after
- [ ] `clm agent install --type openclaw --host <h> --force` performs full reinstall + re-pair, generates new device credentials
- [ ] Bumping manifest version → install proceeds with download

---

<details>
<summary>Prompt Log</summary>

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-09T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 163
```

</details>
