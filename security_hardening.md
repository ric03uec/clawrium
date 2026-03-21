# Security Hardening Research (Airgapped + Defense-in-Depth)

This document captures security hardening research for Clawrium, based on the current `SPEC.md` and `IMPLEMENTATION_PLAN.md`, plus reference architecture lessons from NVIDIA NemoClaw/OpenShell.

Status: research only. No implementation changes are included here.

## Goals

- Make Clawrium viable for airgapped or tightly controlled environments.
- Improve blast-radius control for each claw instance.
- Move from host-level trust to policy-governed runtime trust.
- Keep the existing fleet-management UX while adding security controls.

## Threat Model Focus (Current)

This research tracks the current project priority for security hardening:

- Primary concern: agent-specific abuse patterns, especially data exfiltration.
- Secondary concern: lateral movement and control-plane pivoting from compromised agents.
- Lower concern (for now): supply-chain integrity of package sources (`deb`, `npm`) because they are treated as trusted in the current risk posture.

Implication:

- Runtime controls (policy, isolation, observability, secret handling) should be prioritized over artifact provenance controls.

## Current Clawrium Baseline (from spec/plan)

Strengths today:

- Centralized deployment and lifecycle with Ansible.
- Config-as-code pattern and repeatable workflows.
- Basic secret hygiene (do not commit, inject at deploy time).
- Local-network-first deployment model.

Main gaps for high-security/airgapped posture:

- No strict per-instance sandbox boundary by default.
- No deny-by-default egress policy enforcement.
- Upgrade path assumes online source fetches (`cargo install --git ...`).
- No first-class signed/offline artifact bundle workflow.
- No runtime mediation layer for inference, outbound calls, or approvals.

## What NemoClaw/OpenShell Introduces (Principles)

The key new idea is to treat the assistant runtime as untrusted-by-default and govern it through policy.

### 1) Defense in Depth by Policy Domain

- Filesystem controls (scoped read/write).
- Network controls (allowlist egress).
- Process controls (syscall/capability restrictions).
- Inference controls (routed through a trusted mediator).

### 2) Gateway-Mediated Egress

- Outbound network traffic is intercepted and checked against policy.
- Enforcement can include host/port and method/path constraints.
- Unauthorized calls are blocked and surfaced for operator action.

### 3) Runtime Policy + Controlled Mutability

- Static controls locked at sandbox creation (filesystem/process).
- Dynamic controls hot-reloadable at runtime (network/inference).

### 4) Versioned, Verifiable Artifacts

- Resolve artifact version.
- Verify digest/signature.
- Plan/apply lifecycle.
- Track state and status.

## Clawrium vs NemoClaw (Security Lens)

| Aspect | NemoClaw/OpenShell | Clawrium (current) | Recommendation |
|---|---|---|---|
| Trust model | Runtime is policy-governed/untrusted | Host/process mostly trusted | Introduce per-instance sandbox policy |
| Egress control | Deny-by-default + allowlist | Local-network guidance only | Enforced network policy per claw |
| Inference path | Routed via gateway | Direct provider call from claw | Optional local gateway/proxy route |
| Artifact integrity | Digest-verified lifecycle | Standard package install flow | Signed/offline bundle verification |
| Runtime updates | Policy hot reload supported | Re-deploy to change behavior | Add `clm policy` workflows |
| Operator approvals | Block-and-approve flow | Not built-in | Add monitor/approval mode (optional) |

## Findings: Why Artifact Safekeeping Is Not the First Lever

Given the current threat model, protecting artifacts from trusted package sources is not the highest-value control.

- If the attacker path is prompt-injection or agent compromise at runtime, exfiltration occurs after process start, regardless of where binaries were downloaded.
- Artifact integrity controls improve reproducibility and rollback safety, but they do not directly stop an agent from reading sensitive data and sending it through allowed channels.
- The strongest risk reduction comes from constraining runtime behavior: what can be read, what can be sent, where it can be sent, and what gets audited.

Conclusion:

- Keep artifact hygiene as a platform reliability measure.
- Prioritize runtime exfiltration defenses as the primary security program for Clawrium.

## Agent-Specific Attack Vectors (Prioritized)

These vectors are specific to autonomous agent workflows and are the main targets for hardening.

| Vector | Typical Path | Impact | Priority |
|---|---|---|---|
| Allowed-channel exfiltration | Agent sends secrets to an endpoint that is technically allowed (GitHub API, model API, telemetry API) | Direct data leakage | Critical |
| Prompt-injection exfiltration | Untrusted input instructs agent to read files/secrets and transmit them | Credential/data leakage | Critical |
| Tool-chaining exfiltration | Multi-step chain (`read` -> transform -> network tool) bypasses simple single-call checks | Stealthy leakage | Critical |
| Secret scraping at runtime | Agent reads env vars, `.secrets`, config files, shell history | Credential compromise | High |
| Exfil via logs/artifacts | Sensitive values appear in logs, runner artifacts, debug output | Passive leakage | High |
| Cross-instance lateral movement | One claw accesses another claw's workspace/db creds on same host | Multi-instance compromise | High |
| Control-plane pivot | Compromised claw targets SSH/runner/control credentials | Fleet compromise | High |
| Covert network channels | DNS tunneling, chunked slow upload over allowed TLS, unusual protocols | Hard-to-detect leakage | Medium-High |
| Persistence poisoning | Malicious instructions stored in memory/prompts/config for future exfil | Recurring compromise | Medium-High |

## Recommended Countermeasures (Documentation-Only)

The controls below describe what to implement later. They are intentionally architecture-level, not implementation tasks.

### 1) Allowed-Channel Exfiltration

- Enforce endpoint + method + path-level allowlists, not host-only allowlists.
- Add payload guardrails for outbound traffic (secret pattern detection, high-entropy checks, size/rate thresholds).
- Separate inference egress policy from general internet egress policy.

### 2) Prompt-Injection and Tool-Chaining

- Treat all external content as untrusted instructions.
- Add policy checks across action sequences, not just single tool calls.
- Require explicit approval policy for dangerous combinations (sensitive read followed by outbound network action).

### 3) Runtime Secret Exposure

- Prefer short-lived secret files in tmpfs over long-lived environment variables.
- Scope secret visibility per instance and per process.
- Ensure strict permissions and automatic cleanup on restart/stop.

### 4) Logging and Artifact Leakage

- Redact secrets before persistence in logs and ansible-runner artifacts.
- Reduce retention for sensitive operational artifacts.
- Ensure debug modes cannot print secret values.

### 5) Lateral Movement and Control Plane Isolation

- Maintain strict per-instance identity and filesystem separation.
- Isolate per-instance database credentials and access boundaries.
- Keep control-plane credentials off target hosts where possible.

### 6) Covert Channels and Persistence Abuse

- Restrict DNS and outbound protocol surface to approved paths only.
- Detect unusual egress behavior (frequency, volume, destination drift).
- Separate trusted and untrusted memory/persistence domains.

## Detection and Audit Signals to Capture

To support incident response, log and monitor at least the following:

- Blocked vs allowed egress decisions (endpoint, method, path, binary/process).
- Sensitive file read attempts.
- Policy exceptions or runtime approvals.
- Secret access events (which process, when, scope).
- Sudden changes in outbound volume/destination patterns.
- Cross-instance access denials and privilege escalation attempts.

## Recommended Security Hardening Plan for Clawrium

## Phase 1: Airgapped Deployment Mode (Runtime-First)

Objective: remove internet dependency during deployment/upgrade.

Priority note: this phase should emphasize runtime isolation and egress control before deeper artifact provenance work.

Proposed additions:

- Add airgap profile flags and policy defaults (deny-by-default egress).
- Support local/offline package sources and mirrors for deployment.
- Keep bundle/checksum support as reliability control, not the primary exfiltration control.

Example manifest extension:

```yaml
airgap:
  bundle_version: "0.5.2"
  bundle_sha256: "<sha256>"
  includes:
    - zeroclaw-linux-amd64
    - python-wheels/
    - deb-packages/
    - sbom.json
```

CLI ideas:

```bash
clm bundle create zeroclaw --version 0.5.2 --output /mnt/usb
clm deploy wolf --from-bundle /mnt/usb/zeroclaw-0.5.2.bundle
clm upgrade wolf.espresso --from-bundle /mnt/usb/zeroclaw-0.5.3.bundle
```

## Phase 2: Per-Instance Network Policy (Deny-by-Default)

Objective: enforce explicit egress rules per claw.

Proposed policy file per instance:

`hosts/<host>/instances/<instance>/policy.yml`

Example:

```yaml
version: "1"
network:
  default: deny
  rules:
    - name: local-inference
      endpoints: ["192.168.1.17:11434"]
      methods: ["POST"]
    - name: local-db
      endpoints: ["127.0.0.1:5432"]
      methods: ["ANY"]
```

Enforcement options:

- Minimal: host firewall + systemd-level outbound restrictions.
- Better: sidecar proxy for L7 allowlist checks.
- Best: dedicated gateway mediation path for all outbound/inference.

## Phase 3: Sandbox Runtime for Claws

Objective: isolate claw process from host and other claws.

Approach:

- Run each instance in Podman/Docker rootless container where possible.
- Read-only root filesystem by default.
- Minimal writable mounts (`/workspace`, `/tmp`, instance data).
- Drop Linux capabilities + `no-new-privileges` + seccomp profile.
- Optional Landlock/AppArmor/SELinux policy overlays.

## Phase 4: Inference Routing Controls

Objective: control where model calls can go and how credentials are used.

For airgapped mode:

- Local-only inference providers (Ollama/vLLM/internal gateway).
- No cloud endpoints in policy and config.

For connected mode:

- Optional proxy route for inference.
- Central credential injection at boundary, not direct from agent process.

## Phase 5: Secret Isolation Hardening

Objective: reduce secret exposure window and locations.

- Continue avoiding committed secrets.
- Move from env-var-heavy exposure to short-lived file injection on tmpfs.
- Strict permissions (`0400` files, `0700` dirs).
- Avoid logging/rendering secret values in CLI/events.
- Add secret-scanning checks in CI and pre-commit.

## Phase 6: Auditability and Operator Controls

Objective: make blocked/allowed behavior inspectable and controllable.

- Add policy decision logs (allow/deny, endpoint, binary, reason).
- Add `clm monitor` for live policy events.
- Optional approval workflow for unknown egress attempts.
- Export security report per deployment.

## Proposed New Security Principles for Clawrium

1. Deny by default, allow explicitly.
2. Treat each claw as untrusted execution.
3. Separate fleet orchestration trust from runtime execution trust.
4. Prefer local/offline artifacts with cryptographic verification.
5. Keep static hardening immutable at runtime; allow narrow dynamic policy updates.
6. Make every sensitive action auditable.

## Practical Roadmap Mapping (to existing implementation plan)

- Phase 5 (Secrets): extend with tmpfs injection and stricter handling.
- Phase 6 (Registry): add bundle metadata, signatures/checksums, SBOM references.
- Phase 7 (Roles): add policy provisioning, sandbox runtime integration.
- Phase 8 (Runner): add policy apply/reload hooks and security event collection.
- Phase 9 (Deploy): add `--airgap` and `--from-bundle` behavior, fail on external deps.

## Suggested New Commands (Future)

- `clm bundle create <claw-type> --version <v>`
- `clm bundle verify <bundle>`
- `clm deploy <host> --from-bundle <path> --airgap`
- `clm policy validate <host>.<claw>`
- `clm policy apply <host>.<claw>`
- `clm policy reload <host>.<claw>`
- `clm monitor [--host <host>] [--claw <claw>]`

## Risks and Trade-offs

- Added complexity in exchange for stronger containment.
- Performance overhead from proxy/sandbox layers.
- More operational artifacts (policies, bundles, signatures) to manage.
- Potentially steeper user learning curve (mitigated via defaults and CLI UX).

## Minimum Viable Hardening (Fastest Path)

If implementing incrementally, start here:

1. Offline bundles + checksum verification.
2. Deny-by-default egress at host level per instance.
3. Rootless containerized claws with read-only rootfs.
4. Local-only inference for airgapped profile.

This subset gives most of the security value quickly without building a full gateway stack first.

## Reference Inputs

- Clawrium spec: `SPEC.md`
- Clawrium implementation plan: `IMPLEMENTATION_PLAN.md`
- NemoClaw repository and docs:
  - `https://github.com/NVIDIA/NemoClaw`
  - `https://docs.nvidia.com/nemoclaw/latest/reference/architecture.html`
  - `https://docs.nvidia.com/nemoclaw/latest/reference/network-policies.html`
- OpenShell repository:
  - `https://github.com/NVIDIA/OpenShell`
