# Plan: `clawctl agent upgrade` + version bump (issue #592)

## Decisions

- **openclaw**: bump `2026.4.2` → **`2026.5.28`** (npm `latest` as of 2026-06-01).
- **hermes**: bump `2026.5.7` → **`v2026.5.29.2`** (GitHub latest stable as of 2026-06-01).
- **zeroclaw**: **no bump** — upstream stable is still `0.7.5`; only `v0.8.0-beta-1` exists and clawctl does not ship betas as defaults.
- `clawctl agent upgrade <name>` is **forward-only, max-only**: no `--version`, no `--allow-downgrade`. The issue's original plan listed those flags; both are dropped per execution direction.
- "Upgrade available" indicator lives in `gui/src/components/agent-detail/overview-tab.tsx`. No GUI button — CLI is the only mutation path.
- Drift pre-flight is **hard-fail** (no warn-and-prompt). `--skip-drift-check` is a hidden escape hatch.
- 2 install-verification subtasks (one per agent type whose version actually changes). Zeroclaw is unchanged so no subtask.

## Files to modify

| File | Change |
|---|---|
| `src/clawrium/platform/registry/openclaw/manifest.yaml` | Add `version: 2026.5.28` entries (Ubuntu 22.04 + 24.04, x86_64). Keep existing `2026.4.2` + `0.1.0` entries as historically supported. |
| `src/clawrium/platform/registry/openclaw/playbooks/install.yaml:7` | `claw_version \| default('v2026.5.28')` |
| `src/clawrium/platform/registry/hermes/manifest.yaml` | Add `version: 2026.5.29.2` entries (Ubuntu 22.04, 24.04, macOS ≥14). Compute fresh sha256 for `raw.githubusercontent.com/NousResearch/hermes-agent/v2026.5.29.2/scripts/install.sh`; apply same hash to all three entries (installer URL is identical across OSes — matches the existing manifest convention). Keep `2026.5.7` entries. |
| `src/clawrium/platform/registry/hermes/playbooks/install.yaml:7` | `claw_version \| default('v2026.5.29.2')` |
| `src/clawrium/cli/clawctl/agent/upgrade.py` (new) | `upgrade` subcommand. |
| `src/clawrium/cli/clawctl/agent/__init__.py` | Register `upgrade` in the agent typer app. |
| `src/clawrium/core/install.py` | No code change expected — `run_installation(force=True, claw_version=...)` already wired, and `hosts.json.agents.<name>.version` is written at install.py:562. Verify the upgrade path exercises the same write site. |
| `src/clawrium/gui/routes/agents.py` | Extend the agent-detail response with `latest_supported_version: str \| None`, derived from the registry filtered to entries matching the host's `os/os_version/arch`. |
| `gui/src/components/agent-detail/overview-tab.tsx:105` | Render an "Upgrade available → `<latest>`" badge next to the Version row when `agent.version < latest_supported_version`. Tooltip / inline hint: `Run: clawctl agent upgrade <name>`. |
| `website/docs/reference/cli/agent.md` | Rewrite the existing `### upgrade` section (line 539+): **remove** `--version` and `--restart` flags (lines 551–552); **add** `--yes`, `--skip-drift-check` (hidden, but mention in CLI reference), and `-o json`; rewrite the three example invocations (lines 558, 561, 564) to reflect max-only forward semantics; document the four pre-flight rejection cases (already-at-max no-op, downgrade rejection, drift rejection, drift bypass). No `docs/` mirror exists for this file (verified — mirror discipline in AGENTS.md applies only to `installation.md` and `host-preparation.md`). |

## CLI surface

```
clawctl agent upgrade <name> [--yes] [--skip-drift-check] [-o json]
```

Pre-flight, in order:

1. Resolve agent + host from `hosts.json`.
2. Gather host facts via the same path `run_installation` uses.
3. Build `allowed_set` = `[entry for entry in platforms if matches(entry, hardware)]`.
4. `target = max(allowed_set, key=Version)`.
5. **No-op exit** if `target == hosts.json.agents.<name>.version` (exit 0, "already at latest"). `run_installation` is NOT called.
6. **Hard reject downgrade**: if `target < installed`, fail with explicit message. Cannot happen via normal flow — only triggers if manifest entries are reordered/removed, which is the bug we want surfaced.
7. **Drift pre-flight**: invoke the same path `clawctl agent sync --dry-run` uses; refuse if any rendered file differs from on-host state. Prints the changed-file list. `--skip-drift-check` bypasses this gate.
8. Confirmation prompt unless `--yes` or `-o json`.

Execute:

- Call `run_installation(claw_name=<type>, host=..., agent_name=..., force=True)`. Matched-entry resolution inside it picks the right `claw_version` (and zeroclaw `claw_sha256`) automatically because the manifest's max is now the new version.
- `hosts.json.agents.<name>.version` updates at the existing write site (install.py:562).
- Route restart + re-pair through the canonical lifecycle so the zeroclaw `gateway_token_rotated` event fires per AGENTS.md §"Gateway Token Lifecycle". No-op for hermes; openclaw uses a static bearer.

## GUI "Upgrade available" wiring

- Backend: extend the agent-detail response in `gui/routes/agents.py` with `latest_supported_version`, computed as `max(version for entry in platforms if matches(entry, host_hardware))`. Returns `None` when no platform entry matches.
- Frontend: in `overview-tab.tsx`, when `latest_supported_version > agent.version`, render a yellow badge next to the Version row:
  ```
  Version: v2026.4.2 [↑ Upgrade available: v2026.5.28]
  Run: clawctl agent upgrade <name>
  ```
- No upgrade button. CLI is the only mutation path — matches the "CLI-driven upgrade" requirement and the pattern used by `configure`/`restart`.

## Test strategy

### `tests/cli/test_agent_upgrade.py` (new file)

Every happy-path and rejection test follows the same shape:
- **Patch** `run_installation` (and the drift-check helper where applicable).
- **Assert** exit code, stdout content, mock call args, AND on-disk `hosts.json` state.

| Test | Asserts |
|---|---|
| `test_upgrade_no_op_when_already_at_max` | exit_code == 0; stdout contains "already at latest"; `run_installation` NOT called; `hosts.json` version unchanged. |
| `test_upgrade_nochange_zeroclaw_exits_zero` | Zeroclaw at `0.7.5` with manifest max `0.7.5`: exit_code == 0; stdout contains "already at latest"; `run_installation` NOT called; `hosts.json` version unchanged. (Replaces the audit-flagged B1 test — bearer rotation cannot be exercised on zeroclaw because this PR does not bump its version. Bearer-rotation coverage on a real upgrade is tracked as a follow-up if/when zeroclaw bumps.) |
| `test_upgrade_rejects_drift` | exit_code != 0; stdout contains the changed-file list; `run_installation` NOT called; `hosts.json.agents.<name>.version` unchanged. |
| `test_upgrade_rejects_downgrade_attempt` | Synthetic manifest with installed > max: exit_code != 0; stdout names the version comparison; `run_installation` NOT called; `hosts.json` unchanged. |
| `test_upgrade_happy_path_openclaw` | Mock `run_installation` to succeed and update `hosts.json` to `2026.5.28`; assert `force=True` and `claw_version='v2026.5.28'` passed; **read back** `hosts.json.agents.<name>.version == '2026.5.28'`. |
| `test_upgrade_happy_path_hermes` | Same shape as openclaw, target `v2026.5.29.2`; read back `hosts.json` version. |
| `test_upgrade_json_output_mode` | Invoke with `-o json --yes`; exit_code == 0; `json.loads(stdout)` succeeds; assert keys `agent`, `from_version`, `to_version` present. |
| `test_upgrade_skip_drift_check_bypasses_preflight` | Drift-present state mocked; invoke with `--skip-drift-check --yes`; `run_installation` IS called; exit_code == 0. |

### `tests/core/test_registry_latest_supported.py` (new file)

| Test | Asserts |
|---|---|
| `test_latest_supported_per_host_filter` | For each (agent_type × OS × arch) tuple covered by the bundled manifests, the returned `latest_supported_version` is the max of host-compatible platform entries. |
| `test_latest_supported_returns_none_when_no_platform_matches` | Host with OS/arch absent from the manifest (e.g. openclaw on debian/aarch64) returns `None` — guards against `KeyError` in the GUI backend. |

### `tests/test_gui_agent_detail_latest_version.py` (new file — naming aligns with existing `tests/test_gui_*.py` convention)

| Test | Asserts |
|---|---|
| `test_agent_detail_includes_latest_supported_version` | GET on the agent-detail route returns `latest_supported_version` matching the registry's max for that host hardware. |
| `test_agent_detail_latest_supported_version_is_none_for_unmatched_host` | When the host's OS/arch has no platform entry, the response field is `None` (not omitted, not an empty string — matches `Optional[str]` typing). |

### `gui/src/components/agent-detail/overview-tab.test.tsx` (new file — does not exist today; confirmed via `ls gui/src/components/agent-detail/*.test.tsx`)

| Test | Asserts |
|---|---|
| `renders upgrade-available badge when latest_supported_version > agent.version` | Badge element present; text contains the latest version. |
| `does not render badge when latest_supported_version equals agent.version` | Badge element absent. |
| `does not render badge when latest_supported_version is null` | Badge element absent (covers the unmatched-host case). |

## Subtasks

1. `[Parent #592] Verify openclaw v2026.5.28 install on a single Ubuntu host` (24.04, x86_64). Fresh install + start + chat smoke; confirm `hosts.json.agents.<name>.version == 2026.5.28`.
2. `[Parent #592] Verify hermes v2026.5.29.2 install on a single Ubuntu host` (24.04, x86_64). Fresh install + start; binary `hermes --version` matches; `/health` returns 200 on the per-instance `api_server_port`.

(Zeroclaw verification subtask removed — manifest is untouched for zeroclaw.)

## Explicit non-goals

- No upstream polling. Registry is the contract.
- No GUI-initiated upgrade button. CLI only.
- No `--version`, no `--allow-downgrade`. One-way only.
- No `clawctl agent upgrade --all`. Single-agent in v1.
- No removal of older manifest entries. Older versions stay in `platforms[]` so existing installs continue to validate.
- Bearer-rotation coverage on a real zeroclaw upgrade. Cannot be exercised in this PR because zeroclaw's manifest max is unchanged; tracked as a follow-up when zeroclaw bumps.

## Related

- AGENTS.md §"Gateway Token Lifecycle (zeroclaw)"
- `src/clawrium/core/install.py:run_installation` (install.py:261, claw_version wiring at install.py:830, version write at install.py:562)
- `src/clawrium/core/registry.py:check_compatibility` (registry.py:933) and `describe_agent_type` (registry.py:804–839)
- `src/clawrium/platform/registry/{openclaw,zeroclaw,hermes}/manifest.yaml`
- `src/clawrium/platform/registry/{openclaw,hermes}/playbooks/install.yaml`
- `website/docs/reference/cli/agent.md` §`### upgrade` (line 539+)

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-01T00:00:00Z
**Model**: claude-opus-4-7

```prompt
https://github.com/ric03uec/clawrium/issues/592 review the plan for this. update all 3 support claw versions to their latest version(check from upsgream releases). update max version for each agent in the code. add 3 subtasks to test installation on the latest versions. add the new command for upgrading existing agents. i DO NOT want reversible path to be supported. only oneward path. if for an installed agent, the default agent has been upgraded, then show a button that upgrade is available and user shoudl run an upgrade command from cli to upgrade the agent. thsi shoulb eb in the agent settngs page. for each agent. show me plan first. ask if any thing is unclear
```

**Output**: High-level plan saved to `.itx/592/00_PLAN.md`; 2 subtask issues (#598 openclaw verify, #599 hermes verify) created and linked as sub-issues of #592; plan comment posted on #592; label flipped to `planned`. Plan refined via clarifying questions (skip zeroclaw bump, GUI indicator → overview tab, CLI upgrade-to-max only with no `--version` flag, drop zeroclaw verification subtask). Plan revised after audit pass to address 6 blockers + 5 warnings (test coverage gaps and stale `website/docs/reference/cli/agent.md`).
