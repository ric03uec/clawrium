# Issue #344 — Auto-install hermes system dependencies (ripgrep, ffmpeg)

## Customer Outcome
`clm agent install --type hermes --host <target>` succeeds on a fresh Ubuntu host without the operator having to SSH in and `apt-get install` ripgrep and ffmpeg by hand.

## Problem Summary
`src/clawrium/platform/registry/hermes/playbooks/install.yaml` currently runs preflight `which rg` / `which ffmpeg` checks and HARD-FAILS with a remediation message when either binary is missing (lines 25–52). The manifest already declares both as platform dependencies (`manifest.yaml` lines 116–117, 125–126), but nothing in the playbook acts on those declarations — they are documentation only.

## Approach
Replace the "fail if missing" preflight tasks with idempotent `apt` installs. The playbook already runs `become: yes`, so package installation works without additional privilege escalation. Use `update_cache: yes` with a `cache_valid_time` so we don't punish well-maintained hosts with a full apt-update on every install.

Trade-off considered: leaving the `which` detection in place and only running `apt` when missing is fractionally faster on hosts where the binaries exist, but it adds two tasks and a `when:` branch for what `apt: state=present` already handles idempotently. Choosing the simpler form.

Out of scope: non-apt distros (RHEL/Fedora/Arch). The manifest pins `os: ubuntu` for both supported platforms (`manifest.yaml` lines 105, 112), so a `become + apt` task is sufficient. If/when non-Debian support lands, swap to `ansible.builtin.package` with `module_defaults`.

## Files to Modify

### `src/clawrium/platform/registry/hermes/playbooks/install.yaml`
Replace lines 25–52 (the four preflight tasks: `which rg` check, fail-if-missing, `which ffmpeg` check, fail-if-missing) with a single `ansible.builtin.apt` task installing both packages.

Proposed replacement:

```yaml
    # Hermes upstream installer requires `rg` and `ffmpeg` on PATH. Install
    # them via apt before invoking the installer rather than failing with a
    # manual-remediation message. The playbook already runs `become: yes`,
    # so no extra escalation is needed. `cache_valid_time` avoids hammering
    # apt mirrors when the cache is recent.
    - name: Install hermes system dependencies (ripgrep, ffmpeg)
      ansible.builtin.apt:
        name:
          - ripgrep
          - ffmpeg
        state: present
        update_cache: yes
        cache_valid_time: 3600
```

### `tests/test_registry_hermes.py`
Lines 131–135 assert that `which rg` and `which ffmpeg` appear in the install playbook. Update the assertions to verify the new behavior: apt task present, both package names listed.

Proposed change:

```python
    # Hermes upstream installer requires ripgrep and ffmpeg. Verify they are
    # installed via apt rather than expected to be pre-provisioned.
    assert "ansible.builtin.apt" in content
    assert "ripgrep" in content
    assert "ffmpeg" in content
```

## Steps
1. Edit `install.yaml` — replace the four preflight tasks with the single `apt` install task.
2. Update `tests/test_registry_hermes.py` assertions to match.
3. Run `make test` and `make lint`. Fix any failures.
4. Manual smoke (optional, if a target host is available): `clm agent install --type hermes --host <fresh-ubuntu>` on a host where `rg` and `ffmpeg` are absent, confirm install succeeds.

## Test Strategy
- **Unit**: existing `test_registry_hermes.py` covers playbook structure — update assertions and run `make test`.
- **Idempotency**: `apt: state=present` is idempotent by design; re-running the playbook on a host where both packages exist must be a no-op (already covered by the broader install-skip path on subsequent runs).
- **Manual**: smoke install on a fresh Ubuntu 22.04 and/or 24.04 host where `rg` and `ffmpeg` are absent.

## Risks
- **Apt lock contention**: if another process holds `/var/lib/dpkg/lock-frontend`, the task fails. Acceptable — same failure mode the user would hit running apt manually. Not worth a retry loop in v1.
- **Cache staleness**: `cache_valid_time: 3600` means if a host hasn't updated its cache in over an hour, we trigger `apt-get update` before install. That's the right default; adds 5–30s on first install per host but avoids stale-index failures.
- **Network**: hosts behind restrictive egress that block Ubuntu mirrors will fail. Same failure mode as today's "install ripgrep manually" path — not a regression.

## Subtasks
None — single-file behavior change with a paired test update. Below the 3-file threshold.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-15T00:00:00Z
**Model**: claude-opus-4-7

```prompt
344 plan create only. dont update issue
```

</details>
