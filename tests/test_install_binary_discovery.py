"""Static YAML-structure tests for the openclaw `install` playbook.

Mirrors `test_start_binary_discovery.py` for `install.yaml`. Round 2 ATX
review flagged that the install playbook's #305 changes (W2 executable+size
guard in Resolve, W4 validator on the resolved variable, the ExecStart-change
restart task, and the B1 `creates:` removal) were entirely unguarded by tests.

Running real ansible isn't feasible in unit tests, but the relevant properties
are statically expressible from the playbook structure.
"""

from pathlib import Path

import pytest
import yaml


INSTALL_PLAYBOOK = (
    Path(__file__).parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "openclaw"
    / "playbooks"
    / "install.yaml"
)

PER_AGENT_CONCAT = "'/home/' ~ agent_name ~ '/.openclaw/bin/openclaw'"


@pytest.fixture(scope="module")
def install_tasks() -> list[dict]:
    play = yaml.safe_load(INSTALL_PLAYBOOK.read_text())
    assert isinstance(play, list) and len(play) == 1, (
        "install.yaml must be a single play"
    )
    tasks = play[0].get("tasks", [])
    assert tasks, "install.yaml must declare tasks"
    return tasks


def _task_by_name(tasks: list[dict], name: str) -> dict | None:
    return next((t for t in tasks if t.get("name") == name), None)


def _index_by_name(tasks: list[dict], name: str) -> int:
    return next(i for i, t in enumerate(tasks) if t.get("name") == name)


def test_install_resolve_rejects_non_executable_per_agent_binary(
    install_tasks: list[dict],
) -> None:
    """W2 — per-agent branch must require stat.executable AND stat.size > 0.

    A zero-byte or non-executable file (e.g. crashed mid-flight install) must
    NOT silently become the runtime binary — that produces an ExecStart that
    crash-loops under systemd's Restart=always.
    """
    resolve = _task_by_name(
        install_tasks,
        "Resolve openclaw binary (per-agent preferred, PATH fallback)",
    )
    assert resolve is not None
    set_fact = resolve.get("ansible.builtin.set_fact") or resolve.get("set_fact")
    assert set_fact is not None
    expr = set_fact["openclaw_discovered_binary"]

    # All three predicates must appear in the per-agent branch guard.
    assert "openclaw_per_agent_stat.stat.exists" in expr
    assert "openclaw_per_agent_stat.stat.executable" in expr
    assert "openclaw_per_agent_stat.stat.size" in expr
    # And the per-agent path must come before the `which` fallback in the
    # conditional — otherwise PATH wins and the discovery convergence breaks.
    assert PER_AGENT_CONCAT in expr
    assert expr.index("openclaw_per_agent_stat.stat.exists") < expr.index(
        "openclaw_which_result.stdout"
    )


def test_install_validator_runs_on_resolved_variable(
    install_tasks: list[dict],
) -> None:
    """Round 2 B1 — validator must run on `openclaw_discovered_binary`
    (the resolved variable, which is what propagates to ExecStart), NOT on
    `openclaw_which_result.stdout` (the raw PATH discovery).

    The earlier W4 fix (gate validator on `not stat.exists`) is REJECTED: it
    let a non-executable per-agent file fall back to an unvalidated PATH
    binary that then reached ExecStart unchecked.
    """
    validate = _task_by_name(install_tasks, "Validate discovered binary path")
    assert validate is not None
    when = validate["when"]

    # Must check the resolved variable, not the raw which result.
    assert "openclaw_discovered_binary" in when
    assert "openclaw_which_result.stdout" not in when

    # Must NOT be gated on stat.exists — that's the regressed behavior.
    assert "not openclaw_per_agent_stat.stat.exists" not in when

    # Allowlist content present.
    for allowed in ("/usr/local/bin/", "/usr/bin/", "/home/"):
        assert allowed in when, f"Allowlist missing prefix {allowed!r}"

    # Must be a fail task (debug wouldn't stop the playbook).
    assert (
        validate.get("ansible.builtin.fail") is not None
        or validate.get("fail") is not None
    )


def test_install_discovery_task_ordering(install_tasks: list[dict]) -> None:
    """Required order: stat → which → resolve → validate → version-check.

    Resolve must run before Validate (the validator reads the resolved fact).
    Version-check must run after Validate (otherwise an unsafe PATH binary
    would be invoked with `--version` before the safety check).
    """
    stat_idx = _index_by_name(install_tasks, "Check per-agent openclaw binary")
    which_idx = _index_by_name(install_tasks, "Discover openclaw binary in PATH")
    resolve_idx = _index_by_name(
        install_tasks, "Resolve openclaw binary (per-agent preferred, PATH fallback)"
    )
    validate_idx = _index_by_name(install_tasks, "Validate discovered binary path")
    version_idx = _index_by_name(install_tasks, "Get installed openclaw version")
    assert stat_idx < which_idx < resolve_idx < validate_idx < version_idx


def test_install_creates_guard_removed_from_runtime_install(
    install_tasks: list[dict],
) -> None:
    """B1 (v1) — the `Install OpenClaw CLI runtime` task must NOT carry a
    `creates:` argument. The pre-fix guard silently bypassed the install when
    the per-agent file existed at any version, masking version drift and the
    credential-rotation bug. Idempotency is owned by `when: not
    openclaw_already_installed` instead.
    """
    install_task = _task_by_name(install_tasks, "Install OpenClaw CLI runtime")
    assert install_task is not None
    cmd = install_task.get("ansible.builtin.command") or install_task.get("command")
    assert cmd is not None, "Install task must use ansible.builtin.command"
    # `creates:` would live inside the command module dict, not at task level.
    if isinstance(cmd, dict):
        assert "creates" not in cmd, (
            "creates: guard reintroduced — masks #305 credential-rotation bug"
        )
    # And the `when:` gate is what actually owns idempotency now.
    assert "not openclaw_already_installed" in install_task["when"]


def test_install_restarts_service_on_execstart_change(
    install_tasks: list[dict],
) -> None:
    """B3 — explicit `state: restarted` on unit-file change.

    `state: started` on an already-active service is a no-op even after a
    unit-file rewrite — exactly the path that left the running daemon stuck
    on `/usr/local/bin/openclaw` while the ExecStart pointed at the per-agent
    binary in issue #305. The restart task must be gated on the unit-file
    copy's `changed` flag and must run BEFORE the regular `Enable and start`
    task. It must also bundle `daemon_reload: yes` so a stale-unit restart
    is impossible.
    """
    sync = _task_by_name(install_tasks, "Create systemd service file")
    assert sync is not None
    assert sync.get("register") == "openclaw_unit_file_result"

    restart = _task_by_name(
        install_tasks, "Restart openclaw service on ExecStart change"
    )
    assert restart is not None
    systemd = restart.get("ansible.builtin.systemd") or restart.get("systemd")
    assert systemd is not None
    assert systemd.get("state") == "restarted"
    assert systemd.get("enabled") is True  # W1
    assert systemd.get("daemon_reload") is True  # W3/W6
    assert "openclaw_unit_file_result.changed" in restart["when"]

    restart_idx = _index_by_name(
        install_tasks, "Restart openclaw service on ExecStart change"
    )
    start_idx = _index_by_name(install_tasks, "Enable and start openclaw service")
    assert restart_idx < start_idx


def test_install_systemd_unit_uses_resolved_runtime_binary(
    install_tasks: list[dict],
) -> None:
    """Sanity guard against future regression of the original #305 root cause.

    The unit file content must reference `{{ openclaw_runtime_binary }}` — the
    resolved fact — and never `openclaw_which_result.stdout` directly.
    """
    sync = _task_by_name(install_tasks, "Create systemd service file")
    copy = sync.get("ansible.builtin.copy") or sync.get("copy")
    content = copy["content"]
    assert "ExecStart={{ openclaw_runtime_binary }}" in content
    assert "openclaw_which_result.stdout" not in content
