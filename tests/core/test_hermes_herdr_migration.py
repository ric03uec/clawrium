from unittest.mock import Mock

import pytest

import clawrium.core.lifecycle_canonical as lc


@pytest.mark.parametrize(
    ("os_family", "operation"), [("linux", "install_herdr"), ("darwin", "install_herdr_macos")]
)
def test_hermes_reconcile_dispatches_os_specific_playbook(monkeypatch, os_family, operation):
    calls = []
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook",
        lambda **kwargs: calls.append(kwargs) or (True, None),
    )
    lc._hermes_reconcile_herdr("legacy", "host", {"os_family": os_family})
    assert calls[0]["agent_type"] == "hermes"
    assert calls[0]["operation"] == operation


def test_hermes_reconcile_failure_is_canonical_error(monkeypatch):
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook", lambda **_: (False, "checksum mismatch")
    )
    with pytest.raises(lc.CanonicalSyncError, match="Herdr reconciliation failed"):
        lc._hermes_reconcile_herdr("legacy", "host", {})


def test_migration_runbooks_provision_shared_binary_and_plugin():
    from pathlib import Path

    root = Path(__file__).parents[2]
    for name in ("install_herdr.yaml", "install_herdr_macos.yaml"):
        body = (root / "src/clawrium/platform/registry/hermes/playbooks" / name).read_text()
        assert "import_playbook: ../../../playbooks/herdr" in body
        assert "integration, install, hermes" in body
        assert 'become_user: "{{ agent_name }}"' in body
