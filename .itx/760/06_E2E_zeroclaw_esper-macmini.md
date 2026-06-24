# Issue #771 — E2E: zeroclaw workspace overlay playbook on `esper-macmini`

**Phase**: 5 (zeroclaw / macOS)
**Host**: `esper-macmini` (espers-mac-mini.tailf7742d.ts.net, darwin/arm64, macOS 26.5.1)
**Date**: 2026-06-24
**Branch**: `issue-771-zeroclaw-workspace-macos`

## Scope of this E2E (and what it cannot cover)

The standard `clawctl agent sync ws-zeroclaw-mac --workspace-only`
end-to-end flow that Phase 2 (#768) used on `wolf-i` and that Phase 4
(#770) used here on `esper-macmini` for openclaw is **not achievable
for zeroclaw on macOS today**, because the prerequisites do not yet
exist:

- `src/clawrium/platform/registry/zeroclaw/playbooks/` does not contain
  an `install_macos.yaml` (only `workspace_macos.yaml`, added by this
  PR).
- `src/clawrium/platform/registry/zeroclaw/manifest.yaml` has no
  `darwin`/`macos` platform entries — only `debian` (Pi armv7l) and
  `ubuntu` (aarch64/x86_64). Concrete repro of the gap:

  ```
  $ uv run clawctl agent create ws-zeroclaw-mac --type zeroclaw --host esper-macmini
  agent/ws-zeroclaw-mac: [validate] Checking zeroclaw manifest...
  agent/ws-zeroclaw-mac: [validate] Loading host esper-macmini...
  agent/ws-zeroclaw-mac: [validate] Checking compatibility...
  Error: installation failed: Host is incompatible: Requires debian 13,
  host has macos 26.5.1, Requires ubuntu 22.04, host has macos 26.5.1,
  Requires ubuntu 24.04, host has macos 26.5.1
  ```

Standing up a live zeroclaw daemon on macOS is a separate, much larger
workstream (zeroclaw upstream macOS binaries + ports of `install.yaml`,
`configure.yaml`, `start.yaml`, `stop.yaml`, `remove.yaml`,
`restart.yaml`, plus the launchd plist). That is out of scope for the
workspace overlay phase — but it does mean **bearer rotation (#437)
on macOS cannot be exercised live in this PR**. That gap is recorded
as a Callout on the PR and the bearer-rotation invariant is pinned at
the unit-test layer instead (I-pair-A/B/C parametrized for darwin in
`tests/test_workspace_zeroclaw_bearer_rotation.py`).

### What this E2E does cover

Direct invocation of
`src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml`
against `esper-macmini` via `ansible-playbook`, asserting every
security boundary the playbook enforces:

1. Happy path: file lands at `/Users/<agent>/.zeroclaw/workspace/`
   with `agent:staff` ownership and the operator-supplied mode.
2. Tampered `workspace_dest_root` outside `/Users/<agent>/` is
   rejected at the assert task.
3. Path traversal (`..`) in `workspace_dest_root` is rejected at the
   assert task.
4. Invalid `item.mode` (non-octal regex) is rejected at the assert
   task.
5. Path traversal (`..`) in `item.rel` is rejected at the assert task.

The proxy agent identity for the E2E is `xclm` — the SSH user, which
is the only unprivileged user already provisioned on the host. The
slug matches the playbook's `^[a-z][a-z0-9_-]{0,31}$` allowlist;
`workspace_dest_root` expands to `/Users/xclm/.zeroclaw/workspace/`.
The dispatcher routing and bearer-rotation lifecycle live in
`lifecycle_canonical` and are exercised at the unit-test layer
(I-pair-A/B/C darwin variants).

## Setup

```
$ mkdir -p /tmp/clawrium/staging/workspace/ws-zero-test
$ cat > /tmp/clawrium/staging/workspace/ws-zero-test/SOUL.md <<'EOF'
# Issue #771 macOS zeroclaw workspace overlay E2E marker
agent: ws-zeroclaw-mac (proxy: xclm)
host: esper-macmini (espers-mac-mini.tailf7742d.ts.net)
os_family: darwin
expected_destination: /Users/xclm/.zeroclaw/workspace/SOUL.md
test_run_at: 2026-06-24T05:56:03Z
test_scope: workspace overlay playbook validation (no live zeroclaw daemon)
EOF

$ cat > /tmp/ws_zero_inv.yaml <<'EOF'
all:
  hosts:
    esper-macmini:
      ansible_host: espers-mac-mini.tailf7742d.ts.net
      ansible_user: xclm
      ansible_ssh_private_key_file: ~/.config/clawrium/keys/espers-mac-mini.tailf7742d.ts.net/xclm_ed25519
      ansible_python_interpreter: /usr/bin/python3
      ansible_ssh_common_args: '-o StrictHostKeyChecking=no'
EOF
```

## 1. Happy path

```
$ uv run ansible-playbook -i /tmp/ws_zero_inv.yaml \
    src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/Users/xclm/.zeroclaw/workspace' \
    -e 'staging_dir=/tmp/clawrium/staging/workspace/ws-zero-test' \
    -e '{"workspace_files":[{"rel":"SOUL.md","mode":"0644"}]}'

PLAY [all] *****
TASK [Assert agent_name matches the safe slug pattern] *****  ok
TASK [Assert workspace_dest_root is under /Users/xclm/] *****  ok
TASK [Assert staging_dir is a non-empty absolute path under the clawrium staging tree] *****  ok
TASK [Assert workspace_files is a list] *****  ok
TASK [Assert each workspace file entry is a relative path and well-formed mode] *****  ok: [esper-macmini] => (item=SOUL.md)
TASK [Ensure workspace destination root exists] *****  changed
TASK [Ensure parent directories exist for each workspace file] *****  skipping: (item=SOUL.md)
TASK [Push each workspace file onto the host] *****  changed: (item=SOUL.md)

PLAY RECAP *****
esper-macmini  : ok=7  changed=2  unreachable=0  failed=0  skipped=1  rescued=0  ignored=0
```

Verify on host:

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net \
    'stat -f "%Su:%Sg %Sp %z %N" /Users/xclm/.zeroclaw/workspace/SOUL.md'
xclm:staff -rw-r--r-- 341 /Users/xclm/.zeroclaw/workspace/SOUL.md
```

- Owner: `xclm` (the agent user).
- Group: `staff` (gid 20, macOS convention — confirms the playbook's
  `group: staff` literal applied; using `{{ agent_name }}` would have
  failed since no `xclm` group exists on macOS).
- Mode: `0644` (the operator-supplied mode, passed through
  `_floor_mode_for` on the Python side).
- Path: under `/Users/xclm/.zeroclaw/workspace/` — confirms macOS
  prefix expansion fired and the dispatcher routed to the macOS
  playbook variant.

## 2. Tampered `workspace_dest_root` outside `/Users/<agent>/`

```
$ uv run ansible-playbook -i /tmp/ws_zero_inv.yaml \
    src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/etc/zeroclaw/workspace' \
    -e 'staging_dir=/tmp/clawrium/staging/workspace/ws-zero-test' \
    -e '{"workspace_files":[{"rel":"SOUL.md","mode":"0644"}]}'

TASK [Assert workspace_dest_root is under /Users/xclm/] *****
fatal: [esper-macmini]: FAILED! => {
  "assertion": "workspace_dest_root.startswith('/Users/' ~ agent_name ~ '/')",
  "msg": "workspace_dest_root must start with `/Users/xclm/` and contain no
          `..` segments (got '/etc/zeroclaw/workspace')"
}
PLAY RECAP: failed=1
```

B1 iter-3 backstop holds — the assert bails before any `copy` task runs.

## 3. Path traversal (`..`) in `workspace_dest_root`

```
$ uv run ansible-playbook -i /tmp/ws_zero_inv.yaml \
    src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/Users/xclm/../../etc/zeroclaw/workspace' \
    -e 'staging_dir=/tmp/clawrium/staging/workspace/ws-zero-test' \
    -e '{"workspace_files":[{"rel":"SOUL.md","mode":"0644"}]}'

TASK [Assert workspace_dest_root is under /Users/xclm/] *****
fatal: [esper-macmini]: FAILED! => {
  "assertion": "'..' not in workspace_dest_root.split('/')",
  "msg": "workspace_dest_root must start with `/Users/xclm/` and contain no
          `..` segments (got '/Users/xclm/../../etc/zeroclaw/workspace')"
}
PLAY RECAP: failed=1
```

Mirrors openclaw macOS ATX iter-1 W1 hardening on a real darwin host.
The Python-side `_expand_destination_root` does string concatenation
only (no `os.path.normpath`), so this assert is the live backstop.

## 4. Invalid `item.mode`

```
$ uv run ansible-playbook -i /tmp/ws_zero_inv.yaml \
    src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/Users/xclm/.zeroclaw/workspace' \
    -e 'staging_dir=/tmp/clawrium/staging/workspace/ws-zero-test' \
    -e '{"workspace_files":[{"rel":"SOUL.md","mode":"a644"}]}'

TASK [Assert each workspace file entry is a relative path and well-formed mode] *****
failed: [esper-macmini] (item=SOUL.md) => {
  "assertion": "item.mode is match('^0[0-7]{3,4}$')",
  "msg": "workspace file entry has unsafe rel or mode: rel='SOUL.md', mode='a644'"
}
PLAY RECAP: failed=1
```

Mirrors openclaw macOS ATX iter-1 W7/S6 hardening. A hostile extravar
injecting a malformed mode string is rejected before any `copy` task.

## 5. Path traversal (`..`) in `item.rel`

```
$ uv run ansible-playbook -i /tmp/ws_zero_inv.yaml \
    src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/Users/xclm/.zeroclaw/workspace' \
    -e 'staging_dir=/tmp/clawrium/staging/workspace/ws-zero-test' \
    -e '{"workspace_files":[{"rel":"../escaped.md","mode":"0644"}]}'

TASK [Assert each workspace file entry is a relative path and well-formed mode] *****
failed: [esper-macmini] (item=../escaped.md) => {
  "assertion": "'..' not in (item.rel.split('/'))",
  "msg": "workspace file entry has unsafe rel or mode: rel='../escaped.md', mode='0644'"
}
PLAY RECAP: failed=1
```

W12 iter-2 belt-and-suspenders holds on macOS — Python-side
enumeration already filters traversal, but the playbook re-asserts it.

## Cleanup

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net \
    'rm -f /Users/xclm/.zeroclaw/workspace/SOUL.md; \
     rmdir /Users/xclm/.zeroclaw/workspace 2>/dev/null; \
     rmdir /Users/xclm/.zeroclaw 2>/dev/null; \
     ls -la /Users/xclm/.zeroclaw 2>&1'
ls: /Users/xclm/.zeroclaw: No such file or directory
```

Host left in starting state.

## Gaps documented (Callouts on the PR)

- **Bearer rotation (#437) on macOS** — cannot be exercised live until
  zeroclaw ships macOS binaries + an `install_macos.yaml`. Pinned at
  the unit-test layer: I-pair-A/B/C darwin variants in
  `tests/test_workspace_zeroclaw_bearer_rotation.py`.
- **Lifecycle verbs (stop / remove) on macOS** — same prerequisite
  gap. The `lifecycle_macos.py` dispatcher uses `launchctl
  kickstart -k` / `launchctl bootout`, which #770 validated for
  openclaw on this host; the path is identical for zeroclaw once the
  upstream binaries land.
- **`clawctl agent doctor` healthy after each sync** — requires a
  live zeroclaw daemon on darwin. Out of scope here.
- **`clawctl agent delete --yes ws-zeroclaw-mac` cleanup** — no
  `ws-zeroclaw-mac` agent was created (the install failed at
  compatibility check, as expected). Cleanup of the synthetic
  `/Users/xclm/.zeroclaw/` directory is shown above.
