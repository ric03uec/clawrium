"""Pi removal uses the daemonless remove path and preserves state on failure."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from clawrium.core.lifecycle import _run_lifecycle_playbook, remove_agent


def _host():
    return {
        "hostname": "pi-host",
        "key_id": "pi-host",
        "os_family": "linux",
        "agents": {
            "pi-one": {
                "type": "pi",
                "agent_name": "pi-one",
                "runtime": {"status": "running"},
            }
        },
    }


def test_lifecycle_runner_exception_cleans_operation_artifacts(tmp_path):
    playbook = tmp_path / "remove.yaml"
    playbook.write_text("---\n")
    log_dir = tmp_path / "logs"
    def explode(private_data_dir, **_kwargs):
        artifacts = Path(private_data_dir) / "artifacts"
        artifacts.mkdir()
        (artifacts / "inventory").write_text("secret")
        raise RuntimeError("runner exploded")

    with (
        patch("clawrium.core.lifecycle.get_host_private_key", return_value=tmp_path / "key"),
        patch("clawrium.core.lifecycle._get_logs_dir", return_value=log_dir),
        patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=explode),
    ):
        success, error = _run_lifecycle_playbook("pi", "pi-one", "pi-host", "remove", _host(), playbook_path_override=playbook)
    assert success is False and error == "runner exploded"
    assert not list(log_dir.rglob("artifacts"))


def test_lifecycle_missing_events_result_cleans_operation_artifacts(tmp_path):
    playbook = tmp_path / "remove.yaml"
    playbook.write_text("---\n")
    log_dir = tmp_path / "logs"
    failed_without_events = SimpleNamespace(status="failed", rc=1)
    def fail_without_events(private_data_dir, **_kwargs):
        env = Path(private_data_dir) / "env"
        env.mkdir()
        (env / "extravars").write_text("secret")
        return failed_without_events

    with (
        patch("clawrium.core.lifecycle.get_host_private_key", return_value=tmp_path / "key"),
        patch("clawrium.core.lifecycle._get_logs_dir", return_value=log_dir),
        patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fail_without_events),
    ):
        success, error = _run_lifecycle_playbook("pi", "pi-one", "pi-host", "remove", _host(), playbook_path_override=playbook)
    assert success is False and "events" in error
    assert not list(log_dir.rglob("env"))


def test_pi_remove_dispatches_remove_without_stop_and_deletes_after_success():
    host = _host()
    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.lifecycle.stop_agent") as stop,
        patch(
            "clawrium.core.lifecycle._run_lifecycle_playbook", return_value=(True, "")
        ) as run,
        patch(
            "clawrium.core.lifecycle.remove_agent_from_host", return_value=True
        ) as remove,
        patch(
            "clawrium.core.lifecycle.get_instance_key", return_value="pi-instance-key"
        ) as instance_key,
        patch("clawrium.core.lifecycle.remove_instance_secrets") as secrets,
        patch(
            "clawrium.core.lifecycle.cleanup_agent_state", return_value=True
        ) as cleanup,
    ):
        result = remove_agent("pi-host", "pi", agent_name="pi-one")
    assert result["success"] is True
    stop.assert_not_called()
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    run.assert_called_once_with(
        "pi",
        "pi-one",
        "pi-host",
        "remove",
        host,
        timeout=120,
        playbook_path_override=resolve_agent_playbook("pi", "remove", "linux"),
    )
    remove.assert_called_once_with("pi-host", "pi-one")
    instance_key.assert_called_once_with("pi-host", "pi", "pi-one")
    secrets.assert_called_once_with("pi-instance-key")
    cleanup.assert_called_once_with("pi-one")


def test_pi_darwin_remove_runs_runner_with_macos_playbook_and_cleans_up(tmp_path):
    host = _host()
    host["os_family"] = "darwin"
    key = tmp_path / "key"
    key.write_text("test")
    runner = MagicMock(return_value=SimpleNamespace(status="successful", rc=0, stats=None))
    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.lifecycle.get_host_private_key", return_value=key),
        patch("clawrium.core.lifecycle.ansible_runner.run", runner),
        patch("clawrium.core.lifecycle.remove_agent_from_host", return_value=True) as remove,
        patch("clawrium.core.lifecycle.get_instance_key", return_value="key"),
        patch("clawrium.core.lifecycle.remove_instance_secrets") as secrets,
        patch("clawrium.core.lifecycle.cleanup_agent_state", return_value=True) as cleanup,
    ):
        assert remove_agent("pi-host", "pi", agent_name="pi-one")["success"]
    kwargs = runner.call_args.kwargs
    assert kwargs["playbook"].endswith("pi/playbooks/remove_macos.yaml")
    inventory_host = kwargs["inventory"]["all"]["hosts"]["pi-host"]
    assert inventory_host["ansible_user"] == "xclm"
    assert kwargs["inventory"]["all"]["vars"]["agent_name"] == "pi-one"
    assert kwargs["inventory"]["all"]["vars"]["agent_type"] == "pi"
    remove.assert_called_once_with("pi-host", "pi-one")
    secrets.assert_called_once_with("key")
    cleanup.assert_called_once_with("pi-one")


def test_pi_darwin_remove_selects_macos_playbook():
    host = _host()
    host["os_family"] = "darwin"
    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.lifecycle._run_lifecycle_playbook", return_value=(True, "")
        ) as run,
        patch("clawrium.core.lifecycle.remove_agent_from_host", return_value=True),
        patch("clawrium.core.lifecycle.get_instance_key", return_value="key"),
        patch("clawrium.core.lifecycle.remove_instance_secrets"),
        patch("clawrium.core.lifecycle.cleanup_agent_state", return_value=True),
    ):
        assert remove_agent("pi-host", "pi", agent_name="pi-one")["success"]
    assert str(run.call_args.kwargs["playbook_path_override"]).endswith(
        "pi/playbooks/remove_macos.yaml"
    )


def test_pi_darwin_runner_failure_preserves_local_state(tmp_path):
    host = _host()
    host["os_family"] = "darwin"
    key = tmp_path / "key"
    key.write_text("test")
    runner = MagicMock(return_value=SimpleNamespace(status="failed", rc=1, stats=None))
    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.lifecycle.get_host_private_key", return_value=key),
        patch("clawrium.core.lifecycle.ansible_runner.run", runner),
        patch("clawrium.core.lifecycle.remove_agent_from_host") as remove,
        patch("clawrium.core.lifecycle.remove_instance_secrets") as secrets,
        patch("clawrium.core.lifecycle.cleanup_agent_state") as cleanup,
    ):
        result = remove_agent("pi-host", "pi", agent_name="pi-one")
    assert result["success"] is False
    kwargs = runner.call_args.kwargs
    assert kwargs["playbook"].endswith("pi/playbooks/remove_macos.yaml")
    inventory_host = kwargs["inventory"]["all"]["hosts"]["pi-host"]
    assert inventory_host["ansible_user"] == "xclm"
    assert kwargs["inventory"]["all"]["vars"]["agent_name"] == "pi-one"
    assert kwargs["inventory"]["all"]["vars"]["agent_type"] == "pi"
    remove.assert_not_called()
    secrets.assert_not_called()
    cleanup.assert_not_called()


def test_pi_darwin_remove_failure_retains_local_record_and_skips_cleanup():
    host = _host()
    host["os_family"] = "darwin"
    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.lifecycle._run_lifecycle_playbook", return_value=(False, "remote refused")) as run,
        patch("clawrium.core.lifecycle.remove_agent_from_host") as remove,
        patch("clawrium.core.lifecycle.remove_instance_secrets") as secrets,
        patch("clawrium.core.lifecycle.cleanup_agent_state") as cleanup,
    ):
        result = remove_agent("pi-host", "pi", agent_name="pi-one")
    assert result["success"] is False and result["error"] == "remote refused"
    assert str(run.call_args.kwargs["playbook_path_override"]).endswith("pi/playbooks/remove_macos.yaml")
    remove.assert_not_called()
    secrets.assert_not_called()
    cleanup.assert_not_called()


def test_pi_remove_failure_retains_local_record_and_skips_local_cleanup():
    host = _host()
    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.lifecycle._run_lifecycle_playbook",
            return_value=(False, "remote refused"),
        ),
        patch("clawrium.core.lifecycle.remove_agent_from_host") as remove,
        patch("clawrium.core.lifecycle.remove_instance_secrets") as secrets,
    ):
        result = remove_agent("pi-host", "pi", agent_name="pi-one")
    assert result["success"] is False and result["error"] == "remote refused"
    remove.assert_not_called()
    secrets.assert_not_called()
