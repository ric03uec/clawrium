"""Tests for the slack-mcp-server per-arch install matrix on hermes.

#834 (B6/W3): the runbook downloads the korotovsky/slack-mcp-server
binary via `get_url` with an sha256 checksum. The (arch → asset filename)
and (arch → sha256) maps live in the runbook `vars:` block. A drift
between the two, or a missing arch that ansible would happily leave
without a checksum guard, would silently install a mismatched binary
(or fail loudly at first sync — this test catches the drift up
front).

Runbook layout follows AGENTS.md §"Integration Binary Install":
`install_slack_mcp.yaml` (Linux) + `install_slack_mcp_macos.yaml`
(darwin, divergent arch naming — `arm64` vs Linux's `aarch64`). Both
files are covered here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _playbook_vars(name: str) -> dict:
    path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / "hermes"
        / "playbooks"
        / name
    )
    data = yaml.safe_load(path.read_text())
    # ansible playbooks are top-level lists of plays; `vars:` sits on
    # the single play we author.
    return data[0]["vars"]


# ---------------------------------------------------------------------------
# Linux (install_slack_mcp.yaml)
# ---------------------------------------------------------------------------


LINUX_ARCH_TARGETS = [
    ("x86_64", "linux-amd64"),
    ("aarch64", "linux-arm64"),
]

LINUX_EXPECTED_SHA256 = {
    "x86_64": "d1525962e9b9dbfdd2eaf48d0a81ca1eca7d8f1862b8d34931b812c850b3e568",
    "aarch64": "a307a48d16c2261346bdc257274cdcdb8b2027c867dc971b41d52cef36472c88",
}


def test_linux_playbook_pins_mcp_slack_version() -> None:
    vs = _playbook_vars("install_slack_mcp.yaml")
    assert vs["mcp_slack_version"] == "v1.3.0"


@pytest.mark.parametrize(("arch", "expected_asset_suffix"), LINUX_ARCH_TARGETS)
def test_linux_arch_map_covers_arch(arch: str, expected_asset_suffix: str) -> None:
    vs = _playbook_vars("install_slack_mcp.yaml")
    assert vs["mcp_slack_arch_map"][arch] == expected_asset_suffix


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_linux_sha256_map_covers_arch(arch: str) -> None:
    vs = _playbook_vars("install_slack_mcp.yaml")
    assert vs["mcp_slack_sha256_map"][arch] == LINUX_EXPECTED_SHA256[arch]


def test_linux_maps_have_identical_keys() -> None:
    """The arch and sha256 maps must have the exact same key set —
    a mismatch would let a supported arch slip past the checksum guard."""
    vs = _playbook_vars("install_slack_mcp.yaml")
    assert set(vs["mcp_slack_arch_map"].keys()) == set(
        vs["mcp_slack_sha256_map"].keys()
    )


def test_linux_armv7l_intentionally_absent() -> None:
    """korotovsky/slack-mcp-server v1.3.0 does NOT ship an armv7l asset.
    The playbook's arch guard MUST fail-fast rather than silently skip
    slack setup on armv7l zeroclaw hosts. Regression signal so a
    future addition of armv7 shipping upstream also lands here."""
    vs = _playbook_vars("install_slack_mcp.yaml")
    assert "armv7l" not in vs["mcp_slack_arch_map"]
    assert "armv7l" not in vs["mcp_slack_sha256_map"]


# ---------------------------------------------------------------------------
# Darwin (install_slack_mcp_macos.yaml)
# ---------------------------------------------------------------------------


DARWIN_ARCH_TARGETS = [
    ("arm64", "darwin-arm64"),
    ("x86_64", "darwin-amd64"),
]

DARWIN_EXPECTED_SHA256 = {
    "arm64": "e839aa5c2e28253438ed704dd862aa4afb75711d688080ce447a3b1167855312",
    "x86_64": "e38142ee628b2c2ff241f0d021947b96e743540cfb702fc8b01f61a4f7a4a125",
}


def test_darwin_playbook_pins_mcp_slack_version() -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml")
    assert vs["mcp_slack_version"] == "v1.3.0"


@pytest.mark.parametrize(("arch", "expected_asset_suffix"), DARWIN_ARCH_TARGETS)
def test_darwin_arch_map_covers_arch(arch: str, expected_asset_suffix: str) -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml")
    assert vs["mcp_slack_arch_map"][arch] == expected_asset_suffix


@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_darwin_sha256_map_covers_arch(arch: str) -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml")
    assert vs["mcp_slack_sha256_map"][arch] == DARWIN_EXPECTED_SHA256[arch]


def test_darwin_maps_have_identical_keys() -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml")
    assert set(vs["mcp_slack_arch_map"].keys()) == set(
        vs["mcp_slack_sha256_map"].keys()
    )


# ---------------------------------------------------------------------------
# Cross-file version lockstep
# ---------------------------------------------------------------------------


def test_linux_and_darwin_pin_same_version() -> None:
    """Both runbooks must reference the same upstream release, else a
    partially-migrated pin bump silently ships a mixed fleet."""
    linux = _playbook_vars("install_slack_mcp.yaml")
    darwin = _playbook_vars("install_slack_mcp_macos.yaml")
    assert linux["mcp_slack_version"] == darwin["mcp_slack_version"]


@pytest.mark.parametrize(
    "runbook",
    ["install_slack_mcp.yaml", "install_slack_mcp_macos.yaml"],
)
def test_render_constant_matches_playbook_pin(runbook: str) -> None:
    """`_HERMES_MCP_SLACK_VERSION` in render.py is the single source of
    truth for the upstream pin — drift silently, hosts silently.
    Lockstep is asserted against EACH runbook directly (per AGENTS.md
    §"Integration Binary Install" Rule 8): a transitive assertion via
    the separate Linux ↔ darwin equality test would silently fail to
    catch a darwin-only regression if the intermediate test were
    renamed or skipped."""
    from clawrium.core.render import _HERMES_MCP_SLACK_VERSION

    vs = _playbook_vars(runbook)
    assert _HERMES_MCP_SLACK_VERSION == vs["mcp_slack_version"]


# ---------------------------------------------------------------------------
# AGENTS.md §"Integration Binary Install" Rule 2 regression guard.
# ---------------------------------------------------------------------------


def _runbook_tasks(runbook: str) -> list[dict]:
    """Load the runbook's task list via YAML parse — lets us assert
    structural properties (task-0 position, task action, `when:`
    clauses) instead of hoping a line-scan catches every regression."""
    path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / "hermes"
        / "playbooks"
        / runbook
    )
    data = yaml.safe_load(path.read_text())
    return data[0]["tasks"]


@pytest.mark.parametrize(
    "runbook",
    ["install_slack_mcp.yaml", "install_slack_mcp_macos.yaml"],
)
def test_runbook_has_single_task0_dispatcher_guard(runbook: str) -> None:
    """Rule 2 narrow exception: each runbook is permitted exactly ONE
    `when: ansible_os_family` clause, and it MUST be at task-0
    position, and it MUST fire only `ansible.builtin.fail` (not
    conditionally install anything — that would reintroduce OS
    branching inside install tasks).

    ATX iter-4 W1 introduced a line-scan version of this test; iter-5
    W3 upgraded to YAML parsing so all three sub-invariants (single
    guard, task-0 position, `fail:` action) are enforced structurally.
    """
    tasks = _runbook_tasks(runbook)

    # Sub-invariant 1: exactly ONE task has `when: ansible_os_family`.
    guarded = [
        t
        for t in tasks
        if "ansible_os_family" in str(t.get("when", ""))
    ]
    assert len(guarded) == 1, (
        f"{runbook}: expected exactly ONE task with a "
        f"`when: ansible_os_family` clause (task-0 dispatcher-contract "
        f"guard); found {len(guarded)}. Rule 2 bans OS branching "
        f"inside install tasks."
    )

    # Sub-invariant 2: it MUST be task-0. Any earlier install task
    # (mkdir, download, etc.) would run on the wrong-OS host before
    # the guard tripped.
    assert tasks[0] is guarded[0], (
        f"{runbook}: dispatcher-contract guard must be task-0 "
        f"(runs before any install work). Currently at task "
        f"{tasks.index(guarded[0])}. Move to the top of `tasks:`."
    )

    # Sub-invariant 3: the guarded task MUST fire `ansible.builtin.fail`
    # only (never `get_url:`, `file:`, etc.). A guard on an install
    # task is exactly the OS-branching-inside-install-task pattern
    # Rule 2 bans.
    guard_action_keys = [
        k
        for k in tasks[0].keys()
        if k not in {"name", "when", "become", "become_user", "no_log"}
    ]
    assert guard_action_keys == ["ansible.builtin.fail"], (
        f"{runbook}: dispatcher-contract guard at task-0 must ONLY "
        f"call `ansible.builtin.fail` — found action keys "
        f"{guard_action_keys!r}. A guard on an install task would "
        f"reintroduce OS branching inside install tasks (Rule 2)."
    )
