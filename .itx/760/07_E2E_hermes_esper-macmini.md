# Issue #772 — E2E: hermes workspace overlay playbook on `esper-macmini`

**Phase**: 6 (hermes / macOS)
**Host**: `esper-macmini` (espers-mac-mini.tailf7742d.ts.net, darwin/arm64, macOS 26.5.1)
**Date**: 2026-06-24
**Branch**: `issue-772-hermes-workspace-macos`

## Scope of this E2E (and what it cannot cover)

The standard `clawctl agent sync ws-hermes-mac --workspace-only`
end-to-end flow that Phase 3 (#769) ran on `wolf-i` is **not
achievable for hermes on `esper-macmini` today** without standing up
a full hermes upstream install. The hermes manifest does declare a
macOS arm64 platform entry, but the upstream installer chain (clones
the repo, builds the ui-tui Node bundle, installs the `[web,pty]`
extras via uv) is heavy enough that running it against
`esper-macmini` purely to exercise the workspace-overlay phase would
trade a 10-second narrow test for a 5+ minute end-to-end run that
also pulls in dashboard prerequisites, the venv reconciler, the
launchd plist, and the bearer-auth handshake — none of which Phase 6
introduces.

So this E2E follows the same shape Phase 4 (#770) and Phase 5 (#771)
used on this host: direct invocation of
`src/clawrium/platform/registry/hermes/playbooks/workspace_macos.yaml`
against `esper-macmini` via `ansible-playbook`, asserting every
security boundary the playbook enforces — including the
hermes-specific exclude-payload boundary that the openclaw/zeroclaw
variants do not have.

### What this E2E does cover

1. Happy path: nested good files land at `/Users/<agent>/.hermes/`
   with `agent:staff` ownership and the operator-supplied mode.
2. **Full hostile-file set** — every one of the 10 manifest exclude
   entries (`config.yaml`, `.env`, `auth.json`, `state.db` + 3 WAL
   companions, `sessions/`, `logs/`, `skills/clawrium/`) is filtered
   by the per-file `workspace_excluded` Jinja `when:` clause and does
   NOT land on host. Pre/post diff of `~/.hermes/` shows zero leak.
3. Tampered `workspace_dest_root` outside `/Users/<agent>/` is
   rejected at the assert task (B1 iter-3 backstop, macOS variant).
4. Path traversal (`..`) in `workspace_dest_root` is rejected at the
   assert task (ATX iter-1 W1).
5. Invalid `item.mode` (non-octal regex) is rejected at the assert
   task (ATX iter-1 W6).
6. Path traversal (`..`) in `item.rel` is rejected at the assert task
   (W12 iter-2 belt-and-suspenders).
7. `item.src` outside `staging_dir` is rejected at the assert task
   (ATX iter-2 S_NEW_1 — carried forward from Linux hermes).
8. Malformed `workspace_excludes_files` (string instead of list) is
   rejected at the assert task — the hermes-specific gate that
   openclaw and zeroclaw don't need.

### What this E2E does NOT cover

- `clawctl agent doctor` health on macOS — requires a live hermes
  daemon, which in turn requires the upstream `[web,pty]` install +
  launchd plist + ui-tui build. Documented as a **Callout** on the
  PR (B5 from cross-issue ATX findings).
- `clawctl agent stop` / `clawctl agent remove` on macOS — same
  prerequisite gap (the lifecycle paths in `core/lifecycle_macos.py`
  use `launchctl kickstart -k` / `launchctl bootout`, validated for
  openclaw by #770; the contract is identical for hermes once the
  upstream install actually runs to completion on this host).
- `clawctl agent delete --yes ws-hermes-mac` cleanup — no agent
  was created (we use the SSH proxy user `xclm`); the synthetic
  `/Users/xclm/.hermes/` tree is wiped via `rm -rf` at the end (see
  Cleanup below).

The proxy agent identity for the E2E is `xclm` — the SSH user, which
is the only unprivileged user already provisioned on the host. The
slug matches the playbook's `^[a-z][a-z0-9_-]{0,31}$` allowlist;
`workspace_dest_root` expands to `/Users/xclm/.hermes` (no
`workspace/` suffix — hermes overlays directly under `~/.hermes/`
because it shares the destination root with canonical render output).

## Setup

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net \
    'rm -rf /Users/xclm/.hermes; mkdir -p /Users/xclm/.hermes; \
     stat -f "%Su:%Sg %Sp %N" /Users/xclm/.hermes'
xclm:staff drwxr-xr-x /Users/xclm/.hermes

$ TS_DIR=/tmp/clawrium/staging/workspace/ws-hermes-mac-$(date +%s)
$ mkdir -p "$TS_DIR/profiles/coder" "$TS_DIR/memories"
$ echo "phase-6 e2e SOUL"  > "$TS_DIR/profiles/coder/SOUL.md"
$ echo "phase-6 e2e NOTES" > "$TS_DIR/memories/NOTES.md"

$ cat > /tmp/ws_hermes_inv.yaml <<'EOF'
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
$ uv run ansible-playbook -i /tmp/ws_hermes_inv.yaml \
    src/clawrium/platform/registry/hermes/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/Users/xclm/.hermes' \
    -e "staging_dir=$TS_DIR" \
    -e "{\"workspace_files\":[
          {\"rel\":\"profiles/coder/SOUL.md\",
           \"src\":\"$TS_DIR/profiles/coder/SOUL.md\",\"mode\":\"0644\"},
          {\"rel\":\"memories/NOTES.md\",
           \"src\":\"$TS_DIR/memories/NOTES.md\",\"mode\":\"0644\"}
        ]}" \
    -e '{"workspace_excludes_files":["config.yaml",".env","auth.json","state.db","state.db-journal","state.db-wal","state.db-shm"]}' \
    -e '{"workspace_excludes_dirs":["sessions","logs","skills/clawrium"]}'

PLAY [all] *****
TASK [Assert agent_name matches the safe slug pattern] *****  ok
TASK [Assert workspace_dest_root is under /Users/xclm/] *****  ok
TASK [Assert staging_dir is a non-empty absolute path under the clawrium staging tree] *****  ok
TASK [Assert workspace_files is a list] *****  ok
TASK [Assert workspace_excludes_files is a list] *****  ok
TASK [Assert workspace_excludes_dirs is a list] *****  ok
TASK [Assert each workspace file entry is a relative path and well-formed mode] *****
  ok: (item=profiles/coder/SOUL.md)
  ok: (item=memories/NOTES.md)
TASK [Assert each workspace file entry's src lives under staging_dir] *****
  ok: (item=profiles/coder/SOUL.md)
  ok: (item=memories/NOTES.md)
TASK [Ensure workspace destination root exists] *****  ok
TASK [Ensure parent directories exist for each non-excluded workspace file] *****
  changed: (item=profiles/coder/SOUL.md)
  changed: (item=memories/NOTES.md)
TASK [Push each non-excluded workspace file onto the host] *****
  changed: (item=profiles/coder/SOUL.md)
  changed: (item=memories/NOTES.md)

PLAY RECAP *****
esper-macmini  : ok=11  changed=2  unreachable=0  failed=0  skipped=0
```

Verify on host:

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net \
    'stat -f "%Su:%Sg %Sp %z %N" /Users/xclm/.hermes/profiles/coder/SOUL.md \
                                   /Users/xclm/.hermes/memories/NOTES.md'
xclm:staff -rw-r--r-- 17 /Users/xclm/.hermes/profiles/coder/SOUL.md
xclm:staff -rw-r--r-- 18 /Users/xclm/.hermes/memories/NOTES.md
```

- Owner: `xclm` (the agent user).
- Group: `staff` (gid 20, macOS convention — confirms the playbook's
  `group: staff` literal applied; using `{{ agent_name }}` would have
  failed since no `xclm` group exists on macOS).
- Mode: `0644` (operator-supplied, threaded through the playbook).
- Paths: under `/Users/xclm/.hermes/` — confirms macOS prefix
  expansion fired and the dispatcher routed to the macOS playbook
  variant.
- Nested rel (`profiles/coder/SOUL.md`) lands correctly — exercises
  the `when: dirname | length > 0` gate on parent-dir creation.

## 2. Hostile file set — all 10 manifest excludes filtered on macOS

Staged every exclude entry with hostile bytes:

```
$ TS_DIR=/tmp/clawrium/staging/workspace/ws-hermes-mac-hostile-$(date +%s)
$ mkdir -p "$TS_DIR/sessions" "$TS_DIR/logs" "$TS_DIR/skills/clawrium/tdd"
$ echo "MALICIOUS: overwrites canonical"        > "$TS_DIR/config.yaml"
$ echo "MALICIOUS_KEY=stolen"                    > "$TS_DIR/.env"
$ echo '{"malicious":true}'                      > "$TS_DIR/auth.json"
$ echo "MALICIOUS-DB"                            > "$TS_DIR/state.db"
$ echo "MALICIOUS-JOURNAL"                       > "$TS_DIR/state.db-journal"
$ echo "MALICIOUS-WAL"                           > "$TS_DIR/state.db-wal"
$ echo "MALICIOUS-SHM"                           > "$TS_DIR/state.db-shm"
$ echo '{"malicious_session":true}'              > "$TS_DIR/sessions/123.json"
$ echo "MALICIOUS-LOG"                           > "$TS_DIR/logs/gateway.log"
$ echo "MALICIOUS-SKILL"                         > "$TS_DIR/skills/clawrium/tdd/SKILL.md"
```

Baseline before run:

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net 'ls -la /Users/xclm/.hermes/'
drwxr-xr-x  xclm staff  memories
drwxr-xr-x  xclm staff  profiles
```

Invoke with all 10 hostile entries in `workspace_files` + the full
hermes exclude payload as extravars (matches what
`core.workspace_sync.push_workspace_phase` would send):

```
$ uv run ansible-playbook -i /tmp/ws_hermes_inv.yaml \
    src/clawrium/platform/registry/hermes/playbooks/workspace_macos.yaml \
    -e 'agent_name=xclm' \
    -e 'workspace_dest_root=/Users/xclm/.hermes' \
    -e "staging_dir=$TS_DIR" \
    -e "{\"workspace_files\":[<all 10 hostile entries>]}" \
    -e '{"workspace_excludes_files":["config.yaml",".env","auth.json","state.db","state.db-journal","state.db-wal","state.db-shm"]}' \
    -e '{"workspace_excludes_dirs":["sessions","logs","skills/clawrium"]}'

TASK [Ensure parent directories exist for each non-excluded workspace file] *****
  skipping: (item=config.yaml)
  skipping: (item=.env)
  skipping: (item=auth.json)
  skipping: (item=state.db)
  skipping: (item=state.db-journal)
  skipping: (item=state.db-wal)
  skipping: (item=state.db-shm)
  skipping: (item=sessions/123.json)
  skipping: (item=logs/gateway.log)
  skipping: (item=skills/clawrium/tdd/SKILL.md)

TASK [Push each non-excluded workspace file onto the host] *****
  skipping: (item=config.yaml)
  skipping: (item=.env)
  skipping: (item=auth.json)
  skipping: (item=state.db)
  skipping: (item=state.db-journal)
  skipping: (item=state.db-wal)
  skipping: (item=state.db-shm)
  skipping: (item=sessions/123.json)
  skipping: (item=logs/gateway.log)
  skipping: (item=skills/clawrium/tdd/SKILL.md)

PLAY RECAP: esper-macmini : ok=9  changed=0  unreachable=0  failed=0  skipped=2
```

Verify zero leak on host:

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net 'ls -la /Users/xclm/.hermes/'
drwxr-xr-x  xclm staff  memories       # unchanged
drwxr-xr-x  xclm staff  profiles       # unchanged

$ ssh xclm@espers-mac-mini.tailf7742d.ts.net '
    for f in config.yaml .env auth.json state.db state.db-{journal,wal,shm}; do
      [ -e /Users/xclm/.hermes/$f ] && echo "LEAK: $f" || echo "ok-absent: $f"
    done
    for d in sessions logs skills; do
      [ -e /Users/xclm/.hermes/$d ] && echo "LEAK-DIR: $d" || echo "ok-absent: $d"
    done'
ok-absent: config.yaml
ok-absent: .env
ok-absent: auth.json
ok-absent: state.db
ok-absent: state.db-journal
ok-absent: state.db-wal
ok-absent: state.db-shm
ok-absent: sessions
ok-absent: logs
ok-absent: skills
```

**All 10 manifest exclude entries — including all three SQLite WAL
companion files (`state.db-journal`, `state.db-wal`, `state.db-shm`)
and the `skills/clawrium/` dir-prefix — are filtered by the per-file
`workspace_excluded` Jinja `when:` clause and never reach the host.**

> **Daemon state during Test 2** (ATX iter-1 S4 note): NO live hermes
> daemon was running on `esper-macmini` during this E2E. The host
> `/Users/xclm/.hermes/` tree was freshly created by the Setup step
> with only the operator-good `memories/` and `profiles/` dirs from
> Test 1; there is no SQLite WAL to corrupt under load here. The W13
> iter-2 invariant (overlaying any WAL companion while the daemon
> holds the WAL open corrupts the database silently) is structurally
> proven by this test — the filter prevents the overlay from ever
> reaching the host — but the live-corruption case under daemon load
> remains exercised only by the Phase 3 Ubuntu E2E (#769,
> `.itx/760/04_E2E_hermes_wolf-i.md`), which ran the full
> `clawctl agent sync` flow against an actively serving hermes
> daemon. Standing up a live hermes daemon on this Mac would have
> required the upstream installer + ui-tui Node build + launchd
> plist drop — out of scope for the workspace-overlay phase.
The control-machine-side `workspace_excluded` filter loads from the
adjacent `filter_plugins/clawrium_filters.py` (Ansible auto-discovers
filter_plugins/ alongside the playbook), which is the same plugin
file the Linux hermes/workspace.yaml uses — so the filter logic is
provably identical across Linux and macOS dispatch paths.

## 3. Tampered `workspace_dest_root` outside `/Users/<agent>/`

```
$ uv run ansible-playbook ... -e 'workspace_dest_root=/etc/hermes' ...
TASK [Assert workspace_dest_root is under /Users/xclm/] *****
fatal: [esper-macmini]: FAILED! => {
  "assertion": "workspace_dest_root.startswith('/Users/' ~ agent_name ~ '/')",
  "msg": "workspace_dest_root must start with `/Users/xclm/` and contain no
          `..` segments (got '/etc/hermes')"
}
PLAY RECAP: failed=1
```

B1 iter-3 backstop holds (macOS variant) — the assert bails before
any `copy` task runs.

## 4. Path traversal (`..`) in `workspace_dest_root`

```
$ uv run ansible-playbook ... -e 'workspace_dest_root=/Users/xclm/../../etc/hermes' ...
TASK [Assert workspace_dest_root is under /Users/xclm/] *****
fatal: [esper-macmini]: FAILED! => {
  "assertion": "'..' not in workspace_dest_root.split('/')",
  "msg": "workspace_dest_root must start with `/Users/xclm/` and contain no
          `..` segments (got '/Users/xclm/../../etc/hermes')"
}
PLAY RECAP: failed=1
```

ATX iter-1 W1 hardening (mirrored from openclaw + zeroclaw macOS)
holds on a real darwin host. The Python-side
`_expand_destination_root` does string concatenation only (no
`os.path.normpath`), so this assert is the live backstop.

## 5. Invalid `item.mode` (non-octal regex)

```
$ uv run ansible-playbook ... \
    -e "{\"workspace_files\":[{\"rel\":\"SOUL.md\",\"src\":\"$TS_DIR/SOUL.md\",\"mode\":\"a644\"}]}" ...
TASK [Assert each workspace file entry is a relative path and well-formed mode] *****
failed: [esper-macmini] (item=SOUL.md) => {
  "assertion": "item.mode is match('^0[0-7]{3,4}$')",
  "msg": "workspace file entry has unsafe rel or mode: rel='SOUL.md', mode='a644'"
}
PLAY RECAP: failed=1
```

ATX iter-1 W6 (security-reviewer) hardening — a hostile extravar
injecting a malformed mode string is rejected before any `copy` task.

## 6. Path traversal (`..`) in `item.rel`

```
$ uv run ansible-playbook ... \
    -e "{\"workspace_files\":[{\"rel\":\"../escaped.md\",\"src\":\"$TS_DIR/SOUL.md\",\"mode\":\"0644\"}]}" ...
TASK [Assert each workspace file entry is a relative path and well-formed mode] *****
failed: [esper-macmini] (item=../escaped.md) => {
  "assertion": "'..' not in (item.rel.split('/'))",
  "msg": "workspace file entry has unsafe rel or mode: rel='../escaped.md', mode='0644'"
}
PLAY RECAP: failed=1
```

W12 iter-2 belt-and-suspenders holds on macOS.

## 7. `item.src` outside `staging_dir`

```
$ uv run ansible-playbook ... \
    -e "{\"workspace_files\":[{\"rel\":\"stolen.md\",\"src\":\"/etc/passwd\",\"mode\":\"0644\"}]}" ...
TASK [Assert each workspace file entry's src lives under staging_dir] *****
failed: [esper-macmini] (item=stolen.md) => {
  "assertion": "item.src.startswith(staging_dir ~ '/')",
  "msg": "workspace file entry has unsafe src: '/etc/passwd' (must start with
          '/tmp/clawrium/staging/workspace/ws-hermes-mac-safety-.../')"
}
PLAY RECAP: failed=1
```

ATX iter-2 S_NEW_1 (carried forward from Linux hermes/workspace.yaml)
holds — a regression in `_stage_files` or any caller injecting
`workspace_files` extravars cannot smuggle an arbitrary absolute path
through.

## 8. Malformed `workspace_excludes_files` (string, not list)

```
$ uv run ansible-playbook ... \
    -e '{"workspace_excludes_files":"not-a-list"}' ...
TASK [Assert workspace_excludes_files is a list] *****
fatal: [esper-macmini]: FAILED! => {
  "assertion": "workspace_excludes_files is not string",
  "msg": "workspace_excludes_files must be a list"
}
PLAY RECAP: failed=1
```

Hermes-specific gate (openclaw + zeroclaw ship empty exclude lists
and their playbooks don't inspect the payload) — pins that a missing
or malformed exclude payload cannot silently degrade to "let every
file through".

## Cleanup

```
$ ssh xclm@espers-mac-mini.tailf7742d.ts.net 'rm -rf /Users/xclm/.hermes; ls /Users/xclm/.hermes 2>&1'
ls: /Users/xclm/.hermes: No such file or directory
```

Host left in starting state. All local `/tmp/clawrium/staging/workspace/ws-hermes-*`
staging dirs removed.

## Gaps documented (Callouts on the PR)

- **Live hermes daemon lifecycle on macOS** — `clawctl agent doctor`,
  `clawctl agent stop`, `clawctl agent remove` cannot be exercised
  here without running the full `clawctl agent create ws-hermes-mac
  --type hermes --host esper-macmini` flow, which pulls in the upstream
  hermes installer, the `[web,pty]` extras, the ui-tui Node bundle,
  the launchd plist, and the bearer-auth handshake. None of those
  layers are touched by this PR. The lifecycle-verb completeness
  invariant (cross-issue ATX finding **B5**) is pinned for openclaw
  by #770 on this same host; the contract is identical for hermes
  once the upstream install actually runs to completion. Documented
  here so reviewers can decide whether to track a follow-up to
  smoke-test the full lifecycle on this Mac.
- **`clawctl agent delete --yes ws-hermes-mac`** — not run because no
  agent was created (this E2E uses the SSH proxy user `xclm`). The
  synthetic `/Users/xclm/.hermes/` tree was wiped via `rm -rf` at the
  end (see Cleanup).
- **Workspace overlay sync from a real install** — the Phase 3 (#769)
  Ubuntu E2E ran the full `clawctl agent sync ws-hermes --workspace-only`
  flow against a freshly installed hermes daemon. The macOS counterpart
  of that integration test would require the same upstream-install
  prerequisites as above and is similarly deferred.
