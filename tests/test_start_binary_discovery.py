"""Tests for binary discovery convergence in the openclaw `start` playbook.

The `start` playbook regenerates the systemd unit file every time it runs. If
its binary discovery diverges from `install.yaml`, a `clawctl agent start` on a
host where `/usr/local/bin/openclaw` exists at version A will silently rewrite
the unit's `ExecStart` to point at the system-wide binary, even when the
per-agent install at `/home/<agent>/.openclaw/bin/openclaw` is the binary
clawrium just wrote at version B (issue #305).

These tests parse the playbook YAML and assert the ordering, conditions, and
register-keys called out in the v2 plan (B3, B4, S1–S4). Running real ansible
isn't feasible in unit tests, but every property under test is statically
expressible from the playbook structure.
"""

from pathlib import Path

import pytest
import yaml


START_PLAYBOOK = (
    Path(__file__).parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "openclaw"
    / "playbooks"
    / "start.yaml"
)

# Inside a `{{ ... }}` Jinja expression the per-agent path is built via string
# concatenation: `'/home/' ~ agent_name ~ '/.openclaw/bin/openclaw'`. Outside
# a Jinja expression it's the templated form `/home/{{ agent_name }}/...`. We
# accept either, since both render to the same path.
PER_AGENT_CONCAT = "'/home/' ~ agent_name ~ '/.openclaw/bin/openclaw'"


@pytest.fixture(scope="module")
def start_tasks() -> list[dict]:
    play = yaml.safe_load(START_PLAYBOOK.read_text())
    # The file is a single-play list; pull tasks out.
    assert isinstance(play, list) and len(play) == 1, "start.yaml must be a single play"
    tasks = play[0].get("tasks", [])
    assert tasks, "start.yaml must declare tasks"
    return tasks


def _task_by_name(tasks: list[dict], name: str) -> dict | None:
    return next((t for t in tasks if t.get("name") == name), None)


def _index_by_name(tasks: list[dict], name: str) -> int:
    return next(i for i, t in enumerate(tasks) if t.get("name") == name)


def test_start_uses_per_agent_binary_when_present(start_tasks: list[dict]) -> None:
    """S1 — per-agent precedence in the resolution step.

    The `set_fact` task must prefer the per-agent path whenever
    `openclaw_per_agent_stat.stat.exists` is truthy. We assert by string-
    matching the Jinja2 expression because a structural assertion would require
    evaluating Jinja2.
    """
    resolve = _task_by_name(
        start_tasks, "Resolve openclaw binary (per-agent preferred, PATH fallback)"
    )
    assert resolve is not None, "Resolve task missing from start.yaml"

    set_fact = resolve.get("ansible.builtin.set_fact") or resolve.get("set_fact")
    assert set_fact is not None, "Resolve task must use set_fact"

    expr = set_fact["openclaw_runtime_binary"]
    # Per-agent path must appear; chosen first (`if openclaw_per_agent_stat.stat.exists`).
    assert PER_AGENT_CONCAT in expr
    assert "openclaw_per_agent_stat.stat.exists" in expr
    # And the per-agent branch must come before the `which` fallback in the conditional.
    assert expr.index("openclaw_per_agent_stat.stat.exists") < expr.index(
        "openclaw_which_result.stdout"
    )


def test_start_validator_runs_on_resolved_variable(
    start_tasks: list[dict],
) -> None:
    """Round 2 B1 — validator must run on `openclaw_runtime_binary` (the
    resolved variable that propagates to ExecStart), NOT on
    `openclaw_which_result.stdout` (the raw PATH discovery).

    The earlier S2 design (gate validator on `not stat.exists` and validate
    `which.stdout`) was REJECTED in round 2: it let a zero-byte per-agent
    file fall back to an unvalidated PATH binary, which then reached the
    systemd ExecStart unchecked. Validating the resolved fact closes that
    gap. The per-agent /home/... case trivially passes the allowlist — which
    is correct, not a no-op.
    """
    validate = _task_by_name(start_tasks, "Validate resolved binary path")
    assert validate is not None, "Validate task missing from start.yaml"

    when = validate["when"]
    # Must check the resolved variable, not the raw which result.
    assert "openclaw_runtime_binary" in when
    assert "openclaw_which_result.stdout" not in when
    # Must NOT be gated on stat.exists — that's the regressed behavior.
    assert "not openclaw_per_agent_stat.stat.exists" not in when

    # Ordering check: stat → which → resolve → validate.
    # Validator now runs AFTER resolve so it can read the resolved fact.
    stat_idx = _index_by_name(start_tasks, "Check per-agent openclaw binary")
    which_idx = _index_by_name(start_tasks, "Discover openclaw binary in PATH")
    resolve_idx = _index_by_name(
        start_tasks, "Resolve openclaw binary (per-agent preferred, PATH fallback)"
    )
    validate_idx = _index_by_name(start_tasks, "Validate resolved binary path")
    assert stat_idx < which_idx < resolve_idx < validate_idx


def test_start_rejects_unsafe_path_binary(start_tasks: list[dict]) -> None:
    """S3 — unsafe path rejection.

    When the resolved binary is outside the allowlist (e.g. `/tmp/openclaw`
    from a PATH fallback), the validator's `ansible.builtin.fail` must
    trigger and stop the playbook before the unit file is rewritten.
    """
    validate = _task_by_name(start_tasks, "Validate resolved binary path")
    assert validate is not None

    # Must be a `fail` task, not a debug — debug wouldn't stop the playbook.
    # Use explicit `.get(...) is not None` instead of `'fail' in validate`:
    # the substring form would match any dict key containing "fail" (e.g.
    # `failed_when`), letting an accidentally-removed fail module slip past.
    assert (
        validate.get("ansible.builtin.fail") is not None
        or validate.get("fail") is not None
    )

    when = validate["when"]
    # Allowlist must include exactly these prefixes; anything else (incl. /tmp)
    # should fail.
    for allowed in ("/usr/local/bin/", "/usr/bin/", "/home/"):
        assert allowed in when, f"Allowlist missing prefix {allowed!r}"


def test_start_restarts_service_when_unit_file_changes(
    start_tasks: list[dict],
) -> None:
    """S4 / B3 — explicit restart-on-change.

    `state: started` on an already-active service is a no-op even after a
    unit-file rewrite. The playbook must include an explicit `state: restarted`
    task gated on the unit-file copy's `changed` flag, placed before the
    regular `Start openclaw service` task.
    """
    sync = _task_by_name(start_tasks, "Sync systemd service file")
    assert sync is not None
    assert sync.get("register") == "service_file_changed"

    restart = _task_by_name(
        start_tasks, "Restart openclaw service if unit file changed"
    )
    assert restart is not None, "B3 restart task missing from start.yaml"

    systemd = restart.get("ansible.builtin.systemd") or restart.get("systemd")
    assert systemd is not None
    assert systemd.get("state") == "restarted"
    assert "service_file_changed.changed" in restart["when"]

    # Restart must run before the regular Start task.
    restart_idx = _index_by_name(
        start_tasks, "Restart openclaw service if unit file changed"
    )
    start_idx = _index_by_name(start_tasks, "Start openclaw service")
    assert restart_idx < start_idx


def test_start_systemd_unit_uses_resolved_runtime_binary(
    start_tasks: list[dict],
) -> None:
    """Sanity guard against future regression of the original #305 root cause.

    The unit file content must reference `{{ openclaw_runtime_binary }}` — the
    resolved fact — and never `openclaw_which_result.stdout` directly. If
    anyone "simplifies" the playbook by inlining the `which` result back into
    `ExecStart`, that change is the #305 bug returning, and this test will
    fail.
    """
    sync = _task_by_name(start_tasks, "Sync systemd service file")
    assert sync is not None
    copy = sync.get("ansible.builtin.copy") or sync.get("copy")
    content = copy["content"]
    assert "ExecStart={{ openclaw_runtime_binary }}" in content
    assert "openclaw_which_result.stdout" not in content
