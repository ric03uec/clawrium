# Issue #1032 — Pi as a first-class fleet agent

## Customer outcome

An operator can install an isolated Pi agent on a fleet host, attach a supported provider, and use CLI/GUI chat and native exec with real authenticated responses. Pi is on demand: no gateway, service, port, or native web UI.

## Architecture and ownership

- **Control plane (Clawrium):** The operator attaches a provider and selects a model in Clawrium. Clawrium owns the provider record, credential source, model mapping and sync decision. It validates supported combinations and provisions the selected model and scoped access onto the target agent account over SSH/Ansible.
- **Fleet host (Pi):** An isolated OS user owns the pinned Pi installation, its rendered settings, scoped authentication material and sessions. Pi runs only when invoked. It uses the model access already provisioned for that agent to perform inference; it does not discover providers, request access grants or select credentials from other agents.
- **Boundary:** OpenRouter, AWS SSO/Bedrock and Codex OAuth are supported *ways for the control plane to provision access*, not separate fleet agents or provider registries on the host. Provider endpoints still handle inference. The exact per-provider credential handoff (including Pi-native OAuth) must be proven against the pinned Pi version; do not place shared credentials or secrets in `hosts.json`, logs or diffs. Project-level `.pi` files remain operator-owned.

## Customer-verifiable execution plan

Each milestone ends in an action an operator can perform and observe. Complete its acceptance check before starting the next milestone; engineering work is listed only to explain how to unlock that outcome.

### 1. I can install and inspect Pi on a host

**Operator check:** Create a Pi agent on a Linux host and a macOS host, list it in the fleet, and run `clawctl agent exec <name> -- --version`. The pinned Pi version runs under its dedicated account on each host; create does not prompt for provider login, start a service, reserve a port or offer a native dashboard.

**Execution steps:**
1. Confirm Pi's pinned package, platform requirements and native CLI/settings contract.
2. Add the Pi registry manifest and Linux/macOS install and exec playbooks; route them through Clawrium's daemonless lifecycle and fleet views.
3. Create per-agent OS user and owned paths; keep project-level `.pi` files outside Clawrium ownership. Show service controls as not applicable.

**Acceptance:** Real install + version output on both operating systems; existing agents on each host remain unchanged. This milestone needs no provider or model response.

### 2. I can ask my existing OpenRouter model a question from the CLI (#1038)

**Operator check:** Attach an existing OpenRouter provider in Clawrium, select a supported model, sync, then use `clawctl agent chat <name>` to ask a question and get a real answer from Pi on i-wolf. Run a second prompt in the same session and a native `agent exec` request. No manual Pi-side provider setup is required.

**Execution steps:**
1. Verify a real OpenRouter model ID against the pinned Pi version; define an explicit, bounded mapping and reject unsupported pairs.
2. Render the selected model and scoped OpenRouter credential from Clawrium onto only that agent's account at configure/sync; make mismatches and missing access actionable.
3. Implement finite SSH/Ansible-backed chat and native exec with bounded runtime, safe streaming, cancellation and session continuation/reset.

**Acceptance:** A live model response through CLI chat and native exec, plus a continued session using the provisioned agent-scoped credential. A configured provider entry or unit-test mock is not enough.

### 3. I can use the same Pi agent from the GUI

**Operator check:** Open the agent in Clawrium's fleet GUI, send a message, continue the conversation, clear the history and send a new message. The displayed provider/model matches the CLI selection; the “Open Agent UI” action is unavailable.

**Execution steps:**
1. Route GUI chat through the same on-demand Pi chat adapter and agent-scoped session semantics used by the CLI.
2. Expose fleet detail, provider/model and errors without leaking credentials or prompt-bearing transport artifacts; keep native web UI disabled in the manifest.

**Acceptance:** A real GUI reply, continuation and reset on the same provisioned OpenRouter model, with no Pi daemon or dashboard.

### 4. I can use my AWS SSO-backed Bedrock model (#1039)

**Operator check:** Select an AWS SSO-backed Bedrock provider/model in Clawrium, sync the Pi agent, then get real replies in CLI and GUI. Let the short-lived login expire and repeat after refresh or guided re-login; no credential copy from another agent is required.

**Execution steps:**
1. Validate the pinned Pi version's Bedrock model, region and AWS profile/credential-chain behavior on the target host.
2. Provision the scoped AWS access needed by that agent from the control-plane selection; surface expiry and re-login failures clearly.
3. Exercise native exec and both chat surfaces with a real model; verify secrets remain isolated.

**Acceptance:** Live Bedrock replies before and after a refresh/re-login path; expired access produces an actionable error rather than silent fallback.

### 5. I can use my Codex OAuth-backed model (#1040)

**Operator check:** Select Codex in Clawrium, complete the supported login/credential handoff for that Pi account, and get real replies in CLI and GUI; repeat after refresh or re-login. An OpenAI API-key response does not count.

**Execution steps:**
1. Prove the pinned Pi version's `openai-codex` OAuth login, storage and refresh behavior; define the narrowest control-plane-to-host handoff compatible with Pi-native OAuth.
2. Provision only the selected agent's credentials/model and make expired or missing OAuth actionable.
3. Verify real CLI chat, native exec and GUI chat, including refresh/re-login and isolation.

**Acceptance:** Live Codex OAuth replies through both chat surfaces with a verified refresh/re-login path.

### 6. I can change providers and remove Pi without disturbing my fleet

**Operator check:** Switch the same Pi agent between supported providers, detach one, and confirm it no longer uses the previous provider's access. Remove Pi and confirm other agents still run, Pi-owned remote files and local state are gone, and operator-owned project `.pi` files remain.

**Execution steps:**
1. Reconcile bounded config on sync, remove superseded agent-local credential material without revoking a shared provider credential, and verify provider/model selection on each switch.
2. Implement ownership-checked remote cleanup before local state/secret deletion; cover Linux and macOS and preserve unrelated users/files.
3. Add focused regression tests for every customer check, run `make test` and `make lint`, and update CLI help, canonical docs and their website mirrors where applicable, plus the unreleased changelog.

**Acceptance:** No stale credential use after switch/detach, no unrelated fleet changes after removal, and the documented workflow reproduces the live checks.

## Likely implementation areas

- `src/clawrium/platform/registry/pi/` and `src/clawrium/core/registry.py`, `install.py`, `lifecycle.py`, `lifecycle_canonical.py`, `render.py`, `agent_lifecycle.py` — manifest, installation, configuration, provider mapping, and removal.
- `src/clawrium/core/chat_pi.py`, `src/clawrium/cli/chat.py`, `src/clawrium/cli/clawctl/agent/`, `src/clawrium/gui/routes/agents.py` — on-demand chat, CLI/GUI integration, shell/exec, provider UX.
- `tests/`, `docs/`, `website/docs/`, `CHANGELOG.md` — regression coverage and operator guidance.

## Key risks and validation gates

- A registered provider or selected model alone does not establish Pi inference; require a real response from the pinned Pi binary on the agent host. Select an actually available OpenRouter model before locking the mapping. Pi must consume provisioned access rather than request new access on its own.
- Pi's AWS credential chain and Codex OAuth lifecycle differ from API-key auth; test expiry and switching without copying shared credential directories or substituting an API key for OAuth. Keep provider ownership in Clawrium even when the Pi-native OAuth login happens on the host.
- Pi's session and streaming protocol must be validated against the pinned version before reusing Claude-specific chat assumptions. Bound execution time and sanitize outputs; preserve operator-owned files and other fleet agents on removal.

## Existing subissues

- #1038 — existing OpenRouter provider/model and first live response (baseline).
- #1039 — AWS SSO/Bedrock live validation (after baseline).
- #1040 — Codex OAuth live validation (after baseline and AWS phase).

## Planning

**Stage**: plan
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-06T04:26:14Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan 1032 in a worktree. move all plan files there. just give me a high level plan. no changes
```

**Output**: High-level issue plan in the dedicated #1032 worktree; no implementation changes.

## Planning update

**Stage**: plan
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-06T05:07:32Z
**Model**: openai/gpt-6-sol

```prompt
architecture diagram should have provider in the control plane wchih are injected into the fleet host. n pi is NOT requesting model access, its just using the model it has been given access to. update this plan with the execution steps as well. the current phases are very enginering cenetric. i ned outcome driven phases that can be validated by customers at each stepo
```

**Output**: Revised control-plane/host architecture and customer-verifiable execution milestones in `00_PLAN.md` and `architecture.html`.
