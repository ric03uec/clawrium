# Hermes macOS upstream quirks

This document records the upstream NousResearch/hermes-agent defects
that clawrium routes around on macOS. Each quirk lists the symptom,
the upstream code path, and the mitigation in this repo.

The aim: when upstream fixes any of these, the corresponding workaround
here can be reverted (or simplified) confidently. We will file these
upstream as separate issues and link the issue URL next to each entry
once filed.

> **Track**: issue #469 (initial Mac support).
> **Status**: workarounds active. Upstream filings pending.

---

## Quirk 1 — Default launchd plist binds to `gui` domain

**Symptom**: an upstream-installed hermes gateway exits the moment the
user logs out of the GUI session. On a reboot the daemon does not come
back unless someone logs in interactively. Wrong domain for an always-on
agent.

**Upstream code path**:
The hermes installer drops `~/Library/LaunchAgents/<label>.plist` (per-user,
GUI-bound). `launchctl` enrols it into `gui/<uid>` rather than `system`.

**Why this is wrong for us**: clawrium agents are headless services. The
agent user is a managed account; nobody ever runs a `login` shell as it.

**Clawrium mitigation**:
- `src/clawrium/platform/registry/hermes/templates/gateway.plist.j2`
  renders into `/Library/LaunchDaemons/` (system domain).
- `core/launchd.write_plist` installs the file as `root:wheel 0644`.
- `core/lifecycle_macos.start_agent_macos` calls
  `launchctl bootstrap system <plist>` (NOT `gui/<uid>`).
- Test `tests/core/test_launchd.py::test_plist_path_for_lives_in_system_daemons`
  asserts the path never lands under `LaunchAgents`.

**Revert criteria**: upstream switches to a system-domain plist by
default and exposes a `--label` / `--user` flag we can pass through.

---

## Quirk 2 — `hermes gateway start` (system mode) hardcodes the wrong path

**Symptom**: when run under launchd in the system domain, hermes' own
`gateway start` subcommand attempts to load a per-user systemd unit and
exits 1 immediately because that unit does not exist.

**Upstream code path**:
`hermes/hermes_cli/gateway.py:start_gateway` shells out to
`systemctl --user start hermes.service` regardless of platform —
inappropriate on macOS where there is no systemd, and inappropriate
under launchd's system domain on any OS.

**Clawrium mitigation**:
- The plist template uses `hermes gateway run` (foreground, supervisor-
  friendly), not `hermes gateway start`. `gateway run` directly
  bootstraps the FastAPI app in-process, side-stepping the
  systemctl-based start path.
- This matches what configure.yaml already does on Linux (the Linux
  systemd unit is rendered with `ExecStart=...hermes gateway run` too).

**Revert criteria**: upstream removes the systemctl shim or guards it
with a `if which systemctl:` check.

---

## Quirk 3 — `HERMES_HOME` inherits the invoker's `$HOME`, not the user the unit declares

**Symptom**: a launchd unit running as user `h1` ends up reading
`.env` and `config.yaml` from `/Users/xclm/.hermes` because launchctl
inherits the calling shell's `$HOME` when the plist does not set one
explicitly.

**Upstream code path**:
`hermes/hermes_cli/config.py:resolve_hermes_home` falls back to
`os.environ.get("HOME")` when `HERMES_HOME` is unset. Under
`launchctl bootstrap`, `HOME` may not be the agent user's home —
it depends on the calling context. Under `become_user` in Ansible
the same problem manifests during install.

**Clawrium mitigation**:
- `gateway.plist.j2` sets both `HERMES_HOME` and `HOME` explicitly in
  the plist's `EnvironmentVariables` dict, pinning them to
  `/Users/<agent_name>/.hermes` and `/Users/<agent_name>`.
- `install_macos.yaml` exports both vars on the installer
  command's environment so the upstream `install.sh` resolves
  paths against the correct user during install too.
- `core/launchd.py::test_render_plist_paths_target_user_home` asserts
  the rendered plist's env vars match the agent user.

**Revert criteria**: upstream either (a) ignores `$HOME` and derives
`HERMES_HOME` from the launchd unit's `UserName`, or (b) documents the
requirement to set both vars explicitly (in which case this workaround
is no longer a workaround but a documented behaviour).

---

## How to verify the workarounds still hold

After each upstream hermes bump:

```bash
# 1. Plist domain
grep -i "LaunchAgents" src/clawrium/platform/registry/hermes/templates/*.j2
#  (should return nothing)

# 2. ExecStart command
grep -i "gateway start" src/clawrium/platform/registry/hermes/templates/*.j2
#  (should return nothing — we only use `gateway run`)

# 3. HERMES_HOME / HOME in env
python -m clawrium.core.launchd  # (manual smoke; or run the test below)
uv run pytest tests/core/test_launchd.py -v
```

If any of those start failing, either upstream changed behaviour
again, or this workaround was inadvertently broken.
