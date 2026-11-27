# Changelog

All notable changes to this project are documented here. Per-release frozen
archives live under [`docs/releases/`](docs/releases/) — that directory is
the single place to read the full history of what shipped in each version.

The project follows a `YY.M.PATCH` calendar versioning convention; the
`## [Unreleased]` section below is the working log for the next release
cut. The `itx-release` skill archives this section into a new
`docs/releases/<version>/CHANGELOG.md` and resets this file to an empty
`[Unreleased]` template on every release.

## [Unreleased]

### BREAKING

- Removed the per-agent chat / memory / exec / audit / secret CLI surfaces and the top-level `clawctl apply`, `clawctl diff`, `clawctl audit`, and `clawctl doctor` command groups. **Operator scripts invoking any of the commands below will now fail with "No such command".** Removed commands and their replacement workflows (#1071, phase 1):

  | Removed command | Replacement |
  |---|---|
  | `clawctl agent chat <name>` | SSH to the host and invoke the agent's native CLI directly. `clawctl agent shell <name> -- <cmd>` still wraps the SSH session for a one-shot command. |
  | `clawctl agent exec <name> -- <args...>` | `clawctl agent shell <name> -- <cmd>` (one-shot), or SSH directly for longer sessions. |
  | `clawctl agent memory ...` | No replacement. Operator memory lives on the agent host; manage it with the agent's native tooling. |
  | `clawctl agent audit <name>`, `clawctl audit {log,tail,stats,path,session}` | No replacement. The operator audit trail capability is removed from `clawctl`. Prior logs under `~/.config/clawrium/changelog/` are untouched and can be read manually. |
  | `clawctl agent secret {create,list,delete,import}` | Provider and integration credentials live on the provider / integration records: use `clawctl provider` and `clawctl integration`. There is no agent-scoped secret CLI. |
  | `clawctl apply -f <file>`, `clawctl diff -f <file>` | No replacement for declarative fleet apply / diff. `clawctl delete -f <file>` stays for declarative teardown; the imperative path is the individual lifecycle verbs (`clawctl agent {create,configure,sync,start,stop,restart,delete}`). |
  | `clawctl doctor nemoclaw` | Removed — NemoClaw is reclassified as infrastructure, not an agent runtime. No replacement. |

  Alongside the public verbs, the legacy hybrid modules at `src/clawrium/cli/{chat,memory,secret}.py` and the TUI chat panel at `src/clawrium/cli/tui/widgets/chat_panel.py` are deleted. The TUI agent-detail screen now shows a static "chat moved to the host" hint in place of the removed panel. Chat / memory / exec / audit / secret state left on the local disk from prior versions is ignored by the upgraded `clawctl`; operators can remove `~/.config/clawrium/changelog/` and any per-agent `secrets/` / `memory/` trees manually.
- **`clawctl agent open` and `clawctl agent port-forward` now refuse Claude Code, Codex, and Pi agents.** The three daemonless install-only runtimes have no local service to forward and no dashboard to open; both verbs exit code 2 with `"<type> is a daemonless install-only agent and has no web UI — SSH to the agent host and invoke the native CLI directly"`. OpenClaw / Hermes / ZeroClaw are unchanged. No operator action required for the three-agent case; scripts that scripted `agent open <claude|codex|pi>` must switch to `clawctl agent shell <name>` or SSH (#1071, phase 2).
- **Removed the operator workspace-overlay sync pipeline end-to-end.** Files dropped under `~/.config/clawrium/agents/<type>/<name>/workspace/` are no longer mirrored to the agent host on `clawctl agent sync` or `clawctl agent configure`. The CLI flags `--workspace-only` and `--workspace` both exit 2 with `"workspace-overlay sync path was removed"`. Removed surface: `src/clawrium/core/workspace_sync.py`, every per-agent `playbooks/workspace.yaml` + `workspace_macos.yaml`, the hermes + zeroclaw `playbooks/filter_plugins/clawrium_filters.py` Jinja filter module, and the `features.workspace_overlay` block in the hermes / openclaw / zeroclaw manifests. `sync_agent_canonical`'s `workspace_only` and `push_workspace` parameters are gone. The zeroclaw gateway-bearer rotation invariant (issue #437) is unchanged — `_zeroclaw_repair_after_start` still fires on every sync / configure / restart. Operators who relied on the overlay must manage per-agent files directly on the host; local `~/.config/clawrium/agents/<type>/<name>/workspace/` directories are ignored by the upgraded `clawctl` and can be removed manually (#1071, phase 3b).
- **Removed every per-agent chat / memory / exec core module and GUI backend route.** `src/clawrium/core/chat_claude.py`, `chat_codex.py`, `chat_hermes.py`, `chat_pi.py`, `chat_zeroclaw.py`, `chat_ethos.py`, `memory.py`, and `agent_exec.py` are all gone. `core/chat.py` is trimmed to just the OpenClaw gateway WebSocket client that `core/validation.py` uses for openclaw sync-time reachability probes. `src/clawrium/gui/routes/agents.py` is reduced from 1168 lines to the `/logs` journalctl endpoint plus the openclaw gateway-token resolver. The agent-detail Tabs in the SPA now reduce to Overview / Configuration / Logs; Chat / Exec / Memory tabs are absent (#1071, phases 3a + 6).
- **Dropped the `get_secret` / `set_secret` / `remove_secret` / `list_secrets` global-namespace helpers in `core/secrets.py`.** These backed the pre-instance-key `clawctl agent secret` CLI and the legacy `cli/secret.py` hybrid module — both already removed in phase 1. The `*_instance_secret*` primitives that back provider / integration / openclaw-bearer credentials are unchanged. The dead `__global__` key in `secrets.json` from pre-#1071 installs is ignored by the upgraded `clawctl` (#1071, phase 3c).
- **Renamed `src/clawrium/core/nemoclaw.py` → `src/clawrium/core/openclaw_sandbox.py`.** The module is openclaw's NemoClaw sandbox integration — provider mapping, sandbox name validation, CLI builder, pin constant (`NEMOCLAW_VERSION`). Removed the doctor-probe-only helpers (`UPSTREAM_REPO`, `UPSTREAM_DOCS`, `INSTALL_SH_SHA256`, `install_sh_url()`) that have no remaining caller after `clawctl doctor nemoclaw` was dropped in phase 1. Openclaw's `install_nemoclaw.yaml`, `nemoclaw_onboard.yaml`, `nemoclaw_status.yaml`, the `runtime.nemoclaw` block in the openclaw manifest, and `_openclaw_nemoclaw_onboard` in `lifecycle_canonical.py` are all unchanged — every openclaw agent still installs and onboards the NemoClaw sandbox at sync time as before. Operator action: zero — external users should not have been importing from `clawrium.core.nemoclaw`; internal callers (`core/install.py`, `core/lifecycle.py`) are rewired (#1071, phase 4).
- **Removed every per-agent `exec*.yaml`, `memory_*.yaml`, and `workspace*.yaml` playbook** — the host-side half of the three subsystems that phases 1 / 3a / 3b closed on the control plane. 36 playbook files + 2 `filter_plugins/` directories are gone across the claude, codex, ethos, hermes, openclaw, pi, and zeroclaw registries. The `WorkspaceOverlayConfig` TypedDict + `_validate_workspace_overlay` validator in `core/registry.py` are gone; a manifest that declares `features.workspace_overlay` will be parsed with the key silently ignored (#1071, phase 5).
- Removed the Clawrium skills subsystem — `clawctl skill`, `clawctl agent skill`, the GUI **Skills** tab, every `src/clawrium/core/skills*.py` module, every per-claw `skills_apply.yaml` playbook, the `skills/` catalog, the `docs/skills/` documentation tree, and the related tests. Skills management moves fully onto the agent host, operated outside Clawrium. No migration runs — any skills state left under `~/.config/clawrium/agents/<name>/skills*` and any `skills` directory on the agent host (e.g. `~/.hermes/skills/clawrium/`) is ignored by the upgraded `clawctl` and can be manually removed at the operator's discretion. The legacy `agents.<name>.skills` key in `hosts.json` is likewise dead data and is dropped from the agent record on the next `clawctl agent install` / upgrade; operators who still need the attachment list can read it from a pre-upgrade backup of `hosts.json`. Operators who relied on managed skills reapply them directly on the host (#1072).
- Config-directory initialization now refuses symlinked path components, config directories owned by another user, and group/world-writable config leaves or non-sticky ancestors to prevent path-redirection attacks. `sudo XDG_CONFIG_HOME=/home/user/.config clawctl` now fails: run as the intended non-root operator, or set `XDG_CONFIG_HOME` to a root-owned private real path; no automated migration is available (#1046).

### Added

- Add and activate the copied-once GUI design system, including canonical blue tokens, tracking contracts, grid backdrop, and accessible global shell chrome (#1075).

- Provision a distinct controller-owned SSH keypair for every agent during
  installation and sync, and expose its public key in agent details.

- Added the install-only `pi` fleet agent. Pi installs in its own account and runs native commands on demand without a service, port, or dashboard (#1032).
- Added scoped OpenRouter provisioning and finite CLI/GUI chat for Pi agents, including continued and reset conversations without a Pi service or dashboard (#1038).
- Added agent-scoped native OpenAI Codex OAuth selection and interactive login for Pi, with private on-host refresh and CLI/GUI chat support (#1040).
- Added AWS Identity Center SSO profile provisioning for Pi Bedrock selections. Pi uses only its dedicated account's profile and region; it never receives controller AWS caches or static Bedrock keys (#1039).
- Add the daemonless, dedicated-account Codex CLI agent with pinned native command execution on supported Ubuntu and macOS hosts (#1034).
- Add selection-only `codex-oauth` providers that safely import a local file-backed Codex ChatGPT login into the chosen Codex agent's encrypted secrets (#1035).
- Activate Codex OAuth credentials privately on configure and sync while preserving tokens refreshed on the remote agent; re-attaching explicitly replaces remote credentials (#1036).
- Add finite, daemonless Codex chat through `clawctl agent chat` and the GUI Chat tab, with native JSONL thread continuation and safe error handling (#1037).

### Changed

- Standardize the GUI on the copied design system: shared accessible tables for agent, host, provider, model, and integration inventories; migrated headers, controls, tabs, metrics, and status surfaces; larger fleet-wide typography; and a responsive, browser-verified app shell whose reusable sidebar matches the approved navigation hierarchy exactly and whose header exposes Documentation and feature-request actions. MCP servers retains a dedicated follow-up placeholder (#1075).

### Fixed

- Complete the GUI design-system accessibility contracts with stable table identities, real row actions, keyboard tabs, AA text colors, a skip link, a reachable mobile sidebar toggle, official branding for every supported agent type, and the restored app-footer version. The Agents surface now removes the empty status column and restores List/Graph tabs using the shared topology view (#1075).

- Preserve the exact Codex OAuth credential bytes during activation so the stored fingerprint matches the installed document.

- Allow an explicitly confirmed local-only hard delete when remote agent cleanup fails, while warning that remote service and data need manual cleanup (#1052).
- Accept Codex CLI 0.160.1 ChatGPT OAuth files that include `OPENAI_API_KEY: null` while rejecting API-key credentials, and allow on-demand Codex chat from its isolated non-Git home (#1031).
- Reject incomplete or failed native Codex JSONL turns instead of presenting truncated output as a successful chat response (#1037).
- Bound Codex and Pi browser chat sessions to the current agent installation and host, return explicit HTTP errors for failed turns, and refuse new Pi sessions when every cache slot is active (#1037).
- Fixed Pi Codex OAuth provider switches to revoke dedicated-account OAuth state, require marker-bound managed-account login, and start Pi with a clean environment (#1040).
- Fixed Pi Bedrock provider replacement during `clawctl agent configure --stage providers` so the prior dedicated-account SSO and CLI caches are cleared before a different Identity Center profile activates, while failed cleanup retains the prior provider and same-identity updates retain warm caches (#1039).
- Fixed a process-wide umask race during config-directory initialization that could cause intermittent Ubuntu 3.12 permission failures (#1046).

### Documentation

- Document the Codex real-host lifecycle and authenticated Linux CLI/GUI UAT, including the remaining macOS and live token-refresh limitations (#1031).
- Document Pi Bedrock detach and provider-switch cache-cleanup boundaries, including the separate upstream AWS session-revocation step (#1039).
- Document fail-closed recovery steps for an interrupted Codex OAuth activation without exposing native auth credentials (#1036).

### Internal
