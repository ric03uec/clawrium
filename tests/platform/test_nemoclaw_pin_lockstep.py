"""3-way version-pin lockstep for the NemoClaw runtime (issue #944).

Per AGENTS.md §"Integration Binary Install" Rule 8, the pin lives in
THREE places that must stay in lockstep and MUST be asserted by direct
pairwise equality — not transitively — so renaming or skipping one
assertion cannot silently unmask drift:

  1. `clawrium.core.nemoclaw.NEMOCLAW_VERSION` (the Python constant).
  2. `manifest.yaml`'s `runtime.nemoclaw.version` field on openclaw.
  3. `install_nemoclaw.yaml`'s `vars.nemoclaw_version` (Linux) and
     `install_nemoclaw_macos.yaml`'s `vars.nemoclaw_version` (darwin
     sibling — currently the fail-loud stub for plan §7.2 option b,
     but the pin is still asserted so a future darwin binary landing
     starts from a locked pin).

A drift here would either install a stale substrate on the host or
render a manifest that no longer matches the pin the resolver reads,
so every openclaw sync would trip a version mismatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clawrium.core.nemoclaw import NEMOCLAW_VERSION

_REGISTRY_ROOT = (
    Path(__file__).parent.parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "openclaw"
)


def _manifest_pin() -> str:
    data = yaml.safe_load((_REGISTRY_ROOT / "manifest.yaml").read_text())
    return data["runtime"]["nemoclaw"]["version"]


def _runbook_pin(name: str) -> str:
    data = yaml.safe_load(
        (_REGISTRY_ROOT / "playbooks" / name).read_text()
    )
    # ansible playbooks are top-level lists of plays; `vars:` sits on
    # the single play we author.
    return data[0]["vars"]["nemoclaw_version"]


def test_python_constant_matches_manifest_pin() -> None:
    assert NEMOCLAW_VERSION == _manifest_pin()


def test_python_constant_matches_linux_runbook_pin() -> None:
    assert NEMOCLAW_VERSION == _runbook_pin("install_nemoclaw.yaml")


def test_python_constant_matches_macos_runbook_pin() -> None:
    assert NEMOCLAW_VERSION == _runbook_pin("install_nemoclaw_macos.yaml")


def test_manifest_pin_matches_linux_runbook_pin() -> None:
    """Direct manifest ↔ runbook equality — do NOT rely on transitive
    equality via the Python-constant assertions above (per AGENTS.md
    Rule 8: a renamed / skipped intermediate test could silently mask
    darwin-only or Linux-only drift)."""
    assert _manifest_pin() == _runbook_pin("install_nemoclaw.yaml")


def test_manifest_pin_matches_macos_runbook_pin() -> None:
    assert _manifest_pin() == _runbook_pin("install_nemoclaw_macos.yaml")


def test_linux_and_macos_runbooks_pin_same_version() -> None:
    """Both siblings must reference the same upstream release, else a
    partially-migrated pin bump silently ships a mixed fleet."""
    assert _runbook_pin("install_nemoclaw.yaml") == _runbook_pin(
        "install_nemoclaw_macos.yaml"
    )


# ---------------------------------------------------------------------------
# AGENTS.md §"Integration Binary Install" Rule 2 regression guard.
# ---------------------------------------------------------------------------


_RUNBOOKS = ("install_nemoclaw.yaml", "install_nemoclaw_macos.yaml")


def _runbook_tasks(name: str) -> list[dict]:
    data = yaml.safe_load(
        (_REGISTRY_ROOT / "playbooks" / name).read_text()
    )
    return data[0]["tasks"]


@pytest.mark.parametrize("runbook", _RUNBOOKS)
def test_runbook_has_single_task0_dispatcher_guard(runbook: str) -> None:
    """Each nemoclaw runbook is permitted exactly ONE
    `when: ansible_os_family` clause, and it MUST be at task-0
    position, and it MUST fire only `ansible.builtin.fail` — mirrors
    the slack MCP regression guard in `test_slack_asset_map.py` so
    a future edit that reintroduces OS branching inside install
    tasks trips here."""
    tasks = _runbook_tasks(runbook)
    guarded = [
        t
        for t in tasks
        if "ansible_os_family" in str(t.get("when", ""))
    ]
    assert len(guarded) == 1, (
        f"{runbook}: expected exactly ONE task with a "
        f"`when: ansible_os_family` clause; found {len(guarded)}."
    )
    assert tasks[0] is guarded[0], (
        f"{runbook}: dispatcher-contract guard must be task-0."
    )
    guard_action_keys = [
        k
        for k in tasks[0].keys()
        if k not in {"name", "when", "become", "become_user", "no_log"}
    ]
    assert guard_action_keys == ["ansible.builtin.fail"], (
        f"{runbook}: dispatcher-contract guard at task-0 must ONLY "
        f"call `ansible.builtin.fail` — found {guard_action_keys!r}."
    )


def test_linux_runbook_arch_map_matches_python_supported_arches() -> None:
    """Every arch the runbook claims to install for MUST have a matching
    entry in `clawrium.core.nemoclaw.SUPPORTED_ARCHES`. Drift here
    would let the runbook route to an arch the Python side rejects
    (or vice versa)."""
    from clawrium.core.nemoclaw import SUPPORTED_ARCHES

    data = yaml.safe_load(
        (_REGISTRY_ROOT / "playbooks" / "install_nemoclaw.yaml").read_text()
    )
    arch_map = data[0]["vars"]["nemoclaw_arch_map"]
    assert set(arch_map.keys()) == set(SUPPORTED_ARCHES)
