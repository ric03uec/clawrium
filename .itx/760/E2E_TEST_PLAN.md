# Issue #760 — End-to-End Test Plan on `wolf-i`

**Goal**: Prove on a real host (`wolf-i`) that the workspace overlay
feature behaves correctly across all three agent types and — critically
— that the hermes **exclude list cannot be bypassed by an operator
adding or modifying excluded files in the workspace**.

PRs gated on this plan: [#773](https://github.com/ric03uec/clawrium/pull/773)
(openclaw) → [#774](https://github.com/ric03uec/clawrium/pull/774)
(zeroclaw) → [#775](https://github.com/ric03uec/clawrium/pull/775)
(hermes). **Do not merge until every required-pass row is green.**

The `e2e/760-ubuntu-wolf-i` branch sits on top of all three PR
branches — its HEAD is the merged effect of the chain. Run against
this branch so a single run covers all three phases.

## Pre-flight (must hold before any test runs)

- `clawctl agent get` lists `wolf-i` host as `ready`.
- No agents named `ws-openclaw`, `ws-zeroclaw`, or `ws-hermes` exist
  yet. (If they do — left over from a prior failed run — delete with
  `clawctl agent delete --yes <name>` before starting.)
- Local workspace dirs `~/.config/clawrium/agents/ws-{openclaw,zeroclaw,hermes}/`
  do not exist on the control machine. (Same — if leftover, remove.)
- Branch: `e2e/760-ubuntu-wolf-i`. `git rev-parse HEAD` matches
  `origin/issue-769-hermes-workspace-overlay`.
- `make lint && make test` clean on this branch (sanity check).

## Test matrix

Three phases. Each phase: provision → matrix → cleanup. Capture
verbatim command output (stdout + stderr) for every `clawctl`
invocation in the corresponding log file.

### Phase 1 — `ws-openclaw` (PR #773 verification)

Log file: `.itx/760/02_E2E_openclaw_wolf-i.md`.

Provider attachment: pick any provider with `CREDENTIALS=set` from
`clawctl provider registry get` that openclaw accepts. The existing
failed `wolf-i` agent on the host uses `clawrium-gtm-litellm`; that
attachment shape is known good.

1. **Provision**:
   - `clawctl agent create ws-openclaw --type openclaw --host wolf-i`
   - `clawctl provider registry attach <chosen-provider> --agent ws-openclaw`
     (use whatever subcommand current CLI exposes — `clawctl provider --help`)
   - `clawctl agent configure ws-openclaw`
   - `clawctl agent start ws-openclaw`
   - `clawctl agent doctor ws-openclaw` → must be healthy.

2. **Marker push (E1 matrix)**:
   - Create `~/.config/clawrium/agents/ws-openclaw/workspace/MARKER.md`
     with body `phase-1 e2e marker $(date -u +%FT%TZ)`.
   - `clawctl agent sync ws-openclaw`
   - On `wolf-i`: `ssh xclm@wolf.tailf7742d.ts.net 'sudo -u ws-openclaw cat /home/ws-openclaw/.openclaw/workspace/MARKER.md'`
   - **Required pass**:
     - File exists with exact bytes.
     - Owner is `ws-openclaw:ws-openclaw`.
     - Mode is `0644` (or whatever the playbook pins; assert it
       matches the playbook spec).
     - `clawctl agent doctor ws-openclaw` healthy after sync.

3. **`--workspace-only` smoke**:
   - Add `~/.config/clawrium/agents/ws-openclaw/workspace/NOTES.md`
     with `extra: verified by --workspace-only`.
   - `clawctl agent sync ws-openclaw --workspace-only -o json`
   - **Required pass**:
     - `NOTES.md` lands at
       `/home/ws-openclaw/.openclaw/workspace/NOTES.md`.
     - NDJSON stream emits one `workspace_file_pushed` event for
       `NOTES.md`.
     - Exit code is `0`. (No bearer rotation — openclaw is not in
       `_PAIRING_AGENT_TYPES`. Zero `gateway_token_rotated` events.)

4. **Cleanup**:
   - `clawctl agent delete --yes ws-openclaw`
   - `rm -rf ~/.config/clawrium/agents/ws-openclaw`
   - Re-confirm no `ws-openclaw` files on `wolf-i` under
     `/home/ws-openclaw/` (host cleanup is part of `agent delete`).

### Phase 2 — `ws-zeroclaw` (PR #774 verification)

Log file: `.itx/760/03_E2E_zeroclaw_wolf-i.md`.

Provider: existing `clawrium-d01` zeroclaw uses `clawrium-glm51`.

1. **Provision** (same shape as Phase 1).

2. **Bearer-rotation matrix (E2)**:

   - Capture `sha256(hosts.json.agents.ws-zeroclaw.gateway.auth)` BEFORE.
   - Drop `~/.config/clawrium/agents/ws-zeroclaw/workspace/profiles/coder/SOUL.md`
     with operator-override bytes.
   - `clawctl agent sync ws-zeroclaw -o json`
   - **Required pass**:
     - Operator-override `SOUL.md` lands at
       `/home/ws-zeroclaw/.zeroclaw/workspace/profiles/coder/SOUL.md`
       with operator bytes (NOT canonical-rendered bytes).
     - Pre-vs-post `sha256(hosts.json...auth)` **differs**. NEVER
       capture the raw bearer in the log — sha256 only.
     - Exactly **one** `gateway_token_rotated` NDJSON event.
     - `clawctl agent doctor ws-zeroclaw` healthy.

3. **`--workspace-only` also rotates bearer**:
   - Capture sha256 AGAIN.
   - `clawctl agent sync ws-zeroclaw --workspace-only -o json`
   - **Required pass**:
     - sha256 differs from the previous (workspace-only rotates too).
     - Exactly one `gateway_token_rotated` event.

4. **Negative pin**:
   - Re-provision `ws-openclaw` (same as Phase 1 quick path).
   - `clawctl agent sync ws-openclaw --workspace-only -o json`
   - **Required pass**: zero `gateway_token_rotated` events
     (openclaw doesn't rotate).
   - Cleanup `ws-openclaw` again.

5. **`--workspace-only --dry-run`**:
   - `clawctl agent sync ws-zeroclaw --workspace-only --dry-run -o json`
   - **Required pass**: zero `gateway_token_rotated` events
     (`--check` mode on pair playbook).

6. **Cleanup** (delete ws-zeroclaw, rm local workspace).

### Phase 3 — `ws-hermes` (PR #775 verification — THE CRITICAL ONE)

Log file: `.itx/760/04_E2E_hermes_wolf-i.md`.

This phase covers the user-emphasized invariant: **excluded files
must NOT reach the host, even when an operator deliberately tries to
add or modify them in the workspace**.

Provider: existing `clawrium-triage` hermes uses `clm-openrouter`.

1. **Provision** (same shape).

2. **Capture canonical baseline on host** (CRITICAL for the modify test):
   - For each canonical file on the host, capture sha256 + bytes:
     - `/home/ws-hermes/.hermes/config.yaml`
     - `/home/ws-hermes/.hermes/.env`
     - `/home/ws-hermes/.hermes/auth.json` (if present)
     - `/home/ws-hermes/.hermes/state.db` (if present — daemon-managed)
   - Persist these to a fixture dir on the control machine
     (`/tmp/e2e-hermes-baseline/`).

3. **Good-files test (positive)**:
   - Drop into `~/.config/clawrium/agents/ws-hermes/workspace/`:
     - `profiles/coder/SOUL.md` with `phase-3 e2e SOUL`
     - `memories/NOTES.md` with `phase-3 e2e NOTES`
   - `clawctl agent sync ws-hermes -o json`
   - **Required pass**:
     - Both files land at corresponding paths under
       `/home/ws-hermes/.hermes/`.
     - Two `workspace_file_pushed` events.
     - No `gateway_token_rotated` events (hermes does not rotate).

4. **Hostile ADD test** — operator drops files matching the exclude list:
   - Drop into the workspace dir:
     - `config.yaml` with bytes `MALICIOUS: overwrites canonical`
     - `.env` with bytes `MALICIOUS_KEY=stolen`
     - `auth.json` with bytes `{"malicious":true}`
     - `state.db` with bytes `MALICIOUS-DB`
     - `state.db-journal`, `state.db-wal`, `state.db-shm` with
       malicious bytes
     - `sessions/123.json` with malicious bytes
     - `logs/gateway.log` with malicious bytes
     - `skills/clawrium/tdd/SKILL.md` with malicious bytes
   - `clawctl agent sync ws-hermes -o json`
   - **Required pass**:
     - For EVERY hostile file, exactly one `workspace_file_excluded`
       NDJSON event with the matching `rel` path.
     - **Zero** `workspace_file_pushed` events for any of these
       hostile paths.
     - On `wolf-i`, sha256 of EVERY canonical file from step (2) is
       UNCHANGED. The exclude list held.
     - On `wolf-i`, daemon-managed files (state.db, sessions/, logs/)
       are unchanged.
     - No file named `skills/clawrium/tdd/SKILL.md` exists under
       `/home/ws-hermes/.hermes/skills/clawrium/` (this is the W10
       iter-3 invariant).

5. **Hostile MODIFY test** — the case the user explicitly called out:
   - Take the EXISTING `config.yaml` body from step (2) baseline.
     Modify just one line in the LOCAL workspace copy
     (`~/.config/clawrium/agents/ws-hermes/workspace/config.yaml`):
     append `# malicious-modify-test`.
   - `clawctl agent sync ws-hermes -o json`
   - **Required pass**:
     - `workspace_file_excluded` event emitted for `config.yaml`.
     - On `wolf-i`, sha256 of `/home/ws-hermes/.hermes/config.yaml`
       MATCHES the baseline captured in step (2). The modification
       MUST NOT propagate. **This is the failure mode the user
       wants explicitly verified.**

6. **Symlink bypass attempt** (hook-review S — security):
   - In the workspace dir, create a symlink:
     `ln -s ../auth.json workspace/innocent.md`
   - (Adjust path to actually point at a sensitive host file via
     traversal — verify what symlink the playbook resolution would
     see. Goal: prove that a symlink with an innocuous name cannot
     overwrite a sensitive target.)
   - `clawctl agent sync ws-hermes -o json`
   - **Required pass**:
     - Either symlink is rejected at enumeration (preferred — emits
       `workspace_file_excluded` or a `workspace_symlink_rejected`
       event) OR it's pushed as a regular file with the symlink-
       target bytes BUT NOT to the sensitive path.
     - `auth.json` on host unchanged from baseline.

7. **Cleanup** (delete ws-hermes, rm local workspace).

## Result reporting

After the matrix runs, the child agent MUST:

1. Write each phase log under `.itx/760/0[234]_E2E_<agent>_wolf-i.md`
   containing:
   - Timestamps for each command
   - Verbatim stdout/stderr captures
   - Pass/fail per "Required pass" bullet above
   - sha256 hashes (NEVER raw bearer/secret material)

2. Commit all three logs to the `e2e/760-ubuntu-wolf-i` branch in
   one commit.

3. Push the branch and open a PR `e2e/760-ubuntu-wolf-i → main`
   titled `test(e2e): #760 Phase 1-3 verification on wolf-i` with
   body summarizing the matrix outcome. **Do NOT** stack this PR;
   it's a sibling artifact.

4. Update PR bodies on #773, #774, #775 with a comment linking to the
   E2E PR + summary.

5. If ANY required-pass row fails:
   - Do NOT attempt to "fix" the underlying code in this worktree.
     Just document the failure.
   - Comment on the corresponding upstream PR (#773/#774/#775) with
     a `[E2E-BLOCKER]` marker and the verbatim failure evidence so
     the original child can re-iterate.
   - Open a tracking issue if the failure looks like it needs a
     separate fix.

## Non-goals (out of scope this run)

- macOS verification on `mac-test` — that's #770/#771/#772.
- Performance benchmarking.
- Auto-merge — the user explicitly gates merge on this plan.
