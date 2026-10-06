"""Behavior-bearing install-only Pi playbook contracts (#1032)."""

from __future__ import annotations
from pathlib import Path
import subprocess

import yaml
from clawrium.core.agent_exec import SUPPORTED_CLAW_TYPES
from clawrium.core.agent_lifecycle import has_daemon_lifecycle
from clawrium.core.registry import list_claws, load_manifest

ROOT = Path(__file__).parents[2] / "src/clawrium/platform/registry/pi"
PIN = "0.73.1"


def playbook(name):
    return yaml.safe_load((ROOT / "playbooks" / name).read_text())[0]


def task(tasks, name):
    for candidate in tasks:
        if candidate["name"] == name:
            return candidate
        for section in ("block", "always", "rescue"):
            if section in candidate:
                try:
                    return task(candidate[section], name)
                except StopIteration:
                    pass
    raise StopIteration(name)


def test_pi_registry_is_daemonless_and_pinned():
    m = load_manifest("pi")
    assert "pi" in list_claws() and not has_daemon_lifecycle("pi")
    assert "pi" in SUPPORTED_CLAW_TYPES and {p["version"] for p in m["platforms"]} == {
        PIN
    }


def test_pi_install_contract_is_isolated_and_idempotent_on_both_os():
    for name, home, group in (
        ("install.yaml", "/home/{{ agent_name }}", "{{ agent_name }}"),
        ("install_macos.yaml", "/Users/{{ agent_name }}", "staff"),
    ):
        p = playbook(name)
        tasks = p["tasks"]
        rendered = yaml.safe_dump(tasks).lower()
        assert p["vars"]["pi_default_version"] == PIN and p["vars"]["pi_home"] == home
        if name.endswith("_macos.yaml"):
            assert task(tasks, "Refuse non-Darwin dispatcher target")["when"] == (
                'ansible_os_family is defined and ansible_os_family != "Darwin"'
            )
        assert (
            "systemd" not in rendered
            and "launchctl" not in rendered
            and "gateway" not in rendered
        )
        assert task(tasks, "Reject non-immutable Pi version")["ansible.builtin.fail"]
        if name == "install.yaml":
            assert task(tasks, "Acquire nonce-bound Pi UID allocation lock")[
                "changed_when"
            ] is False
        assert task(tasks, "Refuse unmanaged Pi account or marker")[
            "ansible.builtin.fail"
        ]
        install_task = task(tasks, "Install pinned Pi package")
        install = install_task["ansible.builtin.command"]
        assert install["argv"][-1] == "{{ pi_package }}@{{ pi_version }}"
        assert install_task["become_user"] == "{{ agent_name }}"
        assert (
            task(tasks, "Create owned Pi prefix")["ansible.builtin.file"]["group"]
            == group
        )


def test_pi_marker_writer_uses_json_serializer_for_both_platforms():
    for name in ("install.yaml", "install_macos.yaml"):
        writer = task(
            playbook(name)["tasks"],
            "Promote Pi install transaction to ownership marker",
        )
        content = writer["ansible.builtin.copy"]["content"]
        assert "to_json" in content
        assert (
            "schema" in content
            and "agent_name" in content
            and "home" in content
            and "uid" in content
        )
        # Prevent a repeat of the literal-brace template that emitted invalid JSON live.
        assert "}}}" not in content


def test_pi_install_transaction_recovers_only_the_bound_account():
    for name, root_group, uid_floor in (
        ("install.yaml", "root", "2000"),
        ("install_macos.yaml", "wheel", "700"),
    ):
        tasks = playbook(name)["tasks"]
        if name.endswith("_macos.yaml"):
            lock = task(tasks, "Acquire or safely recover Pi UID allocation lock")
            assert "uid-allocation.lock" in str(lock) and lock["retries"] >= 1
            assert "owner" in lock["ansible.builtin.shell"]
            assert "uuidgen" in lock["ansible.builtin.shell"]
            assert "rm -rf" not in lock["ansible.builtin.shell"]
            assert "manually removing" in lock["ansible.builtin.shell"]
            transaction = task(tasks, "Allocate and promote dedicated Pi account transaction")
            assert task(transaction["block"], "Create dedicated Pi account")
            release = transaction["always"][0]
            assert "{{ agent_name }}:{{ pi_uid_lock.stdout | trim }}" in release["ansible.builtin.shell"]
            assert "rmdir" in release["ansible.builtin.shell"]
        intent = task(tasks, "Write pre-account Pi install intent")
        assert intent["ansible.builtin.copy"]["mode"] == "0600"
        assert "transaction_id" in intent["ansible.builtin.copy"]["content"]
        assert root_group == intent["ansible.builtin.copy"]["group"]
        assert (
            uid_floor
            in task(tasks, "Reserve a dedicated Pi UID")["ansible.builtin.shell"]
        )
        recovery = task(tasks, "Verify recoverable Pi install intent")[
            "ansible.builtin.assert"
        ]
        assert (
            "transaction_id" in str(recovery)
            and "bind this account" in recovery["fail_msg"]
        )
        account = (
            task(tasks, "Create dedicated Pi agent account")
            if name == "install.yaml"
            else task(tasks, "Create dedicated Pi account")
        )
        assert "clawrium-pi-" in str(account)  # Account metadata binds the intent.
        assert task(tasks, "Clear promoted Pi install intent")["ansible.builtin.file"]


def test_validated_marker_repeat_skips_transaction_only_uid_promotion_tasks():
    for name in ("install.yaml", "install_macos.yaml"):
        tasks = playbook(name)["tasks"]
        transaction = task(tasks, "Allocate and promote dedicated Pi account transaction")
        for task_name in (
            "Verify reserved Pi UID remains exclusive",
            "Refuse shared Pi UID before promotion",
        ):
            repeat_guard = task(transaction["block"], task_name)["when"]
            assert "not (pi_marker_stat.stat.exists | bool)" in repeat_guard
        # A repeat has a validated marker and no intent/transaction data; these
        # guards prevent any reference to pi_transaction_data on that path.
        assert task(transaction["block"], "Clear promoted Pi install intent")[
            "ansible.builtin.file"
        ]["state"] == "absent"


def test_linux_uid_lock_is_released_after_transaction_failure_without_stealing(
    tmp_path: Path,
):
    tasks = playbook("install.yaml")["tasks"]
    transaction = task(tasks, "Allocate and promote dedicated Pi account transaction")
    transaction_tasks = transaction["block"]
    release = transaction["always"][0]
    release_script = release["ansible.builtin.shell"]

    # Ansible runs `always` after a failure anywhere in `block`, including the
    # account-creation task, so a failed install cannot strand its allocation.
    assert task(transaction_tasks, "Create dedicated Pi agent account")
    assert release["name"] == "Release nonce-bound Pi UID allocation lock"
    assert "{{ agent_name }}:{{ pi_uid_lock.stdout | trim }}" in release_script
    rendered_release = (
        release_script.replace("{{ pi_marker_dir }}", str(tmp_path))
        .replace("{{ agent_name }}:{{ pi_uid_lock.stdout | trim }}", "pi-test:nonce")
    )
    lock = tmp_path / ".uid-allocation.lock"
    lock.mkdir()
    (lock / "owner").write_text("pi-test:nonce\n")
    assert subprocess.run(["/bin/bash", "-c", rendered_release]).returncode == 0
    assert not lock.exists()

    # A competing or tampered lock must remain in place: only this exact owner
    # record may be unlinked, and rmdir refuses non-empty directories.
    lock.mkdir()
    owner = lock / "owner"
    owner.write_text("other-agent:nonce\n")
    result = subprocess.run(["/bin/bash", "-c", rendered_release], capture_output=True)
    assert result.returncode != 0
    assert owner.read_text() == "other-agent:nonce\n"
    assert 'test "$actual" != "$expected"' in release_script
    assert "rm -- \"$owner\"" in release_script
    assert "rmdir -- \"$lock\"" in release_script
    assert "rm -rf" not in release_script
    acquire_script = task(tasks, "Acquire nonce-bound Pi UID allocation lock")[
        "ansible.builtin.shell"
    ]
    assert "manually removing" in acquire_script
    assert 'rmdir "$lock"' in acquire_script


def test_pi_recovery_and_remove_fail_closed_for_foreign_or_tampered_state():
    for name, root_group in (("remove.yaml", "root"), ("remove_macos.yaml", "wheel")):
        tasks = playbook(name)["tasks"]
        trusted = task(tasks, "Verify trusted Pi transaction files")
        assert root_group in str(trusted) and "islnk" in str(trusted)
        gate = task(tasks, "Refuse unmanaged Pi removal")
        assert "ownership transaction" in gate["ansible.builtin.fail"]["msg"]
        binding = task(tasks, "Verify Pi removal ownership binding")[
            "ansible.builtin.assert"
        ]
        assert (
            "transaction_id" in str(binding)
            and "bind this account" in binding["fail_msg"]
        )
        assert task(tasks, "Remove Pi install intent")["ansible.builtin.file"]


def test_pi_remove_and_exec_are_scoped_to_dedicated_account_on_both_os():
    for name, home in (
        ("remove.yaml", "/home/{{ agent_name }}"),
        ("remove_macos.yaml", "/Users/{{ agent_name }}"),
    ):
        p = playbook(name)
        tasks = p["tasks"]
        assert p["vars"]["pi_home"] == home
        if name.endswith("_macos.yaml"):
            assert task(tasks, "Refuse non-Darwin dispatcher target")["when"] == (
                'ansible_os_family is defined and ansible_os_family != "Darwin"'
            )
        assert task(tasks, "Refuse unmanaged Pi removal")["ansible.builtin.fail"]
        # Managed deletion is constrained to the agent home; project-level .pi is absent.
        rendered = yaml.safe_dump(tasks)
        assert "state: absent" in rendered and ".pi" not in rendered
    for name, home in (
        ("exec.yaml", "/home/{{ agent_name }}"),
        ("exec_macos.yaml", "/Users/{{ agent_name }}"),
    ):
        p = playbook(name)
        if name.endswith("_macos.yaml"):
            assert task(p["tasks"], "Refuse non-Darwin dispatcher target")["when"] == (
                'ansible_os_family is defined and ansible_os_family != "Darwin"'
            )
        assert task(p["tasks"], "Reject untrusted Pi execution target")[
            "ansible.builtin.assert"
        ]
        binding = task(p["tasks"], "Verify Pi execution ownership binding")[
            "ansible.builtin.assert"
        ]
        assert "transaction_id" in str(binding) and "home" in str(binding)
        exec_task = task(p["tasks"], "Run encrypted Pi native command")
        t = exec_task["ansible.builtin.command"]
        assert p["vars"]["pi_binary"] == "{{ pi_home }}/.local/pi/bin/pi"
        assert "pi_exec_capture_bootstrap" in t["argv"]
        assert "pi_exec_recipient_certificate" in t["argv"]
        assert exec_task["become_user"] == "{{ agent_name }}"
        assert exec_task["no_log"] is True
