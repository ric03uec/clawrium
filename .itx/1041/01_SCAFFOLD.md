# Issue #1041 — Phased execution scaffold

**Source:** [00_PLAN.md](00_PLAN.md) · [Workflow mock](ARCHITECTURE.html) · [GitHub issue](https://github.com/ric03uec/clawrium/issues/1041)

## Phase 1 — Controller identity and reconciliation contract

**Entry:** Review the existing management key API in `core/keys.py`, stable host `key_id` in host records, and `core/reset.py:delete_host_keys` behavior.

**Work:** Add an agent-only local store outside `keys/`; validate host ID and agent name, forbid symlink/unsafe paths, generate Ed25519 pairs with locked/exclusive atomic creation, verify the private/public relationship, enforce 0700 directory and 0600 private permissions. Define safe states and non-secret error messages; inspect the remote destination before creating a new local pair. Keep rotation out of this ensure path.

**Exit:** Tests prove first generation, same-key repeat, two agents on the same host, corrupted/partial local pair fails, remote occupancy with no controller pair fails, and host reset cannot remove an agent identity.

## Phase 2 — System-level Ansible provisioning

**Entry:** Phase 1 identity semantics and remote state contract fixed.

**Work:** Add Linux/macOS siblings under `platform/playbooks/` and a `playbook_resolver.py` selector. Read-only preflight identifies remote files without emitting private bytes; write phase validates all existing parts before any copy, copies only missing matching components with `no_log: true` and safe file permissions. Use literal OS-specific agent homes and expected groups; never use management-key path or `ansible_user_dir`.

**Exit:** Linux/macOS tests cover missing/matching/partial/conflict/symlinked remote files, expected owner/group and modes, safe Ansible args/events/artifacts, and no partial overwrite when preflight rejects state.

## Phase 3 — Install and all real sync paths

**Entry:** Shared provisioning helper available and isolated from agent-specific templates.

**Work:** Run after the agent install playbook succeeds in `core/install.py` (including binary-skip) and before installed status. Run before early returns in `core/lifecycle_canonical.py`; make non-Claude CLI-only `cli/clawctl/agent/sync.py` invoke canonical sync. Include Claude, workspace-only and no-restart. Preserve incomplete-install/host validation gates and zero writes on dry-run/diff; propagate provisioning failures before restart or success.

**Exit:** Fresh install, legacy sync, repeated sync, CLI-only, Claude, workspace-only and no-restart tests all reach ensure exactly once; dry-run/diff never generate/provision; failures stop lifecycle completion.

## Phase 4 — Detail view and operator documentation

**Entry:** Controller key location and key status API stabilized.

**Work:** Add `ssh_public_key` and `ssh_private_key` (redacted or absent) to describe-only text/JSON/YAML rendering in `cli/clawctl/agent/describe.py`. Keep `agent get` list compact. Update root `CHANGELOG.md` under Unreleased and any operator documentation needed for safe recovery of collisions/partial state; describe future explicit agent-reset-only rotation without inventing a reset command.

**Exit:** Tests confirm all three formats expose only public material, private bytes never appear in serialized output/events, and no detail/list regression.

## Phase 5 — Verification and review

**Entry:** Phases 1–4 complete.

**Work:** Run `make test` and `make lint`; inspect changes against the issue's acceptance cases. If review is enabled in `.claude/itx-config.json`, follow the repo's ATX → CLI → manual review fallback before a future commit. Exercise Linux and macOS host provisioning where test hosts are available.

**Exit:** Required checks pass, failures are resolved or documented, and the issue's install/backfill/idempotency/isolation/reset/permissions/redaction cases are accounted for.

## Scaffold Prompt Log

**Stage**: scaffold
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-10-09T16:25:12Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan 1041 in a worktree. all plan files go there. create an html mock to show the workflow and changes
```

**Output**: Created worktree-local phased execution criteria linked to the expanded issue plan and HTML workflow mock.
