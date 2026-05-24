"""Tests for the zeroclaw agent type registration in the bundled registry.

Parity with tests/test_registry_hermes.py — exercises the install playbook
shape, manifest checksums, run_installation extra_vars, and skip detection
specific to zeroclaw. Added per ATX review of PR #361 (NEW-B2).
"""

from clawrium.core.registry import load_manifest


def test_zeroclaw_manifest_has_installer_checksum():
    """Every platform entry must declare a 64-char hex sha256 and version 0.7.5."""
    manifest = load_manifest("zeroclaw")

    assert len(manifest["platforms"]) == 5, (
        "zeroclaw must publish 5 platform entries (armv7l Debian 13, "
        "aarch64 Ubuntu 22.04/24.04, x86_64 Ubuntu 22.04/24.04)"
    )
    for entry in manifest["platforms"]:
        assert entry["version"] == "0.7.5", (
            f"Platform entry version mismatch: {entry.get('os')} "
            f"{entry.get('os_version')} {entry.get('arch')} -> {entry.get('version')!r}"
        )
        sha256 = entry.get("sha256")
        assert isinstance(sha256, str), (
            f"Platform entry missing sha256: {entry.get('os')} {entry.get('os_version')}"
        )
        assert len(sha256) == 64, (
            f"sha256 must be 64 hex chars, got {len(sha256)}: {sha256!r}"
        )
        # Verify all chars are valid hex
        int(sha256, 16)


def test_zeroclaw_install_playbook_shape():
    """The zeroclaw install playbook must encode the install-disabled invariants."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    playbook_path = zeroclaw_pkg / "playbooks" / "install.yaml"

    content = playbook_path.read_text()

    # Required structural elements.
    assert "- hosts:" in content
    assert "agent_name" in content
    # Agent user is a service account: nologin shell reduces lateral-movement
    # surface if the account is ever compromised.
    assert "shell: /usr/sbin/nologin" in content
    # WorkingDirectory must be inside ~/.zeroclaw (not ~/workspace which is the
    # legacy path; the install playbook now scaffolds ~/.zeroclaw/workspace
    # and ~/.zeroclaw/state).
    assert "WorkingDirectory=/home/{{ agent_name }}/.zeroclaw" in content
    assert "ExecStart=/home/{{ agent_name }}/bin/zeroclaw daemon" in content
    # Workspace + state scaffolding must land inside ~/.zeroclaw.
    assert "/home/{{ agent_name }}/.zeroclaw/workspace" in content
    assert "/home/{{ agent_name }}/.zeroclaw/state" in content
    # Service unit MUST NOT be enabled or started in install.yaml — `clm agent
    # configure` owns the start half of the lifecycle.
    data = yaml.safe_load(content)
    tasks = data[0]["tasks"]
    enable_tasks = [
        t
        for t in tasks
        if t.get("ansible.builtin.systemd", {}).get("enabled") is True
        or t.get("ansible.builtin.systemd", {}).get("state") == "started"
    ]
    assert enable_tasks == [], (
        "install.yaml must not enable or start the zeroclaw service; "
        "configure.yaml owns the start half of the lifecycle"
    )


def test_zeroclaw_start_playbook_uses_argv_list_form():
    """Pin the W9 fix: pgrep in start.yaml MUST use argv-list form, not a
    `cmd:` string. Unquoted agent_name interpolated into a shell-split string
    is a command-injection vector if an agent name ever contains whitespace
    or shell metacharacters."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    start_path = zeroclaw_pkg / "playbooks" / "start.yaml"
    data = yaml.safe_load(start_path.read_text())
    tasks = data[0]["tasks"]

    pgrep_tasks = [
        t
        for t in tasks
        if isinstance(t.get("ansible.builtin.command"), dict)
        and "pgrep" in str(t["ansible.builtin.command"])
    ]
    assert pgrep_tasks, "start.yaml must contain at least one pgrep task"
    for task in pgrep_tasks:
        cmd_block = task["ansible.builtin.command"]
        assert "cmd" not in cmd_block, (
            f"pgrep task '{task.get('name')}' must use argv-list form, not "
            f"cmd: string (W9). Found: {cmd_block!r}"
        )
        assert "argv" in cmd_block, (
            f"pgrep task '{task.get('name')}' must declare argv: list (W9)."
        )
        argv = cmd_block["argv"]
        assert argv[0] == "pgrep"
        # The agent_name token must be a standalone argv element so shell
        # metacharacters in the name cannot split into extra arguments.
        assert "{{ agent_name }}" in argv


def test_zeroclaw_stop_playbook_uses_argv_list_form():
    """Mirror of test_zeroclaw_start_playbook_uses_argv_list_form for stop.yaml."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    stop_path = zeroclaw_pkg / "playbooks" / "stop.yaml"
    data = yaml.safe_load(stop_path.read_text())
    tasks = data[0]["tasks"]

    pgrep_tasks = [
        t
        for t in tasks
        if isinstance(t.get("ansible.builtin.command"), dict)
        and "pgrep" in str(t["ansible.builtin.command"])
    ]
    assert pgrep_tasks, "stop.yaml must contain at least one pgrep task"
    for task in pgrep_tasks:
        cmd_block = task["ansible.builtin.command"]
        assert "cmd" not in cmd_block
        assert "argv" in cmd_block
        assert cmd_block["argv"][0] == "pgrep"
        assert "{{ agent_name }}" in cmd_block["argv"]


def test_zeroclaw_remove_playbook_cleans_workspace_and_state():
    """remove.yaml must clean the unit, ~/.zeroclaw (covers workspace+state),
    the bin directory, and the agent user. Must NOT reference the legacy
    ~/workspace path (NEW-B1)."""
    from importlib.resources import files

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    remove_path = zeroclaw_pkg / "playbooks" / "remove.yaml"
    content = remove_path.read_text()

    assert "/etc/systemd/system/{{ agent_type }}-{{ agent_name }}.service" in content
    # Removing ~/.zeroclaw cascades to workspace + state subdirs.
    assert "/home/{{ agent_name }}/.zeroclaw" in content
    assert "/home/{{ agent_name }}/bin" in content
    assert "remove: yes" in content
    # Legacy ~/workspace must not be referenced — install no longer scaffolds it.
    assert "/home/{{ agent_name }}/workspace" not in content


def _zeroclaw_install_setup(
    monkeypatch, tmp_path, host_record: dict, version: str = "0.7.5"
):
    """Shared setup for zeroclaw install mock tests. Mirrors hermes pattern."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "zeroclaw",
        "entries": [
            {
                "version": version,
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "8bc8276a8d8faefb3e4a824f33876929e7466f632ee7c5363936368a1af2e4f7",
                "requirements": {
                    "min_memory_mb": 1024,
                    "gpu_required": False,
                    "dependencies": {"python": ">=3.9"},
                },
            }
        ],
    }

    import clawrium.core.install

    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)
    monkeypatch.setattr(
        clawrium.core.install,
        "check_compatibility",
        lambda *args, **kwargs: {
            "compatible": True,
            "matched_entry": mock_manifest["entries"][0],
            "reasons": [],
        },
    )

    host_state = [host_record]

    def mock_get_host(_):
        return host_state[0]

    def mock_update_host(_, updater):
        host_state[0] = updater(host_state[0])
        return True

    monkeypatch.setattr(clawrium.core.install, "get_host", mock_get_host)
    monkeypatch.setattr(clawrium.core.install, "update_host", mock_update_host)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")
    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda _: key_file
    )
    monkeypatch.setattr(
        clawrium.core.install, "initialize_onboarding", lambda h, c: True
    )

    return host_state


def _capture_run(captured: list):
    """Mock for ansible_runner.run that captures call kwargs and returns
    a successful result with the recorded events."""

    def _runner(*args, **kwargs):
        captured.append(kwargs)

        class Result:
            status = "successful"

            class Config:
                artifact_dir = "/tmp/nonexistent"

            config = Config()
            events = kwargs.get("_events", [])

        return Result()

    return _runner


def test_zeroclaw_install_passes_correct_extra_vars(monkeypatch, tmp_path):
    """run_installation('zeroclaw', ...) must inject agent_type='zeroclaw',
    claw_version='v0.7.5', and the manifest sha256 into the playbook inventory."""
    from clawrium.core.install import run_installation

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    _zeroclaw_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner

    captured: list = []
    monkeypatch.setattr(ansible_runner, "run", _capture_run(captured))

    result = run_installation("zeroclaw", "test-host", name="zc-test")

    assert result["success"] is True
    assert result["agent"] == "zeroclaw"
    assert result["version"] == "0.7.5"
    # base + claw playbook
    assert len(captured) == 2
    inv_vars = captured[1]["inventory"]["all"]["vars"]
    assert inv_vars["agent_name"] == "zc-test"
    assert inv_vars["agent_type"] == "zeroclaw"
    assert inv_vars["claw_version"] == "v0.7.5"
    assert (
        inv_vars["claw_sha256"]
        == "8bc8276a8d8faefb3e4a824f33876929e7466f632ee7c5363936368a1af2e4f7"
    )
    assert inv_vars["force_install"] is False

    playbook_path = captured[1]["playbook"]
    assert "registry/zeroclaw/playbooks/install.yaml" in playbook_path


def test_install_was_skipped_handles_zeroclaw_fact():
    """The generalized skip detection helper recognizes zeroclaw_already_installed."""
    from clawrium.core.install import _install_was_skipped

    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"zeroclaw_already_installed": True}},
                },
            }
        ]

    assert _install_was_skipped(Result(), "zeroclaw") is True

    # hermes fact does not trigger zeroclaw skip detection.
    class HermesResult:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"hermes_already_installed": True}},
                },
            }
        ]

    assert _install_was_skipped(HermesResult(), "zeroclaw") is False


# ----- Issue #358: workspace + memory CLI wiring -----------------------------


def test_zeroclaw_manifest_declares_memory_feature():
    """features.memory must be true so cli/memory.py routes to zeroclaw playbooks."""
    manifest = load_manifest("zeroclaw")
    features = manifest.get("features", {})
    assert features.get("memory") is True
    workspace = manifest.get("workspace", {})
    assert workspace.get("memory_path") == "~/.zeroclaw/workspace"


def test_zeroclaw_memory_playbooks_exist():
    """All four memory_*.yaml playbooks must ship in the zeroclaw registry."""
    from importlib.resources import files

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    for name in ("memory_read", "memory_write", "memory_delete", "memory_info"):
        assert (zeroclaw_pkg / "playbooks" / f"{name}.yaml").is_file(), (
            f"Missing zeroclaw playbook: {name}.yaml"
        )


def test_zeroclaw_memory_info_lists_seven_personality_files():
    """memory_info must enumerate all 7 personality files (no BOOTSTRAP.md)."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    data = yaml.safe_load((zeroclaw_pkg / "playbooks" / "memory_info.yaml").read_text())
    top = set(data[0]["vars"]["memory_top_level_files"])
    assert top == {
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    }
    # BOOTSTRAP.md must NOT be listed — runtime owns its lifecycle.
    assert "BOOTSTRAP.md" not in top


def test_zeroclaw_memory_playbooks_target_workspace_path():
    """Each memory_*.yaml must point at ~/.zeroclaw/workspace (not legacy paths)."""
    from importlib.resources import files

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    for name in ("memory_read", "memory_write", "memory_delete", "memory_info"):
        content = (zeroclaw_pkg / "playbooks" / f"{name}.yaml").read_text()
        assert "/home/{{ agent_name }}/.zeroclaw/workspace" in content, (
            f"{name}.yaml must use ~/.zeroclaw/workspace"
        )
        # Legacy ~/workspace path must not leak in (mirror of remove.yaml test).
        assert "/home/{{ agent_name }}/workspace" not in content, (
            f"{name}.yaml references legacy ~/workspace path"
        )


def test_zeroclaw_workspace_templates_exist():
    """All 7 workspace MD templates must ship (no BOOTSTRAP.md)."""
    from importlib.resources import files

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    ws = zeroclaw_pkg / "templates" / "workspace"
    expected = {
        "SOUL.md.j2",
        "IDENTITY.md.j2",
        "USER.md.j2",
        "AGENTS.md.j2",
        "TOOLS.md.j2",
        "MEMORY.md.j2",
        "HEARTBEAT.md.j2",
    }
    actual = {p.name for p in ws.iterdir() if p.name.endswith(".j2")}
    assert expected == actual, f"Workspace templates mismatch: {expected ^ actual}"
    # BOOTSTRAP.md MUST NOT be rendered by clm — the runtime generates it
    # on first boot and self-deletes after use.
    assert not (ws / "BOOTSTRAP.md.j2").exists()


def test_zeroclaw_configure_renders_workspace_with_force_no():
    """configure.yaml must render all 7 templates with force: no so a
    subsequent `clm agent configure` run never clobbers user edits."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    data = yaml.safe_load((zeroclaw_pkg / "playbooks" / "configure.yaml").read_text())
    tasks = data[0]["tasks"]
    workspace_renders = [
        t
        for t in tasks
        if isinstance(t.get("ansible.builtin.template"), dict)
        and "/.zeroclaw/workspace/" in t["ansible.builtin.template"].get("dest", "")
    ]
    assert workspace_renders, (
        "configure.yaml must render templates into ~/.zeroclaw/workspace/"
    )
    for task in workspace_renders:
        block = task["ansible.builtin.template"]
        # force: no (Ansible YAML parses `no` as the bool False) preserves
        # user edits across re-configure runs.
        assert block.get("force") is False, (
            f"Workspace template render '{task.get('name')}' missing "
            f"force: no — re-configure would clobber user edits."
        )
        assert block.get("mode") == "0600", (
            f"Workspace template render '{task.get('name')}' must be 0600"
        )
    # All 7 personality files must be in the loop (the task uses `loop:` so
    # check the loop list rather than counting tasks).
    looped = [t for t in workspace_renders if "loop" in t]
    assert looped, "Workspace template task must iterate via `loop:`"
    files_in_loop = set(looped[0]["loop"])
    assert files_in_loop == {
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    }


# ----- ATX iter 5 W3: no_log on memory_delete across all 3 claws -----------


def test_pair_playbook_handles_locked_daemon():
    """Issue #445: zeroclaw v0.7.5's /pair/code returns pairing_code=null
    after the daemon's devices.db has any prior row. The pair handshake
    playbook must (a) not crash on the null (defensive), (b) mint a fresh
    code via POST /api/pairing/initiate using the existing bearer
    (correctness). This is a structural test so the bug cannot regress
    silently.
    """
    from importlib.resources import files
    import yaml

    pkg = files("clawrium.platform.registry.zeroclaw")
    pair_path = pkg / "playbooks" / "tasks" / "pair.yaml"
    raw = pair_path.read_text()
    tasks = yaml.safe_load(raw)
    assert isinstance(tasks, list) and tasks, "pair.yaml must be a task list"

    by_name = {t.get("name", ""): t for t in tasks if isinstance(t, dict)}

    initiate_name = "Mint pairing code via /api/pairing/initiate (locked-pair branch)"
    assert initiate_name in by_name, (
        "pair.yaml must include a task that POSTs to /api/pairing/initiate "
        "for the locked-pair branch"
    )
    initiate = by_name[initiate_name]
    uri = initiate.get("ansible.builtin.uri") or {}
    assert "/api/pairing/initiate" in (uri.get("url") or ""), (
        "initiate task must hit /api/pairing/initiate"
    )
    assert (uri.get("method") or "").upper() == "POST"
    auth_header = (uri.get("headers") or {}).get("Authorization", "")
    assert auth_header.startswith("Bearer "), (
        "initiate must authenticate with a Bearer token from hosts.json"
    )
    assert "config.gateway.auth" in auth_header, (
        "Bearer value must come from config.gateway.auth so both "
        "configure.yaml and restart.yaml can pass it through unchanged"
    )
    assert initiate.get("no_log") is True, (
        "initiate task carries a bearer — must be no_log: true"
    )
    # ATX B2: 401/503 from /api/pairing/initiate must be accepted so the
    # follow-up validate task can produce an actionable operator message
    # rather than a generic Ansible HTTP error.
    accepted = uri.get("status_code")
    if isinstance(accepted, int):
        accepted = [accepted]
    assert set(accepted or []) >= {200, 401, 503}, (
        "initiate task must accept 200, 401, and 503 so the validate task "
        "below can route to actionable messages (ATX B2). Got: {!r}".format(
            uri.get("status_code")
        )
    )

    when_clause = initiate.get("when")
    if isinstance(when_clause, list):
        when_text = " AND ".join(str(c) for c in when_clause)
    else:
        when_text = str(when_clause)
    assert "pairing_code is none" in when_text, (
        "initiate must fire only when /pair/code returned a null code "
        "(locked daemon); current when: {!r}".format(when_clause)
    )
    # ATX W4: the initiate task also needs the `is defined` guard so a
    # network error on GET /pair/code (which leaves pair_code_response.json
    # undefined) doesn't crash the `is none` check below.
    assert "pair_code_response.json is defined" in when_text, (
        "initiate task's when: clause must include "
        "`pair_code_response.json is defined` so a /pair/code network error "
        "fails the prior task cleanly rather than crashing this one's "
        "is-none check (ATX W4)."
    )

    # ATX B2: validate task that routes 401/503 to operator-actionable
    # messages must exist downstream of the initiate task.
    validate_name = "Validate locked-branch initiate response"
    assert validate_name in by_name, (
        "pair.yaml must include a task that surfaces 401/503 from "
        "/api/pairing/initiate as actionable messages (ATX B2)"
    )
    validate_task = by_name[validate_name]
    validate_msg = (validate_task.get("ansible.builtin.fail") or {}).get("msg", "")
    assert "clawctl agent configure" in validate_msg, (
        "401 path must direct the operator to `clawctl agent configure` (ATX B2)"
    )
    assert "journalctl" in validate_msg, (
        "503 path must direct the operator to daemon logs (ATX B2)"
    )
    # ATX iter-3 NB2: validate task MUST NOT be no_log: true. The
    # lifecycle.py censored-event handler (W1) skips events where
    # res.censored is set, which would silently swallow the operator
    # guidance this msg encodes. The msg references only safe scalars
    # (initiate_response.status as int, agent_name/agent_type strings).
    # The msg's WARNING comment in pair.yaml pins this contract for
    # future editors.
    assert validate_task.get("no_log") is not True, (
        "validate task must NOT be no_log: true — would defeat the W1 "
        "censored-event handler and silently suppress the 401/503 "
        "operator guidance this task encodes (ATX iter-3 NB2)"
    )

    # ATX iter-2 NW3: substring-on-raw-template is fragile — render the
    # Jinja2 msg against fixture statuses and assert each branch produces
    # the expected operator-actionable text. A regression that swaps the
    # 401/503 branches or drops one would slip past the substring check
    # above but fails here.
    from jinja2 import Environment

    env = Environment()
    msg_template = env.from_string(validate_msg)
    rendered_401 = " ".join(
        msg_template.render(
            initiate_response={"status": 401},
            agent_name="zer-test",
            agent_type="zeroclaw",
        ).split()
    )
    assert "401" in rendered_401
    # ATX iter-3 NW7: require BOTH discriminating phrases in the 401
    # branch so a rephrasing that drops one doesn't silently lose
    # specificity. Same constraint applies to cross-leak: BOTH must be
    # absent from the 503 render.
    assert "stale" in rendered_401, (
        "401 branch must explicitly say 'stale' so the operator knows the "
        "bearer is the problem (iter-3 NW7)"
    )
    assert "devices.db" in rendered_401, (
        "401 branch must name devices.db so the operator knows where to "
        "look on the host (iter-3 NW7)"
    )
    assert "clawctl agent configure zer-test" in rendered_401

    rendered_503 = " ".join(
        msg_template.render(
            initiate_response={"status": 503},
            agent_name="zer-test",
            agent_type="zeroclaw",
        ).split()
    )
    assert "503" in rendered_503
    # 503 branch's discriminating phrases. Both required.
    assert "journalctl" in rendered_503, (
        "503 branch must direct operator to daemon logs (iter-3 NW7)"
    )
    assert "pairing disabled" in rendered_503 or "unavailable" in rendered_503, (
        "503 branch must explain why the daemon refused (iter-3 NW7)"
    )
    assert "clawctl agent configure zer-test" in rendered_503

    # NW7 cross-leak: BOTH 401 phrases absent from 503, BOTH 503 phrases
    # absent from 401. A swapped branch would fail one of these four.
    assert "stale" not in rendered_503 and "devices.db" not in rendered_503, (
        "401 branch's bearer-staleness guidance leaked into 503 render (iter-3 NW7)"
    )
    assert (
        "pairing disabled" not in rendered_401 and "unavailable" not in rendered_401
    ), "503 branch's daemon-availability guidance leaked into 401 render (iter-3 NW7)"
    assert "journalctl" not in rendered_401, (
        "401 branch must not also include 503's journalctl guidance"
    )

    # Defensive: every `| length` check on a pair field must coexist with
    # an `is none` guard in the same `when:` clause, so the filter never
    # sees a null and crashes with `NoneType has no len()` (the literal
    # error #445 fixes).
    fields_under_check = (
        "pair_response.json.token",
        "resolved_pairing_code",
    )
    when_clauses = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        clause = task.get("when")
        if clause is None:
            continue
        # `when:` may be a string or a list. Normalize to a single string
        # so multi-line `or`-chains (which YAML joins with a space) are
        # searchable as one blob.
        if isinstance(clause, list):
            when_clauses.append(" ".join(str(c) for c in clause))
        else:
            when_clauses.append(str(clause))

    for field in fields_under_check:
        guarded = any(
            f"{field} | length" in w and f"{field} is none" in w for w in when_clauses
        )
        assert guarded, (
            f"`{field} | length` must coexist with `{field} is none` in "
            f"the same when: clause; otherwise a defined-but-null daemon "
            f"response will crash the filter (issue #445)."
        )


def test_pair_playbook_resolved_code_ternary_picks_correct_source():
    """ATX B3: structural shape isn't enough — the `resolved_pairing_code`
    set_fact ternary in pair.yaml is the correctness core of #445. Evaluate
    its Jinja2 expression directly against the two production-relevant
    states and assert the right source is picked. A reversed ternary (the
    obvious typo) passes the existing structural test but fails this one.
    """
    from importlib.resources import files
    import yaml
    from jinja2 import Environment

    pkg = files("clawrium.platform.registry.zeroclaw")
    tasks = yaml.safe_load((pkg / "playbooks" / "tasks" / "pair.yaml").read_text())
    by_name = {t.get("name", ""): t for t in tasks if isinstance(t, dict)}
    set_fact_task = by_name.get(
        "Resolve pairing code from whichever branch produced one"
    )
    assert set_fact_task is not None, (
        "pair.yaml must contain the resolve-source set_fact task"
    )
    expr = (set_fact_task.get("ansible.builtin.set_fact") or {}).get(
        "resolved_pairing_code"
    )
    assert isinstance(expr, str) and expr.strip(), (
        "set_fact must declare a non-empty resolved_pairing_code expression"
    )

    env = Environment()
    template = env.from_string(expr)

    # Fresh-boot branch: /pair/code returned a real code, initiate never
    # ran (undefined). Resolved must be the /pair/code value.
    fresh = template.render(
        pair_code_response={"json": {"pairing_code": "FRESH1"}},
    ).strip()
    assert fresh == "FRESH1", (
        f"fresh-boot branch must yield /pair/code's value; got {fresh!r}. "
        f"This catches a reversed ternary that would silently send the "
        f"empty/undefined initiate value to /pair on first install."
    )

    # Locked branch: /pair/code returned null, initiate minted a fresh code.
    # Resolved must be the initiate value, not the null from /pair/code.
    locked = template.render(
        pair_code_response={"json": {"pairing_code": None}},
        initiate_response={"json": {"pairing_code": "LOCKD2"}},
    ).strip()
    assert locked == "LOCKD2", (
        f"locked-pair branch must yield /api/pairing/initiate's value; "
        f"got {locked!r}. A reversed ternary would pick the null from "
        f"/pair/code and the downstream /pair POST would crash."
    )


def test_memory_delete_no_log_on_delete_task_across_all_claws():
    """ATX iter 5 W3: every claw's memory_delete playbook must mark the
    file-removal task no_log: true so an Ansible run at -vvv does not
    echo agent_name + per-file path back into runner artifacts. Pin the
    invariant structurally across all 3 memory-capable claws."""
    from importlib.resources import files
    import yaml

    for claw_type in ("zeroclaw", "openclaw", "hermes"):
        pkg = files(f"clawrium.platform.registry.{claw_type}")
        data = yaml.safe_load((pkg / "playbooks" / "memory_delete.yaml").read_text())
        tasks = data[0]["tasks"]
        delete_tasks = [
            t
            for t in tasks
            if isinstance(t.get("ansible.builtin.file"), dict)
            and t["ansible.builtin.file"].get("state") == "absent"
        ]
        assert delete_tasks, f"{claw_type}/memory_delete.yaml: no delete task found"
        for task in delete_tasks:
            assert task.get("no_log") is True, (
                f"{claw_type}/memory_delete.yaml task '{task.get('name')}' "
                f"must have no_log: true so secret-bearing paths are not "
                f"echoed in ansible-runner artifacts."
            )
