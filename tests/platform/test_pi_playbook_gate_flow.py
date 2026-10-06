"""Evaluate the actual Pi playbook gate expressions with representative facts.

This deliberately renders the YAML task ``when`` expressions rather than
reimplementing their predicates in Python, so inverted/bypassed gates fail.
"""

from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).parents[2] / "src/clawrium/platform/registry/pi/playbooks"


def _task(playbook: str, name: str) -> dict:
    def walk(tasks):
        for candidate in tasks:
            if candidate["name"] == name:
                return candidate
            for section in ("block", "always", "rescue"):
                found = walk(candidate.get(section, []))
                if found:
                    return found
        return None

    found = walk(yaml.safe_load((ROOT / playbook).read_text())[0]["tasks"])
    assert found is not None
    return found


def _when(task: dict, facts: dict) -> bool:
    """Render an Ansible/Jinja ``when`` expression against supplied facts."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.tests["match"] = lambda value, pattern: __import__("re").match(pattern, value) is not None
    env.filters["bool"] = bool
    return env.from_string("{{ " + task["when"] + " }}").render(facts) == "True"


def test_linux_install_unmanaged_account_gate_reaches_fail_only_for_unmanaged_state():
    gate = _task("install.yaml", "Refuse unmanaged Pi account or marker")
    assert _when(gate, {"pi_account": {"rc": 0}, "pi_marker_stat": {"stat": {"exists": False}}, "pi_intent_stat": {"stat": {"exists": False}}})
    assert not _when(gate, {"pi_account": {"rc": 0}, "pi_marker_stat": {"stat": {"exists": True}}, "pi_intent_stat": {"stat": {"exists": False}}})


def test_darwin_install_dispatch_and_unmanaged_account_gates_execute_actual_whens():
    dispatcher = _task("install_macos.yaml", "Refuse non-Darwin dispatcher target")
    assert _when(dispatcher, {"ansible_os_family": "Linux"})
    assert not _when(dispatcher, {"ansible_os_family": "Darwin"})
    gate = _task("install_macos.yaml", "Refuse unmanaged Pi account or marker")
    unmanaged = {"pi_existing_uid": {"stdout": "701\n"}, "pi_marker_stat": {"stat": {"exists": False}}, "pi_intent_stat": {"stat": {"exists": False}}}
    managed = {**unmanaged, "pi_marker_stat": {"stat": {"exists": True}}}
    assert _when(gate, unmanaged)
    assert not _when(gate, managed)


def test_install_version_gate_reaches_fail_for_nonimmutable_version_on_both_os():
    for playbook in ("install.yaml", "install_macos.yaml"):
        gate = _task(playbook, "Reject non-immutable Pi version")
        assert _when(gate, {"pi_version": "latest"})
        assert not _when(gate, {"pi_version": "0.73.1"})


def test_remove_unmanaged_gates_and_exec_ownership_assertions_are_real_playbook_tasks():
    linux_remove = _task("remove.yaml", "Refuse unmanaged Pi removal")
    assert _when(linux_remove, {"pi_account": {"rc": 0}, "pi_marker_stat": {"stat": {"exists": False}}, "pi_intent_stat": {"stat": {"exists": False}}})
    darwin_remove = _task("remove_macos.yaml", "Refuse unmanaged Pi removal")
    assert _when(darwin_remove, {"pi_existing_uid": {"stdout": ""}, "pi_marker_stat": {"stat": {"exists": False}}, "pi_intent_stat": {"stat": {"exists": False}}})
    for playbook in ("exec.yaml", "exec_macos.yaml"):
        reject = _task(playbook, "Reject untrusted Pi execution target")
        verify = _task(playbook, "Verify Pi execution ownership binding")
        # These are asserts (not a permissive shell check): ownership must
        # fail before the finite command task can execute.
        assert "ansible.builtin.assert" in reject
        assert "ansible.builtin.assert" in verify
        assert "pi_marker_stat.stat.exists | bool" in str(reject)
        assert "transaction_id" in str(verify)
