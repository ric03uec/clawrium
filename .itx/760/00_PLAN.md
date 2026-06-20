# Issue #760 — Sync agent workspace from control plane to data plane

Add a per-agent `workspace/` slot under the local control-plane config
directory and mirror it onto the agent host on every `clawctl agent sync`.
The destination is the upstream-canonical operator-overlay zone for each
agent type, taken straight from upstream docs.

This iteration ships Ubuntu (Linux x86_64) only. macOS support is split
into three follow-up subtasks tracked separately.

---

## ATX Review Summary

| Review | Rating | Blocking | Status | Agents |
|---|---|---|---|---|
| 1 | 2/5 | B1–B5 | All addressed in iter 1 below | lifecycle-core, test-coverage, cli-ux, platform-playbooks, security, render-engine |
| 2 | 3/5 | B1 (iter-2) | All addressed in iter 2 below | lifecycle-core, test-coverage, cli-ux, platform-playbooks, security, render-engine |

### Iter 2 — Blocking resolution

| # | Status | Issue → Resolution |
|---|---|---|
| **B1 (iter-2)** | Fixed | `--no-restart` mode had no bearer-rotation pin or test. **Resolution**: §1.4 explicitly pins phase 6 (bearer repair) as **unconditional for zeroclaw across all three sync modes** (default, `--workspace-only`, `--no-restart`). Added `I-pair-C` (no-restart zeroclaw rotation) capturing pre/post `hosts.json.gateway.auth` and exactly one `gateway_token_rotated` event. AGENTS.md #437 invariant restored across the full flag matrix. |

### Iter 2 — Warning resolutions

| # | Status | Resolution |
|---|---|---|
| W1 (iter-2) | Fixed | Phase-6 stale-bearer window on verify failure pinned. The plan does NOT move repair before verify (calling `/pair/code` against a daemon whose systemd state is `activating` is racier than the stale-bearer trade-off). Instead §1.4 + §5 document explicitly: if restart succeeds but verify fails, repair is skipped; `hosts.json.gateway.auth` may hold the pre-restart bearer; operator must re-run sync after fixing the unit. Pinned in I8-verify-fail. |
| W2 (iter-2) | Fixed | §1.4 splits phase 6 into 6a (repair) and 6b (write state=READY). 6b runs only if 6a succeeds. I-pair-state covers the repair-failure-mid-phase-6 case. |
| W3 (iter-2) | Fixed | §1.4: `--workspace-only` step-2 (repair) runs only if step-1 (workspace.yaml playbook) returned rc==0. Workspace-push failure short-circuits the entire mode. Pinned in I8-wsonly-fail. |
| W4 (iter-2) | Fixed | I-pair-D added: parametrized over `{openclaw, hermes}` — asserts `--workspace-only` does NOT emit `gateway_token_rotated` and does NOT invoke the zeroclaw pair playbook for non-zeroclaw types. |
| W5 (iter-2) | Partially fixed | Reviewer was partially wrong: `clawctl agent shell` is shipping under #761 (plan already merged to main) and will be available by the time #760 is executed and E2E-d. Kept `clawctl agent shell` for host-side file verification. The other two flagged items are real and fixed: `clawctl agent create` does install + initial configure in one step (no separate `agent install`); `clawctl agent delete --yes` (not `remove`). Doctor remains `clawctl agent doctor`. |
| W6 (iter-2) | Fixed | `--workspace` is now a **hard error** that prints both candidates (`--workspace-only` for push-only, `--no-restart` for canonical+overlay-no-restart) and exits 2 immediately. No silent semantic divergence behind a yellow deprecation. The error message text is pinned in U-deprecated-error. |
| W7 (iter-2) | Fixed | Removed in favor of W6's hard-error path. The deprecated-flag exit goes through `cli/output/errors.py:emit_error`, which produces a structured error in JSON/YAML modes and a stderr banner in text mode. U-deprecated-error pins JSON-mode output produces zero stdout bytes. |
| W8 (iter-2) | Fixed | Mutex rejection (`--workspace-only --diff`) routed through `cli/output/errors.py:emit_error` with a structured payload `{error: "mutex", flags: ["--workspace-only", "--diff"]}`. I7-json pins JSON mode returns a single parseable error object. |
| W9 (iter-2) | Fixed | Bidi sanitization expanded to **every operator-controlled string** in NDJSON event payloads (`path`, `remote_path`, `reason`, `owner`, `agent_name`, ansible-runner stderr excerpts). U25 broadened with parametrized fields. |
| W10 (iter-2) | Fixed | §2 explicit: update the Typer `help=` short string in `cli/clawctl/agent/__init__.py:agent_app.command("sync")` registration AND the long-description docstring in `sync.py` to mention workspace overlay. U-help-text extended to assert both. |
| W11 (iter-2) | Fixed | `ansible_user_dir` resolves to the SSH-connecting user (`xclm`), not the agent user. **Resolution**: the workspace playbook uses `become: true` + `become_user: "{{ agent_name }}"` and then references `ansible_user_dir` *inside* that become context. Same pattern as the existing `skills_apply.yaml` and `memory_write.yaml` playbooks. Verified against `hermes/playbooks/skills_apply.yaml:27` which uses `"/home/{{ agent_name }}/.hermes/skills/clawrium"` — we use the same `/home/{{ agent_name }}/...` pattern explicitly rather than `ansible_user_dir` after become. U22 rewritten accordingly. |
| W12 (iter-2) | Fixed | `workspace.yaml` adds an `ansible.builtin.assert` task before each copy loop: `that: ["'..' not in item.rel", "not item.rel.startswith('/')"]`. Defense-in-depth against any future Python-side enumeration bypass. U-playbook-relpath-assert YAML structural test. |
| W13 (iter-2) | Fixed | Hermes excludes extended to include SQLite companion files: `state.db`, `state.db-journal`, `state.db-wal`, `state.db-shm`. Pinned in U3 with the exact set. |
| W14 (iter-2) | Fixed | §5 risk note added: workspace overlay races with daemon writes for `memories/` and `cron/` on hermes. Recommended operator workflow (`clawctl agent stop` → sync → `clawctl agent start`) documented in `docs/operations/sync.md`. No code-level mutex — this is a doc/UX risk acknowledgment, not a safety mechanism. |
| W15 (iter-2) | Fixed | U-manifest-parse added: parametrized over `{block missing, excludes null, excludes empty list, excludes with trailing-slash entry, malformed entry}`. Tests the `WorkspaceOverlaySpec` dataclass parser, not the resolved values. |
| W16 (iter-2) | Fixed | Staging dir managed via Python `tempfile.TemporaryDirectory` context manager. U29 (cleanup on success), U30 (cleanup on exception mid-ansible-runner). The "leak a sync's worth of files per failed run" disk-leak class is eliminated. |
| W17 (iter-2) | Fixed | U5 rewritten: invokes `render_hermes(stub_inputs)` and walks the actual `RenderedFiles.files` keys; asserts each key under the workspace destination root is in the hermes exclude list. No fixture. Catches the drift class the test is designed to prevent. Mirror tests for render_openclaw / render_zeroclaw (which currently have empty workspace excludes — the test asserts their renderers emit no paths under their respective workspace roots). |
| W18 (iter-2) | Fixed | §5 risk #5 rewritten to match implementation: "Symlinks rejected at Python enumeration (`os.path.islink` filter); `ansible.builtin.copy follow: no` is the second line of defense. There is no `O_NOFOLLOW`/`fstat` re-check — TOCTOU between Python enumerate and Ansible copy is bounded by the staging-dir lifetime (Python re-copies into `tempfile.TemporaryDirectory`, so the file Ansible sees is the staged copy, not the operator's path)." This is actually stronger than O_NOFOLLOW because the operator's path is never read by Ansible. |
| W19 (iter-2) | Fixed | I8 extended: failure event payload asserted against frozen enum — `phase="push_workspace"`, `state="failed"`, `reason` non-empty. A regression to `state="error"` fails the test. |
| W20 (iter-2) | Fixed | I16 added: `clawctl agent sync ws-hermes --diff` with workspace files present emits one `state="queued", reason="dry-run preview"` event per staged file with `path` + `remote_path` populated. |
| S1 | Adopted | §2 configure.py row updated: "existing unconditional `_do_pair()` call preserved; workspace push is additive." |
| S2 | Adopted | `destination_root` passed as extravar (`workspace_dest_root`) from the manifest to the playbook. Each `workspace.yaml` reads it from extravars rather than hardcoding the path suffix. Eliminates manifest/playbook drift. |
| S3 | Adopted | Python dispatcher short-circuits darwin with a `WorkspaceSkipped(reason="macos_workspace_overlay_pending")` event before invoking ansible-runner. The macOS stub playbook stays as belt-and-suspenders. |
| S4 | Adopted | U13 extended: AST grep also bans `sys.platform`, `platform.system()`, and `os_family ==` literals in `workspace_sync.py`. |
| S5 | Adopted | §1.3 expanded with the exact `help=` strings for each flag. |
| S6 | Adopted | §2: NDJSON events are CLI-only this iteration. GUI relay is out of scope for #760; tracked in a future issue when the GUI grows a workspace surface. |
| S7 | Adopted | §5 trust-boundary note added: SSH key is the auth boundary; anyone with workspace overlay access already has shell access. |
| S8 | Adopted | §2 + §5: secret-pattern mode floor is **always** applied — operator-supplied mode cannot relax 0600 for secret-pattern names. Filename heuristic is defense-in-depth, not a security boundary. |

---

### Iter 1 — Blocking resolutions

| # | Status | Issue → Resolution |
|---|---|---|
| **B1** | Fixed | `--workspace-only` = push workspace files via Ansible **and** rotate the zeroclaw bearer (also via the existing Ansible pair playbook). One line. No "skip pairing" branch. §1.3, I-pair-B. |
| **B2** | Fixed | OS branching split per the project convention: per-agent `playbooks/workspace.yaml` (Linux) + `playbooks/workspace_macos.yaml` (deferred to macOS subtasks #4–#6, matching the `configure.yaml` / `configure_macos.yaml` pattern already used by openclaw and hermes). Python dispatcher uses the existing `core/playbook_resolver.py`, which already routes by `host.os_family`. §2 Files-to-Modify, §3.1 U13, §3.2 I10 rewritten. |
| **B3** | Fixed | Bearer-rotation invariant not pinned in the new sync pipeline. **Resolution**: added I-pair-A and I-pair-B integration tests that capture pre/post `hosts.json.gateway.auth`, assert they differ, assert exactly one `gateway_token_rotated` NDJSON event, with no retry fallback. §3.2. |
| **B4** | Fixed | `configure_agent` code path had zero test coverage. **Resolution**: extracted a shared `push_workspace_phase(...)` helper (also resolves W9), then added three integration tests (I12–I14, one per agent type) exercising the full `configure_agent` path with the same workspace-overlay assertions as the sync path. §2, §3.2. |
| **B5** | Fixed | `install.py` mkdir scaffold had no test. **Resolution**: added U17 (per-type scaffold) and U18 (idempotent on pre-existing dir, owner+mode preserved). §3.1. |

### Iter 1 — Warning resolutions

| # | Status | Resolution summary |
|---|---|---|
| W1 | Fixed | Existing `--workspace` flag renamed to `--no-restart`. `--workspace` kept as deprecated alias for one release; emits a yellow deprecation notice. New `--workspace-only` flag has no naming collision. CHANGELOG `### Changed` entry added to §2. |
| W2 | Fixed | Phase ordering pinned in §1.4: workspace push → restart → verify → (zeroclaw only) repair. Repair runs only after workspace AND restart AND verify succeed. I8 extended to assert no bearer rotation on workspace-phase failure. |
| W3 | Fixed | NDJSON `state` field is a frozen enum `{queued, pushed, excluded, skipped, failed, complete}`. `reason` is a separate field carrying free-text. U-state-enum unit test pins the enum. |
| W4 | Fixed | All operator-visible workspace paths routed through `sanitize_passthrough` (existing helper at `cli/output/_sanitize.py`) before emission. U-bidi unit test pins the sanitize call. |
| W5 | Fixed | §2 explicitly lists Typer `help=` strings and the help-text invariants for `--workspace-only`, `--no-restart`, and the deprecated `--workspace` alias. U-help-text test asserts each flag's help body. |
| W6 | Fixed | **Ansible-only.** Reviewer was right. Per-agent `playbooks/workspace.yaml` does the file push via the `ansible.builtin.copy` module (handles mode/owner/group/`follow:no` natively — see W11–W14 below). No paramiko/SFTP from Python. Python side is a thin dispatcher: enumerate local workspace files → apply manifest excludes → call `playbook_resolver.resolve('workspace', host.os_family)` → invoke ansible-runner with the staged file list as an extravar. macOS subtasks add `workspace_macos.yaml` per agent. §1.5, §2. |
| W7 | Fixed | Per-type destinations and excludes moved into `manifest.yaml` under `features.workspace_overlay.{destination_root, excludes}`. Loaded via the existing manifest loader. Hard-coded fallback removed. Third-party manifests can declare their own. §2, §3.1 U2–U4. |
| W8 | Fixed | Hermes exclude list expanded: `config.yaml`, `.env`, `auth.json`, `state.db`, `sessions/`, `logs/`. `cron/` and `memories/` stay overlay-able by design (operator-defined cron jobs; memories already operator-editable via memory CLI). Documented in §1.1 table and pinned in U3. |
| W9 | Fixed | Single `push_workspace_phase(...)` helper in `core/workspace_sync.py`. Both `sync_agent_canonical` and `configure_agent` call this helper — no dual implementation. §2 and §3.1 U-shared-helper. |
| W10 | Fixed | Match semantics pinned in §1.1: relative path equality for file entries (`config.yaml` matches only `./config.yaml`, NOT `nested/config.yaml`); trailing-slash entries (`sessions/`) are directory-prefix excludes that match every descendant. U-match-semantics unit test covers both shapes. |
| W11 | Fixed | Ansible `ansible.builtin.copy` takes structured args (`src`, `dest`, `mode`, `owner`, `group`) — no shell interpolation, no flag-injection surface. Agent names still validated against `^[a-z0-9][-a-z0-9]{0,62}$` via existing `core/names.py` before reaching ansible-runner; the validator is the only attack surface left, and it's already covered by the existing name-injection tests. U-name-injection retained. |
| W12 | Fixed | `ansible.builtin.copy` defaults to `follow: no` — does not follow symlinks. We pass `follow: no` explicitly in `workspace.yaml` to lock the behavior. Local symlinks are skipped at enumeration time (U6). The TOCTOU class is eliminated because the copy task is one atomic Ansible action, not a separate open/stat/push sequence. |
| W13 | Fixed | Secret-pattern files (`*.key`, `*.pem`, `*.env`, `.env`, `*credentials*`, `*secret*`, `*token*`, `*password*`) get `mode: '0600'` floor via a per-file conditional in `workspace.yaml`. Non-secret files default to `mode: preserve`. U20 pins the floor. |
| W14 | Fixed | Destination root is rendered as a Jinja template in `workspace.yaml` using Ansible's `ansible_user_dir` fact (the agent user's actual home dir, resolved on the host). No string interpolation in Python. The fact is computed by Ansible's setup module against the live host — getent-equivalent. The relevant assertion ("path under `/home/`") is moved to a playbook-level `assert` task that fails the run if `ansible_user_dir` doesn't start with `/home/` (Linux) — matching what the install/configure playbooks already do. |
| W15 | Fixed | §1.1 explicitly scopes this iteration to hermes/openclaw/zeroclaw. `ethos` is in the registry but has no entry in `lifecycle_canonical._RENDERERS` — sync_agent_canonical itself raises for ethos today, so workspace sync inherits the same constraint. U1 asserts that every agent type WITH a canonical renderer also has a workspace-overlay manifest entry (the relevant pairing). Ethos remains intentionally absent until it joins the canonical pipeline. |
| W16 | Fixed | §1.3: `--workspace-only --dry-run` is allowed as a preview mode — enumerate + show + do not push. I-dry-run-only test added in §3.2. |
| W17 | Fixed | I-result-shape tests added covering `CanonicalSyncResult.workspace_files_pushed` in success / empty / failure cases. §3.2 I15. |

---

## 1. User-Centric Outputs

### 1.1 New control-plane convention

A `workspace/` subdirectory inside each agent's local config dir is
operator-droppable. Anything the operator places under it is mirrored
onto the agent host on every `clawctl agent sync` (and `configure`).

```
~/.config/clawrium/agents/<type>/<name>/workspace/   ← drop files here
```

Whatever relative path the operator uses inside `workspace/` is the
same relative path the file lands at under the per-type destination
root on the host (subject to per-type excludes).

#### Destinations (Ubuntu, this iteration) — manifest-declared (W7)

Each agent's `manifest.yaml` declares a new block:

```yaml
features:
  workspace_overlay:
    destination_root: "<absolute path on host, $HOME-rooted>"
    excludes:                  # optional; relative-path strings
      - <relpath>              # file: exact relpath match
      - <relpath>/             # dir: trailing slash = prefix match for all descendants
```

Pinned values for this iteration:

| Agent type | `destination_root` | `excludes` |
|---|---|---|
| **openclaw** | `~/.openclaw/workspace` | (none) |
| **zeroclaw** | `~/.zeroclaw/workspace` | (none) |
| **hermes** | `~/.hermes` | `config.yaml`, `.env`, `auth.json`, `state.db`, `state.db-journal`, `state.db-wal`, `state.db-shm`, `sessions/`, `logs/` |

Why hermes excludes `state.db`/`state.db-{journal,wal,shm}`/`sessions/`/`logs/`
in addition to the canonical-render trio: those are daemon-runtime
state files that the hermes process is actively writing — operator
overwrite would corrupt session history, SQLite transactions (WAL
companions, W13 iter-2), or invalidate the gateway. `cron/` and
`memories/` are intentionally NOT excluded — cron jobs are operator-
defined and memories are already operator-editable through the memory
CLI. **W14 iter-2 caveat**: workspace overlay races with daemon writes
for `memories/` and `cron/`. Recommended workflow is `clawctl agent
stop` → sync → `clawctl agent start` when overlaying these subtrees.
Documented in §5 and `docs/operations/sync.md`. No code-level mutex.

Match semantics (W10):

- A file entry (no trailing slash) matches the local workspace path
  **exactly equal** to that string. `config.yaml` excludes only the
  workspace root `config.yaml`, never a nested `profiles/x/config.yaml`.
- A directory entry (trailing slash) matches every descendant. `sessions/`
  excludes `sessions/anything/foo.json`.

Ethos has no canonical renderer in `lifecycle_canonical._RENDERERS`, so
the canonical sync pipeline itself fails for ethos today. Workspace
overlay does not extend that surface; ethos will gain a workspace-overlay
manifest entry only when ethos joins the canonical pipeline (W15).

### 1.2 Local scaffolding

`clawctl agent create` (and the recovery path in `core/install.py`)
mkdirs the local workspace scaffold for every agent type that has a
`features.workspace_overlay` manifest entry. Existing scaffolds are
left untouched (idempotent — B5/U18).

### 1.3 CLI surface

Existing `clawctl agent sync <name>` behavior is extended. Flag
inventory after this issue:

| Flag | Behavior |
|---|---|
| (none) | Default: canonical render + workspace overlay playbook + restart + verify + (zeroclaw) repair. |
| `--workspace-only` | Workspace overlay playbook + (zeroclaw) repair playbook. Nothing else. Files sync, bearer rotates. |
| `--no-restart` | Canonical render + workspace overlay playbook, no restart. Renamed from existing `--workspace` (W1). |
| `--workspace` | Deprecated alias for `--no-restart`; yellow notice. |
| `--dry-run` | Existing behavior. Workspace overlay phase runs in `ansible-runner` check mode (`--check`). |
| `--diff` | Existing. Workspace files appear as "would push" lines (operator owns them, no rendered counterpart). |
| `--workspace-only --dry-run` | Allowed. Enumerate + invoke playbook in check mode. |
| `--workspace-only --diff` | Mutually exclusive — exits 2. |

### 1.4 Phase ordering (W2, W1/W2/W3 iter-2)

Pinned sequence for the **default** `clawctl agent sync`:

```
1. validate local state
2. push canonical config (provider, skills, channels, env)  ← existing
3. push workspace overlay (workspace.yaml playbook)         ← NEW
4. restart unit
5. verify health
6a. repair gateway bearer (zeroclaw only)
6b. transition state to READY (only if 6a succeeds)
```

Sequence for **`--no-restart`**:

```
1. validate local state
2. push canonical config
3. push workspace overlay
6a. repair gateway bearer (zeroclaw only)  ← unconditional (B1 iter-2)
6b. transition state to READY
```

Sequence for **`--workspace-only`**:

```
3. push workspace overlay
6a. repair gateway bearer (zeroclaw only)  ← runs only if 3 succeeded
```

Pins (B1 iter-2 / W1 iter-2 / W2 iter-2 / W3 iter-2):

- **Phase 6a is unconditional for zeroclaw across all three sync modes.**
  AGENTS.md #437 admits no idempotent-skip path. Default, `--no-restart`,
  and `--workspace-only` all run 6a as long as the upstream phases for
  that mode succeeded. I-pair-A / I-pair-B / I-pair-C cover the three
  modes; I-pair-D asserts the negative case (no rotation for non-zeroclaw).
- **Phase 6a is skipped only when the mode's upstream phases failed**:
  for default, that's phases 2/3/4/5; for `--no-restart`, phases 2/3;
  for `--workspace-only`, phase 3.
- **Stale-bearer window on verify failure**: in default mode, if phase
  4 (restart) succeeds but phase 5 (verify) fails, phase 6a is skipped.
  The daemon has minted a fresh bearer in-memory; `hosts.json.gateway.auth`
  still holds the pre-restart value. The operator must re-run sync after
  fixing the unit to bring hosts.json back in sync. Documented in §5.
  Repair is NOT moved before verify because calling `/pair/code` against
  a daemon in `activating` state has its own failure modes (port not
  bound yet) that are racier than the documented stale window.
- **Phase 6b runs only on 6a success**: if repair fails, state is NOT
  transitioned to READY. Subsequent `clawctl agent start` will surface
  the non-READY state instead of silently claiming healthy on stale auth.
  I-pair-state pins this.

### 1.4.1 Help text strings (W10 iter-2, S5)

Exact strings to land in `cli/clawctl/agent/sync.py`:

```python
workspace_only: bool = typer.Option(
    False, "--workspace-only",
    help=(
        "Push workspace overlay only (rotates zeroclaw bearer). "
        "Skips canonical render, restart, verify. "
        "Mutually exclusive with --diff."
    ),
)
no_restart: bool = typer.Option(
    False, "--no-restart",
    help=(
        "Canonical render + workspace overlay; skip restart and verify. "
        "Still rotates zeroclaw bearer."
    ),
)
# --workspace (existing) → hard error path:
workspace_deprecated: bool = typer.Option(
    False, "--workspace",
    help=(
        "[REMOVED] Use --no-restart for canonical+overlay-no-restart, "
        "or --workspace-only for overlay-only."
    ),
)
```

`agent_app.command("sync", help=...)` short string:

```
"Sync local control-plane state and workspace overlay to the agent."
```

### 1.5 Architectural choice: Ansible (W6)

Every host-side write in this feature goes through Ansible. There is
**no paramiko SFTP** from Python.

- Each agent type ships a new `playbooks/workspace.yaml` (Linux) and
  `playbooks/workspace_macos.yaml` (deferred to subtask). Same shape
  as the existing `configure.yaml` / `configure_macos.yaml` split.
- The playbook reads its file list from a single extravar
  (`workspace_files: [{src: <abs-path-on-control>, rel: <relpath>}, ...]`)
  staged into a tempdir under `${clawrium_config}/staging/workspace/<name>/`.
- `ansible.builtin.copy` does the actual push, with `mode`, `owner`,
  `group`, `follow: no` set on every task. Secret-pattern files get
  `mode: '0600'` via a per-file conditional (W13).
- Destination root is `{{ ansible_user_dir }}/<manifest-relative-root>`
  (e.g. `{{ ansible_user_dir }}/.openclaw/workspace`), so the host's
  own facts decide the home dir (W14).
- Python side (`core/workspace_sync.py`) is a thin wrapper: enumerate
  local workspace, apply manifest excludes, stage the file list, call
  `playbook_resolver.resolve('workspace', host.os_family)` to get the
  right playbook path, hand off to `ansible_runner`, stream stdout
  events back through `on_event`.
- The `_zeroclaw_repair_after_start()` path that runs for zeroclaw
  syncs is **already Ansible-based** (the pair playbook). No change
  there — `--workspace-only` just calls it as the second step after
  the workspace playbook.

### 1.6 Example sessions

```bash
# Stage a profile override for hermes
$ mkdir -p ~/.config/clawrium/agents/hermes/ws-hermes/workspace/profiles/coder
$ cat > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/profiles/coder/SOUL.md <<EOF
You are a senior staff engineer focused on Python.
EOF
$ clawctl agent sync ws-hermes
agent/ws-hermes  validate                    ...
agent/ws-hermes  validate                    complete
agent/ws-hermes  push_config                 ...
agent/ws-hermes  push_config                 complete (0 written, 2 unchanged)
agent/ws-hermes  push_workspace              ...
agent/ws-hermes  push_workspace              complete (1 pushed, 0 excluded)
agent/ws-hermes  restart                     ...
agent/ws-hermes  restart                     complete
agent/ws-hermes  verify                      complete
agent/ws-hermes  synced  (drift=0, took 4s)

$ clawctl agent shell ws-hermes -- 'cat ~/.hermes/profiles/coder/SOUL.md'
You are a senior staff engineer focused on Python.

# Try to slip a hostile config.yaml — must be silently excluded
$ echo "model: { provider: evil }" > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/config.yaml
$ clawctl agent sync ws-hermes -o json | grep workspace
{"resource":"agent/ws-hermes","phase":"push_workspace","state":"excluded","path":"config.yaml","reason":"hermes_canonical_managed"}
{"resource":"agent/ws-hermes","phase":"push_workspace","state":"pushed","path":"profiles/coder/SOUL.md","remote_path":"/home/ws-hermes/.hermes/profiles/coder/SOUL.md","mode":"0644","owner":"ws-hermes"}
{"resource":"agent/ws-hermes","phase":"push_workspace","state":"complete","files_pushed":["profiles/coder/SOUL.md"],"files_excluded":["config.yaml"]}

# Workspace-only — but zeroclaw bearer still rotates (B1)
$ clawctl agent sync ws-zeroclaw --workspace-only -o json | grep -E 'workspace|gateway'
{"resource":"agent/ws-zeroclaw","phase":"push_workspace","state":"complete","files_pushed":["SOUL.md"]}
{"resource":"agent/ws-zeroclaw","phase":"gateway_token_rotated","state":"complete"}

# Deprecated flag emits notice
$ clawctl agent sync ws-openclaw --workspace
Warning: --workspace is deprecated; use --no-restart. Will be removed in a future release.
...
```

## 2. Files to Modify

| Path | Change |
|---|---|
| `src/clawrium/core/workspace_sync.py` | **NEW**. Thin Python wrapper. Exports `push_workspace_phase(host, agent_type, agent_name, workspace_overlay_spec, on_event) -> WorkspacePhaseResult`. Enumerate local workspace, apply manifest excludes (file-equal + dir-prefix match, W10), filter symlinks + `.clawrium-*` dotfiles, stage `workspace_files` extravar list into `${clawrium_config}/staging/workspace/<name>/`, call `playbook_resolver.resolve('workspace', host.os_family)`, hand off to `ansible_runner.run()` with the standard host inventory. Stream ansible-runner events to `on_event`. All operator-visible paths sanitized via `cli/output/_sanitize.py:sanitize_passthrough` (W4). No SFTP, no paramiko, no `os_family` branch in this file — `playbook_resolver` is the OS seam (B2). |
| `src/clawrium/platform/registry/openclaw/playbooks/workspace.yaml` | **NEW**. Receives `workspace_files` extravar. `ansible.builtin.copy` per file with `dest: "{{ ansible_user_dir }}/.openclaw/workspace/{{ item.rel }}"`, `mode: preserve` (or `'0600'` when item.rel matches secret-pattern globs, W13), `owner: "{{ agent_name }}"`, `group: "{{ agent_name }}"`, `follow: no` (W12). Asserts `ansible_user_dir` starts with `/home/` (W14). |
| `src/clawrium/platform/registry/zeroclaw/playbooks/workspace.yaml` | **NEW**. Same shape as openclaw's; `dest: "{{ ansible_user_dir }}/.zeroclaw/workspace/{{ item.rel }}"`. |
| `src/clawrium/platform/registry/hermes/playbooks/workspace.yaml` | **NEW**. Same shape; `dest: "{{ ansible_user_dir }}/.hermes/{{ item.rel }}"`. Manifest excludes are enforced Python-side before reaching the playbook, so the playbook sees only allowed files. |
| `src/clawrium/platform/registry/{openclaw,zeroclaw,hermes}/playbooks/workspace_macos.yaml` | **NEW** (stubs). Single task: `fail: msg="workspace overlay deferred to macOS subtask"`. Subtasks #4–#6 flesh these out (root path becomes `{{ ansible_user_dir }}/...` which already works on darwin; the stubs exist so dispatcher routing is in place from day one). |
| `src/clawrium/core/lifecycle_canonical.py` | New `workspace` phase between the canonical `write` loop and `restart`. Calls `workspace_sync.push_workspace_phase(...)` (which dispatches to the right playbook via `playbook_resolver`). New flag `push_workspace: bool = True`. New fields `workspace_files_pushed: tuple[str, ...]` and `workspace_files_excluded: tuple[str, ...]` on `CanonicalSyncResult`. Phase ordering matches §1.4. Workspace failure does NOT advance to restart (W2). |
| `src/clawrium/cli/clawctl/agent/sync.py` | Add `--workspace-only`, `--no-restart` flags. Keep `--workspace` as deprecated alias emitting a yellow notice (W1). Mutual-exclusion: `--workspace-only --diff` rejected with exit 2; `--workspace-only --dry-run` allowed (W16). NDJSON state values are frozen enum `{queued, pushed, excluded, skipped, failed, complete}` + free-text `reason` (W3). Help text strings pinned in tests (W5). Phase line "push_workspace". |
| `src/clawrium/cli/clawctl/agent/configure.py` | Mirror workspace push by calling `push_workspace_phase` (shared helper, W9/B4). Same Linux-only dispatcher routing as sync. |
| `src/clawrium/core/install.py` | On `clawctl agent create`, `mkdir -p` `~/.config/clawrium/agents/<type>/<name>/workspace/` for every agent type with a `features.workspace_overlay` manifest entry. Idempotent on pre-existing dirs (B5/U18). |
| `src/clawrium/platform/registry/openclaw/manifest.yaml` | Add `features.workspace_overlay: {destination_root: "~/.openclaw/workspace", excludes: []}`. |
| `src/clawrium/platform/registry/zeroclaw/manifest.yaml` | Add `features.workspace_overlay: {destination_root: "~/.zeroclaw/workspace", excludes: []}`. |
| `src/clawrium/platform/registry/hermes/manifest.yaml` | Add `features.workspace_overlay: {destination_root: "~/.hermes", excludes: [config.yaml, .env, auth.json, state.db, "sessions/", "logs/"]}`. |
| `src/clawrium/platform/manifest.py` (or wherever the manifest loader lives) | Parse the new `features.workspace_overlay` block; surface a typed `WorkspaceOverlaySpec` (dataclass) on the loaded manifest. |
| `tests/unit/core/test_workspace_sync.py` | **NEW**. See §3.1 — 22 tests. |
| `tests/integration/test_workspace_overlay_ubuntu.py` | **NEW**. See §3.2 — 15 tests. |
| `CHANGELOG.md` `[Unreleased]` | `### Added` entry for workspace overlay + `--workspace-only`. `### Changed` entry for `--workspace` → `--no-restart` rename + deprecation alias. |
| `docs/operations/sync.md` (+ website mirror per CLAUDE.md rule) | Document the overlay model, per-type destinations (sourced from manifests), exclude semantics, the three flags (`--workspace-only`, `--no-restart`, deprecated `--workspace`), and the Ansible-playbook architecture. |
| `AGENTS.md` | New "Workspace Overlay" section noting: (a) manifest-driven destination + excludes, (b) per-agent `playbooks/workspace.yaml` is the only host-write path, (c) `--workspace-only` syncs files and rotates the zeroclaw bearer (no skip), (d) macOS deferred to per-type follow-up subtasks. |

## 3. Test Plan

### 3.1 Unit tests (`tests/unit/core/test_workspace_sync.py`)

| # | Test | What it asserts |
|---|---|---|
| U1 | `test_every_canonical_renderer_has_workspace_manifest_entry` | For each agent type in `lifecycle_canonical._RENDERERS`, the loaded manifest has `features.workspace_overlay.destination_root`. Hermes/openclaw/zeroclaw covered; ethos is intentionally absent because it has no renderer (W15). |
| U2 | `test_destination_root_values_match_upstream` | Pin the literals: openclaw `~/.openclaw/workspace`, zeroclaw `~/.zeroclaw/workspace`, hermes `~/.hermes`. Sourced from manifests, not hard-coded in core (W7). |
| U3 | `test_hermes_excludes_pin` | Hermes excludes = `{config.yaml, .env, auth.json, state.db, sessions/, logs/}` exactly (W8). |
| U4 | `test_openclaw_zeroclaw_have_no_excludes` | Empty list each. |
| U5 | `test_renderer_output_vs_exclude_invariant` | For each agent type, the rendered file paths that would land under the destination root are a subset of the exclude list. Catches "new template file silently shadowed". |
| U6 | `test_enumerate_skips_symlinks` | Symlink → not enumerated; `WorkspaceSkipped(reason="symlink")` emitted. |
| U7 | `test_enumerate_skips_clawrium_prefixed_dotfiles` | `.clawrium-*` skipped (reserved for future control-plane state). |
| U8 | `test_enumerate_rejects_path_traversal` | Resolved path escaping workspace root → raise. |
| U9 | `test_enumerate_preserves_relative_path_structure` | `workspace/profiles/coder/SOUL.md` → relative path `profiles/coder/SOUL.md`. |
| U10 | `test_extravar_payload_preserves_local_mode_bits` | The `workspace_files` extravar list carries `mode: '0644'` / `'0600'` / `'0755'` from local stat. Playbook is responsible for applying it (verified in §3.2/§3.3). |
| U11 | `test_extravar_payload_carries_agent_owner_group` | Every entry has `owner: <agent_name>`, `group: <agent_name>`. |
| U12 | `test_playbook_resolver_returns_correct_path_per_os` | `resolve('workspace', 'linux')` → `<registry>/<type>/playbooks/workspace.yaml`. `resolve('workspace', 'darwin')` → `..._macos.yaml`. Same dispatcher contract as `configure`. |
| U13 | `test_workspace_sync_python_has_no_paramiko_import` | AST grep / `inspect.getsource` — `workspace_sync.py` does not import `paramiko` and does not call SFTP. Ansible is the only host-write channel (W6). |
| U14 | `test_empty_workspace_is_noop` | Empty workspace → `ansible_runner.run` not called, `files_pushed=()`. |
| U15 | `test_missing_workspace_dir_is_noop` | Non-existent local dir treated as empty, not error. |
| U16 | `test_hermes_excluded_files_emit_events` | `WorkspaceExcluded(path="config.yaml", reason="hermes_canonical_managed")` emitted. |
| U17 | `test_create_agent_scaffolds_workspace_dir_for_each_type` | `clawctl agent create` mkdirs the local workspace dir for hermes/openclaw/zeroclaw (B5). |
| U18 | `test_create_agent_scaffold_is_idempotent_when_workspace_exists` | Pre-existing workspace with custom mode and files → not overwritten, no error (B5). |
| U19 | `test_match_semantics_file_exact_vs_dir_prefix` | `config.yaml` excludes root file only; `sessions/` excludes `sessions/anything` (W10). |
| U20 | `test_extravar_marks_secret_pattern_files_with_0600` | A `*.key`/`*.pem`/`*.env`/`.env`/`*credentials*`/`*secret*`/`*token*`/`*password*` entry has `mode: '0600'` in the extravar regardless of local mode (W13). |
| U21 | `test_agent_name_injection_rejected` | Names like `foo; rm -rf /`, `--reference=/etc/passwd`, `$(whoami)`, `foo/../etc` rejected by `core/names.py` validator at workspace_sync entry (W11). |
| U22 | `test_workspace_playbook_uses_ansible_user_dir_fact` | Each per-type `workspace.yaml` references `{{ ansible_user_dir }}` for the dest root and includes an `assert ansible_user_dir.startswith('/home/')` task (W14). YAML structural test — no host needed. |
| U23 | `test_workspace_playbook_uses_copy_with_follow_no` | Each per-type `workspace.yaml` calls `ansible.builtin.copy` with `follow: no` on every push task (W12). |
| U24 | `test_ndjson_state_field_is_enum` | Every emitted event's `state` is one of `{queued, pushed, excluded, skipped, failed, complete}` (W3). |
| U25 | `test_operator_visible_paths_are_bidi_sanitized` | A workspace path containing U+202E reaches NDJSON / text output with the bidi marker stripped (W4). |
| U26 | `test_help_text_pinned` | Typer `--help` body contains the pinned strings for `--workspace-only`, `--no-restart`, and the deprecation notice for `--workspace` (W5). |
| U27 | `test_shared_helper_called_from_both_configure_and_sync` | Mocked `push_workspace_phase` is called by both `configure_agent` and `sync_agent_canonical` — no parallel implementation (W9). |
| U28 | `test_workspace_only_preserves_zeroclaw_bearer_rotation` | `sync(..., workspace_only=True)` against a zeroclaw record still calls `_zeroclaw_repair_after_start` and emits `gateway_token_rotated` (B1). |

### 3.2 Integration tests (`tests/integration/test_workspace_overlay_ubuntu.py`)

All integration tests use the existing `ansible_runner` mock fixture
(shared with the configure/install integration suites). They assert
the right playbook is invoked with the right extravars, NOT internal
SSH/SFTP details — Ansible owns the wire.

| # | Test | What it asserts |
|---|---|---|

| I1 | `test_sync_invokes_openclaw_workspace_playbook` | Mocked `ansible_runner.run` called with `playbook=<.../openclaw/playbooks/workspace.yaml>` and `extravars.workspace_files` containing `[{rel: "IDENTITY.md", src: "<staging>/IDENTITY.md", mode: "0644", owner: "<name>"}]`. |
| I2 | `test_sync_zeroclaw_workspace_overlay_wins_over_seed_via_playbook_order` | Configure's seed playbook runs first; sync's `workspace.yaml` runs after. Mocked runner records call order; operator `SOUL.md` reaches the workspace playbook's extravar list. |
| I3 | `test_sync_hermes_skips_excludes_before_extravar_staging` | Excludes are applied Python-side. Mocked runner's `workspace_files` extravar contains only `profiles/coder/SOUL.md`. The hostile files (`config.yaml`, `.env`, `auth.json`, `state.db`, `sessions/x.json`, `logs/y.log`) never appear in the extravar payload, and each emits a `WorkspaceExcluded` event. |
| I4 | `test_workspace_only_skips_canonical_and_restart_playbook_calls` | `--workspace-only` → canonical render not called, no `restart.yaml`, no `verify`. Only `workspace.yaml` (and for zeroclaw, the pair playbook). |
| I5 | `test_workspace_only_with_empty_workspace_skips_playbook_invocation` | Empty workspace + `--workspace-only` → `ansible_runner.run` NOT called for `workspace.yaml` (no files to push). Exits 0, `files_pushed=()`. |
| I6 | `test_dry_run_invokes_workspace_playbook_in_check_mode` | `--dry-run` → `ansible_runner.run` called with `cmdline='--check'`. No host writes per Ansible check-mode contract. |
| I7 | `test_workspace_only_and_diff_are_mutually_exclusive` | Exits 2. |
| I8 | `test_workspace_playbook_failure_does_not_advance_to_restart_or_repair` | Mocked ansible-runner returns rc != 0 for `workspace.yaml`. Restart playbook NOT invoked; pair playbook NOT invoked (W2). `CanonicalSyncResult.success=False` references workspace phase. |
| I9 | `test_workspace_push_emits_per_file_ndjson_from_ansible_events` | `-o json` translates ansible-runner's per-task events into NDJSON events with `state="pushed"` and the relpath. |
| I10 | `test_macos_host_dispatches_to_workspace_macos_playbook` | `os_family="darwin"` → `playbook_resolver` returns `workspace_macos.yaml`. The stub playbook fails fast with the expected message; the dispatcher routing itself is verified (B2). |
| I11 | `test_workspace_only_dry_run_combination` | `--workspace-only --dry-run` → `ansible_runner.run` called once with `playbook=workspace.yaml`, `cmdline='--check'`, no other playbooks called (W16). |
| I-pair-A | `test_sync_zeroclaw_rotates_bearer_in_full_flow` | Full sync (canonical + workspace + restart): capture `hosts.json.gateway.auth` pre/post — they differ. Exactly one `gateway_token_rotated` event in the NDJSON stream. No retry fallback (B3). |
| I-pair-B | `test_workspace_only_zeroclaw_still_rotates_bearer` | `--workspace-only` sync: capture `hosts.json.gateway.auth` pre/post — they differ. Exactly one `gateway_token_rotated` event. Proves B1 resolution: workspace-only does NOT skip pairing (B3). |
| I12 | `test_configure_openclaw_pushes_workspace_on_first_install` | Run `configure_agent` for openclaw. Same workspace assertions as I1. |
| I13 | `test_configure_zeroclaw_pushes_workspace_on_first_install_with_bearer_rotation` | Run `configure_agent` for zeroclaw. Workspace lands AND bearer rotates AND `gateway_token_rotated` emitted (B4). |
| I14 | `test_configure_hermes_pushes_workspace_with_excludes_enforced` | Run `configure_agent` for hermes. Excludes enforced (B4). |
| I15 | `test_result_shape_workspace_files_pushed_field` | `CanonicalSyncResult.workspace_files_pushed` is the tuple of relpaths pushed; `workspace_files_excluded` is the tuple of relpaths skipped. Both tested in success / empty / mid-failure cases (W17). |

### 3.3 End-to-end on `wolf-i` (Linux x86_64)

Use the existing `wolf-i` host (hostname `wolf.tailf7742d.ts.net`).
Three fresh agents provisioned from scratch; distinct names so they
don't collide with the existing `wolf-i` openclaw agent (which is
currently in `failed` state per the `clawctl_upgrade_strips_attachments`
memory and unrelated to this work).

Agent test names: `ws-openclaw`, `ws-zeroclaw`, `ws-hermes`.

#### 3.3.1 Provisioning sequence (run per agent type)

`clawctl agent create` runs install + initial configure in one step
— there is no separate `agent install` subcommand. Host-side file
verification uses `clawctl agent shell <name> -- <cmd>`, which ships
under issue #761 (plan merged to main) and is expected to be available
by the time #760 is executed. `clawctl agent exec` forwards to the
agent's native binary and is not suitable for `cat`/`stat`.

```bash
# 1. Create — runs install + initial configure, scaffolds local workspace dir
clawctl agent create ws-openclaw --type openclaw --host wolf-i \
  --provider clawrium-gtm-litellm --yes
clawctl agent create ws-zeroclaw --type zeroclaw --host wolf-i \
  --provider clawrium-gtm-litellm --yes
clawctl agent create ws-hermes --type hermes --host wolf-i \
  --provider clawrium-gtm-litellm --yes

# Assert local workspace scaffold
test -d ~/.config/clawrium/agents/openclaw/ws-openclaw/workspace
test -d ~/.config/clawrium/agents/zeroclaw/ws-zeroclaw/workspace
test -d ~/.config/clawrium/agents/hermes/ws-hermes/workspace

# 2. Baseline sanity — every agent must be healthy before workspace tests
clawctl agent doctor ws-openclaw
clawctl agent doctor ws-zeroclaw
clawctl agent doctor ws-hermes
```

If `agent create` doesn't run install+configure for a given type
(some types may still require an explicit `clawctl agent configure
<name>` follow-up to attach channels/providers in stages), run
`clawctl agent configure <name>` before the doctor check. Any
provisioning failure here blocks the workspace E2E and gets filed
as a separate bug, not as part of #760.

#### 3.3.2 Workspace overlay verification (per agent)

**E1 — openclaw → `/home/ws-openclaw/.openclaw/workspace/`**

```bash
echo "Test marker $(date -u +%FT%TZ)" \
  > ~/.config/clawrium/agents/openclaw/ws-openclaw/workspace/MARKER.md

clawctl agent sync ws-openclaw -o json | tee /tmp/ws-openclaw-sync.ndjson

clawctl agent shell ws-openclaw -- 'cat ~/.openclaw/workspace/MARKER.md'
clawctl agent shell ws-openclaw -- 'stat -c "%a %U:%G" ~/.openclaw/workspace/MARKER.md'
# Expect: 0644 ws-openclaw:ws-openclaw

clawctl agent doctor ws-openclaw
```

**E2 — zeroclaw → `/home/ws-zeroclaw/.zeroclaw/workspace/` — operator-overrides-seed + bearer-rotates (B3 invariant)**

```bash
# Capture canonical-seeded SOUL.md
clawctl agent shell ws-zeroclaw -- 'cat ~/.zeroclaw/workspace/SOUL.md' \
  > /tmp/zc-soul-canonical.txt

# Capture pre-sync gateway auth
pre_auth=$(jq -r '.hosts."wolf-i".agents."ws-zeroclaw".config.gateway.auth' ~/.config/clawrium/hosts.json)

# Operator override
cat > ~/.config/clawrium/agents/zeroclaw/ws-zeroclaw/workspace/SOUL.md <<EOF
# Operator-Overridden Personality
You are a terse Rust expert. No fluff.
EOF

# Full sync — must emit gateway_token_rotated exactly once
clawctl agent sync ws-zeroclaw -o json | tee /tmp/ws-zeroclaw-sync.ndjson

# B3 invariant: bearer must have rotated (no retry fallback)
post_auth=$(jq -r '.hosts."wolf-i".agents."ws-zeroclaw".config.gateway.auth' ~/.config/clawrium/hosts.json)
test "$pre_auth" != "$post_auth"

# Exactly one rotation event
rotations=$(grep -c '"phase":"gateway_token_rotated"' /tmp/ws-zeroclaw-sync.ndjson)
test "$rotations" = "1"

# Operator override won
clawctl agent shell ws-zeroclaw -- 'cat ~/.zeroclaw/workspace/SOUL.md' \
  | grep "terse Rust expert"

# --workspace-only also rotates bearer (B1)
pre2=$(jq -r '.hosts."wolf-i".agents."ws-zeroclaw".config.gateway.auth' ~/.config/clawrium/hosts.json)
echo "more text" >> ~/.config/clawrium/agents/zeroclaw/ws-zeroclaw/workspace/SOUL.md
clawctl agent sync ws-zeroclaw --workspace-only -o json | tee /tmp/ws-zeroclaw-wo.ndjson
post2=$(jq -r '.hosts."wolf-i".agents."ws-zeroclaw".config.gateway.auth' ~/.config/clawrium/hosts.json)
test "$pre2" != "$post2"
grep '"phase":"gateway_token_rotated"' /tmp/ws-zeroclaw-wo.ndjson

clawctl agent doctor ws-zeroclaw
```

**E3 — hermes → `/home/ws-hermes/.hermes/` with exclude list enforced**

```bash
mkdir -p ~/.config/clawrium/agents/hermes/ws-hermes/workspace/profiles/coder
echo "You are a senior staff engineer focused on Python." \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/profiles/coder/SOUL.md

mkdir -p ~/.config/clawrium/agents/hermes/ws-hermes/workspace/memories
echo "Project: workspace overlay E2E test on wolf-i" \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/memories/NOTES.md

# Hostile files — every one in the exclude list
cat > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/config.yaml <<EOF
model:
  provider: "evil"
EOF
echo "OPENROUTER_API_KEY=fake-key" \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/.env
echo '{"oauth":"fake"}' \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/auth.json
echo "stale session" \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/state.db
mkdir -p ~/.config/clawrium/agents/hermes/ws-hermes/workspace/sessions
echo '{"transcript":"hostile"}' \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/sessions/123.json
mkdir -p ~/.config/clawrium/agents/hermes/ws-hermes/workspace/logs
echo "hostile log line" \
  > ~/.config/clawrium/agents/hermes/ws-hermes/workspace/logs/gateway.log

# Capture pre-sync canonical-managed contents
clawctl agent shell ws-hermes -- 'cat ~/.hermes/config.yaml' > /tmp/hermes-config-pre.yaml
clawctl agent shell ws-hermes -- 'cat ~/.hermes/.env'        > /tmp/hermes-env-pre
clawctl agent shell ws-hermes -- 'stat -c "%s" ~/.hermes/state.db || echo missing' > /tmp/hermes-state-pre

clawctl agent sync ws-hermes -o json | tee /tmp/ws-hermes-sync.ndjson

# Good files landed
clawctl agent shell ws-hermes -- 'cat ~/.hermes/profiles/coder/SOUL.md' | grep "senior staff engineer"
clawctl agent shell ws-hermes -- 'cat ~/.hermes/memories/NOTES.md'      | grep "wolf-i"

# Hostile files rejected — canonical-managed bytes unchanged
clawctl agent shell ws-hermes -- 'cat ~/.hermes/config.yaml' > /tmp/hermes-config-post.yaml
clawctl agent shell ws-hermes -- 'cat ~/.hermes/.env'        > /tmp/hermes-env-post
diff /tmp/hermes-config-pre.yaml /tmp/hermes-config-post.yaml
diff /tmp/hermes-env-pre /tmp/hermes-env-post

# Excluded events surfaced
for f in config.yaml .env auth.json state.db sessions/123.json logs/gateway.log; do
  grep -F "\"path\":\"$f\"" /tmp/ws-hermes-sync.ndjson | grep '"state":"excluded"'
done

clawctl agent doctor ws-hermes
```

#### 3.3.3 `--workspace-only` × bearer-rotation invariant (B1, B3)

Repeat the bearer-rotation capture from E2 for openclaw and hermes
(both should NOT emit `gateway_token_rotated` because they're not
zeroclaw). For zeroclaw, repeat once more for redundancy.

#### 3.3.4 Cleanup

```bash
clawctl agent delete ws-openclaw --yes
clawctl agent delete ws-zeroclaw --yes
clawctl agent delete ws-hermes   --yes
```

The existing `wolf-i` openclaw agent stays as-is (separate
`failed`-state cleanup tracked elsewhere).

### 3.4 Definition of done

1. All §3.1 unit tests pass (`make test`).
2. All §3.2 integration tests pass.
3. All §3.3 E2E steps complete successfully on `wolf-i`.
4. `make lint` is clean.
5. `CHANGELOG.md` carries `### Added` (workspace overlay) and `### Changed` (`--workspace` → `--no-restart` rename) entries under `[Unreleased]`.
6. `docs/operations/sync.md` + website mirror document the overlay model.
7. `AGENTS.md` carries the Workspace Overlay section.
8. ATX review rated > 3/5 with all `B#` blockers Fixed.

## 4. Subtasks

### In scope (Ubuntu, this iteration)

1. `[Parent #760] Ubuntu: verify openclaw workspace overlay → /home/<name>/.openclaw/workspace/` (E1).
2. `[Parent #760] Ubuntu: verify zeroclaw workspace overlay → /home/<name>/.zeroclaw/workspace/ + bearer rotation invariant` (E2 + B1/B3 checks).
3. `[Parent #760] Ubuntu: verify hermes workspace overlay → /home/<name>/.hermes/ with full exclude list enforced` (E3).

### Deferred (macOS, follow-up)

4. `[Parent #760] macOS: implement workspace_sync_macos.py + openclaw overlay → /Users/<name>/.openclaw/workspace/`.
5. `[Parent #760] macOS: extend workspace_sync_macos.py + zeroclaw overlay → /Users/<name>/.zeroclaw/workspace/`.
6. `[Parent #760] macOS: extend workspace_sync_macos.py + hermes overlay → /Users/<name>/.hermes/ with exclude list`.

Each macOS subtask: fleshes out the macOS module per dispatcher contract,
adds a real-host integration test against `mac-test` (per AGENTS.md
memory `mac_test_host`).

## 5. Risks

- **Hermes exclude-list drift.** If upstream hermes renames `auth.json`
  → `credentials.json` (or adds a new daemon-runtime file), the exclude
  list must extend. Mitigated by U5 (renderer-output-vs-exclude
  invariant) — hard-fails until the exclude list is updated.
- **Operator surprise on silent exclude.** Per-file `WorkspaceExcluded`
  NDJSON events + a yellow "excluded N files" notice in text mode (W3).
- **Bearer rotation race on `--workspace-only`.** The bearer rotation
  for `--workspace-only` happens against the running daemon (not after
  a restart). I-pair-B + E2.2 pin that the rotation actually succeeds
  against the live daemon and that `hosts.json` reflects the new value
  atomically.
- **Symlink TOCTOU.** O_NOFOLLOW + fstat re-check (W12). U23 regression.
- **Mode preservation.** `ansible.builtin.copy` honors the `mode` arg
  on every push task; extravar carries local mode bits with a 0600
  floor for secret-pattern files (W13). U10 + U20 pin both.
- **No delete-on-host.** Additive sync per issue mandate. Documented in
  `docs/operations/sync.md`. Operator's local rm doesn't propagate.
- **macOS module never exercised before subtask #4.** Mitigated by I10
  asserting the dispatcher correctly routes darwin → macOS module and
  the stub raises a clean `WorkspaceMacOSNotImplemented` (no opaque
  AttributeError).

## 6. Verified from upstream

### Hermes (`https://hermes-agent.nousresearch.com/docs`)

- `~/.hermes/` layout: `config.yaml`, `.env`, `auth.json`, `SOUL.md`,
  `memories/`, `skills/`, `cron/`, `sessions/`, `logs/`, `state.db`,
  `profiles/<name>/`.
- Hermes uses a **profile** model, NOT a workspace model. Profiles are
  full subtrees under `~/.hermes/profiles/<name>/` (or `~/.hermes/` for
  the default profile), scoped via the `HERMES_HOME` env var.
- No `~/.hermes/workspace/` directory exists in upstream hermes.

### OpenClaw (`https://docs.openclaw.ai/concepts/agent-workspace`)

- Upstream explicitly separates config zone (`~/.openclaw/`) from
  workspace zone (`~/.openclaw/workspace/`).
- Workspace zone is the operator-customizable overlay slot — upstream
  recommends backing it up in a private git repo.
- Standard workspace files: `AGENTS.md`, `SOUL.md`, `USER.md`,
  `IDENTITY.md`, `TOOLS.md`, `HEARTBEAT.md`, `STARTUP.md`, `BOOT.md`,
  `ONBOARD.md`, `memory/`, `skills/`, `canvas/`.

### ZeroClaw (`https://docs.zeroclawlabs.ai/master/en/`)

- `~/.zeroclaw/workspace/` holds personality MD files (`SOUL.md`,
  `IDENTITY.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`, `MEMORY.md`,
  `HEARTBEAT.md`, `BOOTSTRAP.md`), `skills/`, `memory/`, `state/`.
- Same operator-overlay design as openclaw — clawctl seeds with
  `force: no` so re-render never clobbers operator edits.

## Prompt Log

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-20T00:00:00Z
**Model**: claude-opus-4-7

```prompt
760 plan only. no file creation
```

Iter 1 followup:

```prompt
ATX review feedback: rating 2/5, blockers B1–B5, warnings W1–W17. Resolve and update plan.
```
