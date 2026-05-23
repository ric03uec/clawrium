"""Tests for hermes Ansible playbooks (issue #478 phase 2 / #482).

Focus: structure of the dashboard companion unit + extras-install + node
version gate added by the dashboard work. These run as pure YAML parses
so they're fast and do not require a live host.
"""

from importlib.resources import files

import pytest
import yaml


def _hermes_playbook(name: str) -> str:
    path = files("clawrium.platform.registry.hermes") / "playbooks" / f"{name}.yaml"
    return path.read_text()


def _tasks(playbook_text: str) -> list[dict]:
    data = yaml.safe_load(playbook_text)
    assert isinstance(data, list) and data, "Playbook must be a non-empty list"
    return data[0].get("tasks", []) or []


def test_hermes_install_playbook_has_extras_install_task():
    """Phase 2 must install the [web,pty] extras into the upstream hermes
    interpreter so `hermes dashboard` resolves."""
    content = _hermes_playbook("install")
    assert "hermes-agent[web,pty]" in content, (
        "install.yaml must install the web+pty extras"
    )
    tasks = _tasks(content)
    names = [t.get("name", "") for t in tasks]
    assert any("extras" in n.lower() for n in names), (
        "Should have a dedicated extras-install task"
    )


def _task_module_value(task: dict, *module_keys: str):
    """Return the value of whichever of `module_keys` is present on the task.

    Handles both FQCN (`ansible.builtin.shell`) and short (`shell`) forms.
    """
    for k in module_keys:
        if k in task:
            return task[k]
    return None


def test_install_playbook_pipefail_uses_bash_executable():
    """Every `shell:` task that uses `set -o pipefail` must declare
    `args.executable: /bin/bash`.

    Ansible's `shell:` defaults to `/bin/sh`. On Ubuntu (and any Debian-
    derived image), `/bin/sh` is dash, which does not support `set -o
    pipefail`. Without an explicit executable override, the task crashes
    at the FIRST line with:

        /bin/sh: 1: set: Illegal option -o pipefail

    Regression anchor for the bug that crashed `clm agent install
    --force` for hermes on wolf-i.
    """
    tasks = _tasks(_hermes_playbook("install"))
    offenders = []
    for t in tasks:
        cmd = _task_module_value(t, "ansible.builtin.shell", "shell")
        if not isinstance(cmd, str) or "pipefail" not in cmd:
            continue
        args = t.get("args") or {}
        if args.get("executable") != "/bin/bash":
            offenders.append(t.get("name", "<unnamed>"))
    assert not offenders, (
        f"Shell tasks using `set -o pipefail` but missing "
        f"args.executable: /bin/bash (will crash on dash): {offenders}"
    )


def test_install_playbook_resolves_venv_interpreter_directly():
    """`hermes_interpreter` MUST be resolved by stat-ing the known venv
    path, NOT by parsing the shebang of `~/.local/bin/hermes`.

    The launcher at `/home/<agent>/.local/bin/hermes` is a 4-line bash
    wrapper (verified by reading the file on a live install). Its
    shebang is `#!/usr/bin/env bash` — parsing it yields `/usr/bin/env`
    or `bash`, neither of which can be invoked as `-m pip`.

    The real interpreter is at a stable, hermes-installer-defined path:
    `/home/<agent>/.hermes/code/venv/bin/python3`. Resolve it via
    `set_fact` + `stat`, fail loudly if the venv is missing.
    """
    tasks = _tasks(_hermes_playbook("install"))
    names = [t.get("name", "") for t in tasks]

    # Must NOT keep the shebang-parsing approach.
    assert not any("shebang" in n.lower() for n in names), (
        "Shebang-parsing approach must be removed; the launcher is a "
        f"bash wrapper, not a python script. Offending tasks: "
        f"{[n for n in names if 'shebang' in n.lower()]}"
    )

    expected_path = (
        "/home/{{ agent_name }}/.hermes/code/venv/bin/python3"
    )
    set_fact_task = next(
        (
            t for t in tasks
            if isinstance(
                _task_module_value(t, "ansible.builtin.set_fact", "set_fact"),
                dict,
            )
            and (
                _task_module_value(
                    t, "ansible.builtin.set_fact", "set_fact"
                ).get("hermes_interpreter")
                == expected_path
            )
        ),
        None,
    )
    assert set_fact_task is not None, (
        f"Expected a set_fact task assigning "
        f"hermes_interpreter = {expected_path!r}; not found. "
        f"Task names present: {names}"
    )

    # And a stat + fail pair must guard against a missing venv.
    stat_targets = [
        (_task_module_value(t, "ansible.builtin.stat", "stat") or {}).get("path")
        for t in tasks
    ]
    assert "{{ hermes_interpreter }}" in stat_targets, (
        "Missing `stat: path: {{ hermes_interpreter }}` guard."
    )


def test_install_playbook_extras_install_is_editable_from_source_checkout():
    """The `[web,pty]` extras must be installed via `uv pip install
    --editable <source-checkout>[web,pty]`, NOT a non-editable PyPI
    install of `hermes-agent[web,pty]`.

    Hermes upstream resolves `PROJECT_ROOT` as
    `Path(__file__).parent.parent.resolve()` in `web_server.py`,
    `main.py`, `gateway.py`, and `cron.py`. With an editable install,
    `__file__` lives in `/home/<agent>/.hermes/code/hermes_cli/...`
    and `PROJECT_ROOT` correctly resolves to the source checkout
    (where `ui-tui/`, `web/`, `scripts/`, `pyproject.toml` actually
    live). A non-editable PyPI install lands `__file__` inside
    site-packages, so `PROJECT_ROOT / "ui-tui"` resolves to a
    non-existent path and the dashboard's chat-sidebar WebSocket
    endpoint crashes with FileNotFoundError on /pty_ws.

    Additional requirements:
    - `uv pip install` (not `python -m pip install`) — the upstream
      installer builds the venv with uv, which doesn't ship pip.
    - `--python {{ hermes_interpreter }}` to target the correct venv
      without relying on activate scripts or VIRTUAL_ENV exports.
    - Path-form spec `/home/{{ agent_name }}/.hermes/code[web,pty]`,
      not the PyPI name `hermes-agent[web,pty]` (which would pull a
      fresh non-editable copy and overwrite the editable install
      that upstream's own installer set up).
    - No `--upgrade` flag — `--editable` is a different operation
      (re-point to source) and `--upgrade` would only matter for
      PyPI installs.

    Regression anchor for the chat-sidebar bug surfaced after
    `clm agent install --force` on maurice@wolf-i.
    """
    tasks = _tasks(_hermes_playbook("install"))
    extras_task = next(
        (
            t for t in tasks
            if "[web,pty]" in str(
                _task_module_value(t, "ansible.builtin.command", "command")
            )
        ),
        None,
    )
    assert extras_task is not None, "No task installing the [web,pty] extras"
    cmd_value = _task_module_value(
        extras_task, "ansible.builtin.command", "command"
    )
    argv = cmd_value.get("argv", []) if isinstance(cmd_value, dict) else []

    assert argv[:3] == ["uv", "pip", "install"], (
        f"Extras install must invoke `uv pip install`, not `python -m pip`. "
        f"Got argv[:3] = {argv[:3]!r}"
    )
    assert "--python" in argv, "Must target the venv via --python"
    py_idx = argv.index("--python")
    assert argv[py_idx + 1] == "{{ hermes_interpreter }}", (
        f"--python must be followed by '{{{{ hermes_interpreter }}}}'; "
        f"got {argv[py_idx + 1]!r}"
    )
    assert "--editable" in argv, (
        "Extras install must use --editable so PROJECT_ROOT inside "
        "hermes_cli resolves to the source checkout (not site-packages). "
        f"Got argv = {argv!r}"
    )
    assert "--upgrade" not in argv, (
        "Drop --upgrade; --editable is the operation we want."
    )
    assert "hermes-agent[web,pty]" not in argv, (
        "Do not install from PyPI name `hermes-agent[web,pty]` — that "
        "would land a non-editable copy in site-packages and overwrite "
        "the editable install the upstream installer set up."
    )
    source_specs = [
        a for a in argv
        if a.startswith("/home/{{ agent_name }}/.hermes/code")
        and a.endswith("[web,pty]")
    ]
    assert source_specs, (
        "argv must contain a path-form spec "
        "'/home/{{ agent_name }}/.hermes/code[web,pty]' to install "
        f"editable from the source checkout. Got argv = {argv!r}"
    )


def test_hermes_install_playbook_verifies_node_version():
    """Node >= 18 is required for the dashboard SPA build."""
    content = _hermes_playbook("install")
    tasks = _tasks(content)
    names = [t.get("name", "") for t in tasks]
    assert any("node" in n.lower() and "18" in n for n in names), (
        "Should fail loudly if Node.js < 18"
    )
    # Remediation must be visible to the operator, not just a stack trace.
    assert "apt install" in content or "nodesource" in content


def test_hermes_install_playbook_creates_dashboard_unit():
    """Dashboard companion unit must be dropped at install time with the
    expected systemd directives so PartOf propagation works."""
    content = _hermes_playbook("install")

    assert (
        "/etc/systemd/system/{{ agent_type }}-dashboard-{{ agent_name }}.service"
        in content
    ), "Dashboard unit file path"
    assert "PartOf={{ agent_type }}-{{ agent_name }}.service" in content
    # ATX W1: `Also=` lives on the gateway unit, not the dashboard unit
    # — see install.yaml comment for why. Confirm the dashboard side
    # does NOT carry an `Also=` to the gateway (which would be the
    # silent-disable footgun).
    assert "Also={{ agent_type }}-dashboard-{{ agent_name }}.service" in content, (
        "Gateway unit must carry `Also=<dashboard>` so enabling the gateway "
        "also enables the companion"
    )
    assert "Also={{ agent_type }}-{{ agent_name }}.service" not in content, (
        "Dashboard unit must NOT carry `Also=<gateway>` — that would let "
        "`systemctl disable dashboard` silently disable the gateway"
    )
    assert "Environment=HERMES_DASHBOARD_TUI=1" in content
    assert "hermes dashboard --host 127.0.0.1" in content
    assert "--port {{ dashboard_port }}" in content
    assert "--no-open" in content
    assert "--tui" in content


def test_hermes_install_playbook_dashboard_unit_uses_loopback_only():
    """The dashboard MUST bind to loopback only — the SSH tunnel is the auth
    boundary. A 0.0.0.0 bind would expose it to the LAN unauthenticated."""
    content = _hermes_playbook("install")
    # The exact substring "0.0.0.0" appears elsewhere (api_server) so just
    # check the dashboard ExecStart line uses 127.0.0.1.
    assert "hermes dashboard --host 127.0.0.1" in content


def test_hermes_start_playbook_starts_and_enables_dashboard_unit():
    content = _hermes_playbook("start")
    tasks = _tasks(content)
    names = [t.get("name", "") for t in tasks]
    assert any(
        "dashboard" in n.lower() and "start" in n.lower() for n in names
    ), "start.yaml must start the dashboard unit"
    # The unit name string the systemd module operates on:
    assert "{{ agent_type }}-dashboard-{{ agent_name }}" in content


def test_hermes_start_playbook_resyncs_dashboard_unit_with_port():
    """On every start we re-render the dashboard unit (idempotent) so a
    clm upgrade that changes the ExecStart shape is picked up without a
    full re-install. The render needs `dashboard_port`."""
    content = _hermes_playbook("start")
    assert "Sync dashboard systemd service file" in content
    assert "--port {{ dashboard_port }}" in content
    assert "PartOf={{ agent_type }}-{{ agent_name }}.service" in content


def test_hermes_stop_playbook_stops_dashboard_unit():
    content = _hermes_playbook("stop")
    tasks = _tasks(content)
    names = [t.get("name", "") for t in tasks]
    assert any(
        "dashboard" in n.lower() and "stop" in n.lower() for n in names
    ), "stop.yaml must stop the dashboard unit"
    assert "{{ agent_type }}-dashboard-{{ agent_name }}" in content


def test_hermes_stop_playbook_orders_dashboard_before_gateway():
    """ATX W10: stop.yaml's own comment calls 'Stop dashboard FIRST' a
    load-bearing design (in-flight requests must complete against a live
    gateway). The order is a real invariant — pin it."""
    content = _hermes_playbook("stop")
    tasks = _tasks(content)
    names = [t.get("name", "") for t in tasks]

    def _find(predicate) -> int:
        for i, n in enumerate(names):
            if predicate(n):
                return i
        return -1

    dashboard_stop_idx = _find(
        lambda n: "dashboard" in n.lower() and "stop" in n.lower()
        and "gracefully" in n.lower()
    )
    gateway_stop_idx = _find(
        lambda n: "stop" in n.lower()
        and "gracefully" in n.lower()
        and "dashboard" not in n.lower()
    )
    assert dashboard_stop_idx >= 0, "no graceful dashboard-stop task found"
    assert gateway_stop_idx >= 0, "no graceful gateway-stop task found"
    assert dashboard_stop_idx < gateway_stop_idx, (
        f"dashboard stop (idx {dashboard_stop_idx}) must precede "
        f"gateway stop (idx {gateway_stop_idx})"
    )


def test_hermes_remove_playbook_removes_dashboard_unit():
    content = _hermes_playbook("remove")
    assert (
        "/etc/systemd/system/{{ agent_type }}-dashboard-{{ agent_name }}.service"
        in content
    )
    tasks = _tasks(content)
    names = [t.get("name", "") for t in tasks]
    assert any(
        "dashboard" in n.lower() and "remove" in n.lower() for n in names
    ), "remove.yaml must remove the dashboard unit file"


# ---------------------------------------------------------------------------
# Issue #490 — chat-WS pre-build workaround
#
# Regression anchors for the install-time mitigation against two upstream
# NousResearch/hermes-agent v2026.5.7 defects:
#   A. `_hermes_ink_bundle_stale` looks for `ink-bundle.js`, but the build
#      script only produces `entry-exports.js` — staleness check is
#      permanently True.
#   B. `_make_tui_argv` runs synchronous `subprocess.run([npm, "run",
#      "build"])` after `await ws.accept()`, blocking the asyncio loop and
#      preventing the WS handshake response from reaching the client.
#
# Until upstream lands fixes, the install playbook pre-builds the TUI
# bundle, creates the missing `ink-bundle.js` alias, and bumps mtimes so
# both staleness checks resolve to False.
# ---------------------------------------------------------------------------


_UI_TUI_DIR = "/home/{{ agent_name }}/.hermes/code/ui-tui"
_INK_DIST = f"{_UI_TUI_DIR}/packages/hermes-ink/dist"


def _find_task_by_chdir(tasks: list[dict], chdir: str, cmd_contains: str):
    """Return the first command-module task whose `cmd` contains
    `cmd_contains` and whose `chdir` matches."""
    for t in tasks:
        cmd_value = _task_module_value(
            t, "ansible.builtin.command", "command"
        )
        if not isinstance(cmd_value, dict):
            continue
        if cmd_value.get("chdir") != chdir:
            continue
        if cmd_contains in str(cmd_value.get("cmd", "")):
            return t
    return None


def test_install_playbook_pre_builds_ui_tui_node_deps():
    """`npm install` must run at install time in `ui-tui/`.

    Pre-installing is half of the workaround for upstream defect B
    (sync subprocess in async handler) — the runtime path in
    `_make_tui_argv` would otherwise lazy-install on first WS request
    and block the asyncio event loop.
    """
    tasks = _tasks(_hermes_playbook("install"))
    task = _find_task_by_chdir(tasks, _UI_TUI_DIR, "npm install")
    assert task is not None, (
        "Missing `npm install` task with chdir = "
        f"{_UI_TUI_DIR!r}. Required so `_make_tui_argv` doesn't lazy-"
        "install at WS handshake time."
    )
    assert task.get("become_user") == "{{ agent_name }}", (
        "npm install must run as the agent user so node_modules is "
        "owned correctly."
    )
    env = task.get("environment") or {}
    assert env.get("CI") == "1", (
        "Set CI=1 so npm doesn't drop into interactive prompts on a "
        "headless host."
    )


def test_install_playbook_pre_builds_ui_tui_bundle():
    """`npm run build` must run at install time in `ui-tui/`.

    This produces `dist/entry.js` + `packages/hermes-ink/dist/
    entry-exports.js` so the dashboard's `_make_tui_argv` finds them
    fresh on first chat WS request and skips the build branch
    entirely (workaround for upstream defect B).
    """
    tasks = _tasks(_hermes_playbook("install"))
    task = _find_task_by_chdir(tasks, _UI_TUI_DIR, "npm run build")
    assert task is not None, (
        "Missing `npm run build` task with chdir = "
        f"{_UI_TUI_DIR!r}."
    )
    assert task.get("become_user") == "{{ agent_name }}", (
        "npm run build must run as the agent user."
    )


def test_install_playbook_aliases_entry_exports_to_ink_bundle():
    """Workaround for upstream defect A (filename drift): the
    hermes-ink build script writes `entry-exports.js`, but
    `_hermes_ink_bundle_stale` checks for `ink-bundle.js`. Copy the
    one to the other so the check finds what it's looking for.
    """
    tasks = _tasks(_hermes_playbook("install"))
    src_path = f"{_INK_DIST}/entry-exports.js"
    dest_path = f"{_INK_DIST}/ink-bundle.js"
    task = next(
        (
            t for t in tasks
            if isinstance(
                _task_module_value(t, "ansible.builtin.copy", "copy"), dict,
            )
            and _task_module_value(t, "ansible.builtin.copy", "copy").get(
                "src"
            ) == src_path
            and _task_module_value(t, "ansible.builtin.copy", "copy").get(
                "dest"
            ) == dest_path
        ),
        None,
    )
    assert task is not None, (
        f"Missing copy task aliasing {src_path!r} -> {dest_path!r}. "
        "This is the upstream-filename-drift workaround for defect A "
        "(hermes_cli/main.py:_hermes_ink_bundle_stale checks for "
        "ink-bundle.js but the build script emits entry-exports.js)."
    )
    copy_args = _task_module_value(task, "ansible.builtin.copy", "copy")
    assert copy_args.get("remote_src") is True, (
        "Must set remote_src: true — both files live on the agent host, "
        "not on the controller."
    )


def test_install_playbook_touches_ink_bundle_and_entry_js():
    """Both `ink-bundle.js` and `dist/entry.js` must be touched at the
    end of install so:
      - `_hermes_ink_bundle_stale` sees a non-stale bundle (its mtime
        is newer than any source file in packages/hermes-ink/).
      - `_tui_build_needed` sees `dist/entry.js` newer than every
        `.ts/.tsx` source + package.json/-lock.json/tsconfig*.json
        meta file in ui-tui/.
    """
    tasks = _tasks(_hermes_playbook("install"))
    targets = {
        f"{_INK_DIST}/ink-bundle.js",
        f"{_UI_TUI_DIR}/dist/entry.js",
    }
    touched: set[str] = set()
    for t in tasks:
        file_args = _task_module_value(t, "ansible.builtin.file", "file")
        if not isinstance(file_args, dict):
            continue
        if file_args.get("state") != "touch":
            continue
        path = file_args.get("path")
        if path in targets:
            touched.add(path)
    missing = targets - touched
    assert not missing, (
        f"Missing touch (state: touch) tasks for: {sorted(missing)}. "
        "Without these mtime bumps, _tui_build_needed and "
        "_hermes_ink_bundle_stale return True on first chat WS request "
        "and the asyncio loop blocks on `npm run build`."
    )


def test_install_playbook_prebuild_tasks_are_ordered():
    """ATX B1: the five pre-build tasks have a hard runtime dependency
    chain — reordering keeps existence-only assertions green while the
    playbook fails at runtime (`copy: src entry-exports.js not found`;
    esbuild: missing node_modules). Pin the order.

        npm install
          → npm run build
            → copy entry-exports.js -> ink-bundle.js
              → touch ink-bundle.js
              → touch dist/entry.js
    """
    tasks = _tasks(_hermes_playbook("install"))
    names = [t.get("name", "") for t in tasks]

    def _find(predicate) -> int:
        for i, n in enumerate(names):
            if predicate(n):
                return i
        return -1

    npm_install_idx = _find(lambda n: "Install ui-tui Node dependencies" in n)
    npm_build_idx = _find(lambda n: "Pre-build ui-tui bundle" in n)
    copy_alias_idx = _find(lambda n: "Alias entry-exports.js to ink-bundle.js" in n)
    touch_ink_idx = _find(lambda n: "Touch ink-bundle.js" in n)
    touch_entry_idx = _find(lambda n: "Touch ui-tui/dist/entry.js" in n)

    assert npm_install_idx >= 0, "missing `npm install` task"
    assert npm_build_idx >= 0, "missing `npm run build` task"
    assert copy_alias_idx >= 0, "missing entry-exports.js -> ink-bundle.js alias"
    assert touch_ink_idx >= 0, "missing touch ink-bundle.js task"
    assert touch_entry_idx >= 0, "missing touch dist/entry.js task"

    assert npm_install_idx < npm_build_idx, (
        f"`npm install` (idx {npm_install_idx}) must precede `npm run build` "
        f"(idx {npm_build_idx}) — esbuild needs node_modules."
    )
    assert npm_build_idx < copy_alias_idx, (
        f"`npm run build` (idx {npm_build_idx}) must precede the alias copy "
        f"(idx {copy_alias_idx}) — entry-exports.js doesn't exist until "
        f"build completes."
    )
    assert copy_alias_idx < touch_ink_idx, (
        f"alias copy (idx {copy_alias_idx}) must precede touch of ink-bundle.js "
        f"(idx {touch_ink_idx}) — touching a non-existent file would create "
        f"an empty placeholder."
    )
    assert copy_alias_idx < touch_entry_idx, (
        f"alias copy (idx {copy_alias_idx}) must precede touch of dist/entry.js "
        f"(idx {touch_entry_idx}) — touches close the pre-build block and "
        f"must come last."
    )


@pytest.mark.parametrize("playbook", ["install", "start", "configure"])
def test_hermes_gateway_unit_has_path_in_environment(playbook):
    """All three playbooks that render the hermes gateway systemd unit MUST
    include `Environment=PATH=/home/{{ agent_name }}/.local/bin:...`.

    The hermes kanban dispatcher calls `subprocess.run(["hermes", ...])` with
    a bare-name PATH lookup. systemd's default service PATH does not include
    `~/.local/bin` where the hermes CLI shim lives, so spawns fail and cards
    are parked in `gave_up` after 2 retries. The unit must inject PATH so the
    dispatcher (and any other bare-name subprocess) can resolve `hermes`.

    Drift between install/start/configure has already been observed
    (After=network-online.target, StandardOutput=journal exist only in
    configure). This test anchors the PATH line in all three to prevent
    silently dropping it from one.
    """
    content = _hermes_playbook(playbook)
    assert (
        "Environment=PATH=/home/{{ agent_name }}/.local/bin:" in content
    ), (
        f"{playbook}.yaml gateway unit must declare "
        f"Environment=PATH=/home/{{{{ agent_name }}}}/.local/bin:... so the "
        f"kanban dispatcher's `subprocess.run(['hermes',...])` bare PATH "
        f"lookup resolves the hermes CLI shim."
    )
