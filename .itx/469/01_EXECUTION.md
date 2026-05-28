# Issue #469 — macOS Support — Execution State

## Plan source

The authoritative 12-step plan lives in the **latest comment** on
[issue #469](https://github.com/ric03uec/clawrium/issues/469) — the comment
titled **"Detailed Implementation Plan — Mac OS Support (Dispatcher-Forked)"**
(comment ID `4561162272`). Read it before starting:

```bash
gh issue view 469 --repo ric03uec/clawrium --comments | less
```

That comment specifies, for each of the 12 steps:
- Files to create / modify (with line ranges where it's an edit).
- Specific commands the playbooks run.
- Failure modes and mitigations.
- Validation procedure (command-level).
- Binary Definition of Done.

## Decisions captured from prior planning conversation (do NOT re-litigate)

1. **Single PR**, branch `issue-469-macos-support`. Commits land
   sequentially, one per step. No mid-branch rebases.
2. **Dispatcher-only OS fork.** Existing Linux files (playbooks,
   `cli/host.py`, `core/lifecycle.py`) stay byte-for-byte unchanged.
   New Mac code lives in parallel files (`*_macos.yaml`, `*_macos.py`).
   This is a feedback memory; do not propose `when: ansible_os_family
   == "Darwin"` edits to existing playbooks.
3. **Linux E2E regression validation is OUT OF SCOPE for this session.**
   The user explicitly opted to rely on unit tests + careful code
   review of the dispatcher (which falls through to identical paths
   for `os_family=linux`). They will validate Linux E2E manually
   before merging the PR.
4. **Mac E2E validation IS IN SCOPE.** Credentials:
   `ssh devashish@100.120.88.97`, password
   `thisisabadpasswordshouldchange`. macOS 26.5 arm64. Xcode CLT is
   already installed (kept from prior cleanup); Homebrew, xclm, and
   hermes are NOT — Step 4 reinstalls them.
5. **No `AskUserQuestion`** anywhere in this execution. If a decision
   is needed, follow project standards (AGENTS.md, neighboring code)
   and record it as a Callout on the PR.

## Execution progress

### Step 1 — Dispatcher (COMPLETED) ✓

- Commit: `8845880`
- Branch HEAD when this file was written: `8845880`
- Files added:
  - `src/clawrium/core/playbook_resolver.py`
  - `src/clawrium/cli/host_bootstrap.py`
  - `tests/core/test_playbook_resolver.py`
  - `tests/core/test_hosts_os_family.py`
- Files modified (Linux-touching, dispatcher integration only):
  - `src/clawrium/cli/clawctl/host/create.py` — `_run_bootstrap` now
    detects OS family and dispatches to `cli/host.py` (linux) or
    `cli/host_macos.py` (darwin, available in step 3).
  - `src/clawrium/core/hosts.py` — `_apply_legacy_defaults()` backfills
    `os_family="linux"` on read.
  - `src/clawrium/core/install.py` — `_get_base_playbook_path` and
    `_get_agent_playbook_path` now take `os_family` and delegate to
    `playbook_resolver`. Both call sites pass
    `host.get("os_family", "linux")`.
  - `tests/test_install_skip.py` — patched the legacy monkeypatch to
    raise `FileNotFoundError` instead of returning a missing-path
    `Path` (matches the new resolver-based control flow).
- Validation:
  - `uv run pytest`: 3348 passed (no regressions from main).
  - `make lint`: clean.
- DoD: all bullets met.

### Steps 2–12 — TODO

Execute in order, **one commit per step**, validate before moving on.
Use the issue comment as the spec; the bullet list below is just a
reminder.

- [ ] **Step 2** — Manifest range/min `os_version` matcher
      (`_version_matches()` in `core/registry.py`; macOS platform entry
      in hermes manifest with placeholder sha256; `core/hardware.py`
      normalizes Darwin facts to lowercase `macos` + marketing
      version).
- [ ] **Step 3** — `cli/host_macos.py` (dscl + sudoers +
      `com.apple.access_ssh` group). Mac E2E: bootstrap xclm, verify
      key auth + passwordless sudo.
- [ ] **Step 4** — `platform/playbooks/base_macos.yaml` (CLT idempotent
      check, Homebrew tarball bootstrap, brew install node ripgrep
      ffmpeg uv). Mac E2E: run playbook, verify all four binaries.
      Note: CLT is already present from prior cleanup — playbook must
      detect that and skip the long install.
- [ ] **Step 5** — `registry/hermes/playbooks/install_macos.yaml`
      (dscl agent user, `/Users/<name>` paths, upstream `install.sh`
      via `become_user`, no service file). Mac E2E: `clawctl agent
      install --type hermes --host mac-test --name h1`. Pin real
      sha256 of upstream install.sh in manifest (placeholder from
      step 2 gets resolved here).
- [ ] **Step 6** — launchd plist templating
      (`registry/hermes/templates/gateway.plist.j2` + `core/launchd.py`
      with `render_plist`/`write_plist`/`remove_plist`). Unit tests
      assert: parses as valid plist, `UserName` is `<agent_name>`,
      no `xclm` anywhere in the plist (regression guard for the
      upstream bug).
- [ ] **Step 7** — `core/lifecycle_macos.py` (launchctl
      bootstrap/bootout/kickstart in `system` domain). Dispatcher
      change in `cli/clawctl/agent/{start,stop,restart,status}.py`
      to call `resolve_lifecycle_backend(host["os_family"])`. Add
      `resolve_lifecycle_backend` to `playbook_resolver.py`
      (rename module if appropriate). Mac E2E: start/stop/restart
      gateway on h1.
- [ ] **Step 8** — `registry/hermes/playbooks/configure_macos.yaml`
      (identical wizard UX; writes `.env` + `config.yaml` to
      `/Users/<agent_name>/.hermes/`; calls into macOS lifecycle
      backend instead of systemctl). Mac E2E: configure h1 with
      OpenRouter key from `~/.ssh/openrouter.key` (already known to
      the prior conversation); `clawctl agent chat h1` returns a real
      completion.
- [ ] **Step 9** — `docs/operations/hermes-macos-upstream-quirks.md`.
      Three upstream hermes bugs (gui-domain plist install, system
      mode wrong path, HERMES_HOME from invoker). File upstream issues
      at NousResearch/hermes-agent and link them.
- [ ] **Step 10** — Dashboard launchd plist (#478 Mac port).
      Second plist template `dashboard.plist.j2`,
      lifecycle_macos.install_service installs BOTH labels, stop reaps
      both. Mac E2E: `clawctl agent open h1` opens dashboard via
      tunnel.
- [ ] **Step 11** — CI matrix + integration tests. Add `macos-14` to
      `.github/workflows/ci.yaml`. Create
      `tests/integration/test_macos_e2e_mocked.py` (stubs upstream
      installer; runs on Linux). Create
      `tests/integration/test_macos_e2e_real.py` marked slow + nightly.
- [ ] **Step 12** — Docs. Update `docs/installation.md` with a "macOS
      targets" section per AGENTS.md "Installation Source of Truth"
      rule. Mirror body verbatim to `website/docs/installation.md`
      (keep its frontmatter + mirror-warning HTML comment).

## Global validation bar (run after Step 12)

Per the issue comment's "Global Validation Bar" section — six-command
end-to-end sequence on a fresh Mac. The Mac at `100.120.88.97` is
fresh enough (no clawrium artifacts, CLT pre-installed, brew absent).
Suitable for the final pass.

## Prompt log

### execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-27T22:00:00Z
**Model**: claude-opus-4-7

```prompt
this shoudl be in a worktree. use /itx-execute worktree
```

**Output**: Spawned `/itx:execute 469` in tmux session
`clawrium-issue-469` (window `issue-469`) targeting worktree
`/home/devashish/workspace/ric03uec/clawrium-issue-469`. Step 1 already
committed at `8845880` (dispatcher + os_family field + resolver + 12
new unit tests, 3348 total pass).
