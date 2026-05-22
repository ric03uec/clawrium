"""Tests for hermes Ansible playbooks (issue #478 phase 2 / #482).

Focus: structure of the dashboard companion unit + extras-install + node
version gate added by the dashboard work. These run as pure YAML parses
so they're fast and do not require a live host.
"""

from importlib.resources import files

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


def test_hermes_install_playbook_discovers_interpreter_from_shebang():
    """We must NOT hard-code the uv venv layout — uv has changed paths
    between releases. Read the interpreter from the binary's shebang."""
    content = _hermes_playbook("install")
    assert "shebang" in content.lower() or "head -n1" in content, (
        "Should resolve interpreter via shebang inspection"
    )
    assert "/.local/bin/hermes" in content


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
