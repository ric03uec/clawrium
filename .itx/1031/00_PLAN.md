# Issue #1031 — Codex agent with local OAuth

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx-issue-new
**Timestamp**: 2026-10-05T23:59:31Z
**Model**: openai/gpt-6-sol

```prompt
add a new issue for adding support for codex agent. this should be the same as adding support for claude code. and this should support adding codex oauth as a provider and linking it to the agent.
```

**Follow-up clarification**: Selected "Deploy Codex with OAuth" as the customer outcome and issue-title direction.

**Output**: Created https://github.com/ric03uec/clawrium/issues/1031 for a dedicated Codex CLI agent and agent-scoped local `codex-oauth` provider, linked to related OpenAI subscription-auth issue #733.

## Implementation Plan

### Outcome and scope

`clawctl` can create an isolated, daemonless `codex` agent, attach a locally authenticated `codex-oauth` provider, sync private authentication safely, and run finite native commands and conversational turns through CLI and GUI. This is a dedicated Codex CLI integration, distinct from the generic OpenAI API/ChatGPT-subscription provider work in #733. Match Claude Code's user-facing lifecycle and security guarantees, while following Codex's actual auth and session contracts rather than copying Claude's flags or token format.

### Upstream contracts to validate before implementation

- Pin one supported `@openai/codex` release and verify install prerequisites, target OS/architectures, native binary location, `CODEX_HOME`, command flags, JSONL result/event format, session resume/reset semantics, failure output and exit status on that exact pin. Document tested platforms; do not promise a platform before confirming support.
- Official Codex auth documentation describes ChatGPT login, `codex login status`, a file credential at `$CODEX_HOME/auth.json` **or** an OS keyring selected by `cli_auth_credentials_store`. It permits copying `auth.json` to a headless host; the CLI can refresh tokens and update the file. Verify the pinned schema and supported storage mode with redacted fixtures. Only the verified local file source is importable; keyring/ephemeral/absent credentials must produce an actionable non-secret error rather than be scraped or silently misinterpreted. References: https://developers.openai.com/codex/auth and https://developers.openai.com/codex/noninteractive.
- A local encrypted auth snapshot may be older than a remote `auth.json` refreshed by Codex. Establish this ownership rule: first activation and explicit re-attach/mode switch replace remote auth transactionally; ordinary configure/sync must preserve a valid already-installed remote OAuth document rather than replay a stale snapshot. If remote auth is missing, restore from the local snapshot only when it is still usable; otherwise fail with a re-login/re-attach instruction. Verify pin-specific expiration/refresh semantics before coding the freshness check. API-key mode, if supported, must remove inactive OAuth state with rollback on failure. Keep sync status metadata-only: do not read remote credential contents into events/diffs.

### Execution steps and ownership boundaries

1. **Codex agent foundation** — add `src/clawrium/platform/registry/codex/manifest.yaml` and OS-specific install/remove/exec playbooks as needed. Wire no-daemon lifecycle in `core/agent_lifecycle.py`, `core/install.py`, `core/registry.py`, `core/lifecycle.py`, `core/lifecycle_canonical.py`, `core/agent_exec.py`, `core/agent_shell.py`, and corresponding CLI routing. Match Claude's installed-record semantics, private dedicated account/home and bounded command transport. Never start a service, gateway or tunnel; make unsupported daemon operations clear. Verify cleanup preserves shared/system-owned resources and local state on remote failure.
2. **Local `codex-oauth` provider and credential selection** — register a selection-only, no-model-catalog provider in `core/providers/storage.py` and the provider CLI. Implement a dedicated local reader and per-instance secret handling (alongside `core/claude_credentials.py` patterns); attach only to Codex in `cli/clawctl/agent/provider.py`, with re-attach refresh, validation, no cross-instance leakage, and rollback if first import fails. Add `cli/clawctl/agent/secret.py` mode rules if API-key mode is supported. Do not extend the legacy Ethos device-auth branch or make the generic OpenAI provider accept subscription credentials.
3. **Credential activation and canonical sync** — add a bounded Codex config renderer in `core/render.py` and a single shared configure/sync path in `core/lifecycle.py` and `core/lifecycle_canonical.py`; update `cli/clawctl/agent/configure.py` and `sync.py`. Use dedicated Linux/macOS Ansible playbooks, agent-home absolute paths (`/home/{{ agent_name }}` / `/Users/{{ agent_name }}`), restricted ownership and `0600` auth-file mode. Avoid `ansible_user_dir`. Stage credentials privately, never in host/provider state, command argv, logs, diff or terminal output. Implement explicit remote refresh preservation and fail-closed atomic replacement/cleanup for mode changes. Ensure default sync never clobbers newly refreshed remote tokens.
4. **On-demand chat parity** — add `core/chat_codex.py` with finite, timeout-bounded native Codex invocation, prompt on stdin, JSONL parsing and safe error/redaction handling; wire `cli/chat.py` and `gui/routes/agents.py` to reuse it. Persist native session identifier per interactive CLI/GUI conversation when supported by the pin; `/reset` and GUI New chat start fresh; `--once` uses a new session. Ensure no shell interpolation, unbounded process, browser credential copy or second gateway path.
5. **Integration, docs and release** — add `docs/agent-support/codex.md`, command help and any agent support index, and `CHANGELOG.md` `### Added` entry. Explain supported controller source/platforms, first import vs remote token refresh behavior, re-attach, errors, security, no-daemon operations, and limitations. Run targeted meaningful tests plus `make test` and `make lint`; conduct redaction-safe real-host OAuth propagation and repeat-sync-after-refresh checks on supported host(s). Keep fixture tokens synthetic; never upload or log live credentials.

### Verification matrix

- Manifest discovery/validation and pinned install/removal on declared Linux/macOS targets; lifecycle rejects daemon-only operations and `--version` works without credentials; exec/shell respect argv, agent identity, timeout and redaction.
- Provider registration/listing/attachment restrictions, invalid/missing/keyring source, unsafe permissions/symlink/oversize/malformed file, first-attach rollback and re-attach, two-agent isolation, and secret-free error paths.
- Fresh OAuth activation, repeated sync after remote token refresh, missing/expired remote auth, explicit re-attach, partial-write/cleanup failure rollback, API-key switching (if implemented), settings ownership, filesystem modes, and zero credential exposure in sync diff/events/logs/host records.
- Native CLI and GUI chat finite invocation, success/failure/timeout, JSONL variants for pinned version, multi-turn resume/new chat, `--once` and safe SSE errors. End-to-end real-host check without printing tokens.

### Subtask order

1. #1034 — Agent foundation (independent of provider implementation).
2. #1035 — OAuth provider and local secret import (depends on agent identity and registry).
3. #1036 — Credential activation and freshness-safe sync (depends on both).
4. #1037 — CLI/GUI chat (depends on installed binary and activation).

Parent #1031 owns final integrated documentation, change log, end-to-end verification, and acceptance-criteria closure. These four issues are linked as GitHub sub-issues of #1031.

### Risks and decisions

- The Claude native credential format and `CLAUDE_CODE_OAUTH_TOKEN` are **not** interchangeable with Codex `auth.json`; validate the pinned Codex schema before transferring a redacted native document.
- Remote Codex refresh mutates credential state after installation; treating the controller's original snapshot as authoritative on every sync would revoke usable remote sessions. Preserve remote-refresh ownership until an explicit re-attach, and test it.
- Native `exec --json` emits multiple JSONL events rather than Claude's single JSON response. Derive completion and session IDs from verified events for the pinned version; do not expose raw stderr or tool event data unnecessarily.
- Codex may use keyring storage on the controller; the import feature supports only verified file-backed login and must explain how to select supported storage without collecting keyring contents.

## Planning

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-06T00:07:21Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan this in a worktree. move the plan file in the worktree as well
```

**Output**: Planned Codex agent and OAuth support in the `clawrium-issue-1031` worktree, retaining the issue-creation log in this plan file; created linked sub-issues #1034, #1035, #1036, and #1037.
