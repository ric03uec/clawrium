## Issue Creation

**Stage**: issue-creation
**Skill**: /itx-issue-new
**Timestamp**: 2026-10-06T01:45:51Z
**Model**: openai/gpt-6-sol

```prompt
add new issue to auto-generate ssh key-pair for each agent during installation. control machine should generate this keypair and store it in the respective machines ssh folder during initialiation. the copy will remain on the control host as well. the cli for the agent should show the public key and redact the private key when user checks agent details. no other actions will be allowed for now. only during agent reset will a new keypair be generated. for existing machiens, this flow should be idempotent. everytime a new sync happens, this flow should crete a new ssh keypair if one doesnt exist. this is a system level flow, not agent level so keep it as such int he ansible workflow.

Customer outcome clarification: Auto generate ssh keypair during agent installation
```

**Output**: Created [Auto generate ssh keypair during agent installation](https://github.com/ric03uec/clawrium/issues/1041) with shared system-level Ansible provisioning, sync backfill and idempotency, details redaction, and reset-only rotation requirements.

## Implementation Plan — #1041

**Outcome:** Each agent has its own SSH keypair generated and retained on the control machine, with a matching pair in that agent user's `~/.ssh` on the target host. Existing agents acquire one on their next sync; routine lifecycle operations never rotate it.

### Approach

1. Add a per-host/per-agent Ed25519 key store in `src/clawrium/core/keys.py`, **outside** the management-key tree: e.g. `~/.config/clawrium/agent-keys/<host-key-id>/<agent-name>/id_ed25519{,.pub}`. `core/reset.py` calls `delete_host_keys()` on the entire `keys/<host-key-id>/` tree, so nesting agent keys there would rotate them on host reset. Resolve the stable host `key_id` (not the mutable hostname), validate each path component, reject symlinks, create directories with 0700 and files with 0600/0644, and validate the existing public key against the private key. Publish a pair atomically (temporary files and exclusive destination creation / lock) so concurrent syncs and interrupted writes cannot replace an existing identity.
2. Define a single `ensure_agent_ssh_identity(host, agent_name, ...)` orchestration path, shared by install and sync. Inspect the remote destination **before** generating a missing controller pair: both sides absent → generate and provision; matching pair → no-op; controller present and remote absent → restore; partial remote → restore only absent files if every existing component matches; controller absent but remote occupied, local partial/corrupt, remote mismatch, or unsafe path → fail with a recovery hint, no rotation. Derive/check public identities without printing remote private bytes. Explicit agent reset is the *only* future rotation owner; no agent-reset operation exists yet, and host reset must not delete the agent key store.
3. Create shared `src/clawrium/platform/playbooks/agent_ssh_keys.yaml` and `agent_ssh_keys_macos.yaml`, dispatched exclusively from `src/clawrium/core/playbook_resolver.py`. Use a read-only preflight for remote state before new-key creation, then a write phase that rechecks and safely copies controller file paths via Ansible `copy` (not key bytes as inventory/extravars). Mark secret-bearing tasks `no_log: true`, avoid plaintext runner artifacts, and report only safe states. Require an existing agent user; use `/home/{{ agent_name }}` + group `{{ agent_name }}` on Linux, `/Users/{{ agent_name }}` + group `staff` on macOS; `~/.ssh` 0700, private 0600, public 0644. Never use `ansible_user_dir` or add this to agent-specific playbooks.
4. Call the shared flow in `src/clawrium/core/install.py` immediately after the successful agent-type install playbook, including the binary-skip/reinstall path, before marking the record installed. Call it in `src/clawrium/core/lifecycle_canonical.py:sync_agent_canonical` on every real sync, before workspace-only / CLI-only early returns or daemon file writes and restart; preserve incomplete-install checks and any host probe that must run first. Route non-Claude CLI-only `src/clawrium/cli/clawctl/agent/sync.py` through that canonical path instead of returning early. Cover Claude's focused sync path, `--workspace-only`, `--no-restart`; `--diff` / `dry_run` perform no provisioning and cannot generate keys. A provisioning error fails the operation before restart/success.
5. Extend `src/clawrium/cli/clawctl/agent/describe.py` with a describe-only SSH section: `ssh_public_key` contains the complete controller public key, `ssh_private_key` is always `[REDACTED]` when present (otherwise a clear absent status); text/JSON/YAML agree. Do not modify the shared `agent_to_row()` used by the compact `agent get` listing; do not put private bytes in hosts.json, CLI output, events, logs, or runner artifacts. No key-view/export/rotate subcommand.
6. Add targeted tests to `tests/test_keys.py`, `tests/test_install.py` and install-skip tests, `tests/cli/clawctl/agent/test_sync.py`, `tests/cli/clawctl/agent/test_sync_workspace_flags.py`, `tests/cli/clawctl/agent/test_get_describe.py`, and playbook/resolver tests. Cover first install, legacy backfill, repeated sync, two agents on one host, local/remote missing/partial/conflicting state, interrupted generation/concurrency, host reset isolation, Linux/macOS paths/permissions, dry-run, and public-only output. Add the feature to root `CHANGELOG.md` under Unreleased during implementation; run `make test` and `make lint`.

### Decision table (controller ↔ agent user's `~/.ssh`)

| Controller pair | Remote pair | Action |
|---|---|---|
| Absent | Both files absent | Generate on controller; provision pair on host. |
| Valid pair | Both matching | Retain; repair safe ownership/mode drift without changing contents. |
| Valid pair | Both absent | Restore same pair to host. |
| Valid pair | One component present and matching | Install missing component only. |
| Absent/partial/corrupt | Any remote file exists, or local partial/corrupt | Fail closed; inspect and recover manually; do not silently adopt or rotate. |
| Valid pair | Remote file conflicts, is symlinked, or destination unsafe | Fail closed before writing either file. |

**Key risks and mitigations:** Host management SSH (`keys/<host-key-id>/xclm_ed25519`) is distinct from agent SSH (`agent-keys/<host-key-id>/<agent-name>/id_ed25519`). A remote preflight is necessary before new generation so a missing controller key cannot strand an existing remote identity. Two-phase reconciliation must recheck remote state before copy to avoid overwriting a concurrent change. Ansible event artifacts may outlive the playbook: never send private bytes in event payloads, debug output or extravars. Existing CLI-only, Claude, workspace-only, and normal sync exits must all pass the same check without provisioning on dry run. The on-host path is an agent-owned SSH identity, not an authorized key granting controller access.

**Execution order:** local identity/reconciliation contract → shared OS playbooks and resolver → install/sync wiring → describe output → tests and documentation. Detailed entry/exit criteria: [01_SCAFFOLD.md](01_SCAFFOLD.md). Workflow and proposed CLI output: [ARCHITECTURE.html](ARCHITECTURE.html).

## Planning

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-06T04:27:20Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan 1041 in a worktree. plan only. move plan file to worktree. no changes. i just need high level plan
```

**Output**: Created a dedicated issue worktree and moved the existing issue-creation prompt log into its high-level plan file, adding the implementation outline and planning prompt log.

## Planning Update

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-09T16:25:12Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan 1041 in a worktree. all plan files go there. create an html mock to show the workflow and changes
```

**Output**: Expanded the existing worktree plan with file-level design, safety decision table, phased scaffold, and an updated HTML workflow mock; no implementation code changed.
