"""Tests for the slack-mcp-server per-arch install matrix.

#834 (B6/W3): the runbook downloads the korotovsky/slack-mcp-server
binary via `get_url` with an sha256 checksum. The (arch → asset filename)
and (arch → sha256) maps live in the runbook `vars:` block. A drift
between the two, or a missing arch that ansible would happily leave
without a checksum guard, would silently install a mismatched binary
(or fail loudly at first sync — this test catches the drift up
front).

Runbook layout follows AGENTS.md §"Integration Binary Install":
`install_slack_mcp.yaml` (Linux) + `install_slack_mcp_macos.yaml`
(darwin, divergent arch naming — `arm64` vs Linux's `aarch64`).

#835 (Phase 2): openclaw ships parallel runbooks with byte-identical
pins so both agent types install the same binary at the same version.
Rule 1 (one runbook per (agent_type, binary)) puts them at
`openclaw/playbooks/install_slack_mcp*.yaml`. Rule 8 requires a
per-runbook lockstep assertion against the Python version constant;
this file exercises all four runbook files (hermes+openclaw, Linux+darwin).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Agent types with both Linux + darwin runbooks. Zeroclaw ships only
# the Linux runbook at #836; its darwin sibling is deferred to a
# follow-up (see AGENTS.md §"Integration Binary Install" canonical
# examples). Cross-file (Linux ↔ darwin) tests scope to this tuple;
# Linux-only tests parametrize over `_LINUX_AGENT_TYPES` below.
_AGENT_TYPES = ("hermes", "openclaw")
_LINUX_AGENT_TYPES = ("hermes", "openclaw", "zeroclaw")


def _playbook_vars(name: str, agent_type: str = "hermes") -> dict:
    path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / agent_type
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


@pytest.mark.parametrize("agent_type", _LINUX_AGENT_TYPES)
def test_linux_playbook_pins_mcp_slack_version(agent_type: str) -> None:
    vs = _playbook_vars("install_slack_mcp.yaml", agent_type)
    assert vs["mcp_slack_version"] == "v1.3.0"


@pytest.mark.parametrize("agent_type", _LINUX_AGENT_TYPES)
@pytest.mark.parametrize(("arch", "expected_asset_suffix"), LINUX_ARCH_TARGETS)
def test_linux_arch_map_covers_arch(
    agent_type: str, arch: str, expected_asset_suffix: str
) -> None:
    vs = _playbook_vars("install_slack_mcp.yaml", agent_type)
    assert vs["mcp_slack_arch_map"][arch] == expected_asset_suffix


@pytest.mark.parametrize("agent_type", _LINUX_AGENT_TYPES)
@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_linux_sha256_map_covers_arch(agent_type: str, arch: str) -> None:
    vs = _playbook_vars("install_slack_mcp.yaml", agent_type)
    assert vs["mcp_slack_sha256_map"][arch] == LINUX_EXPECTED_SHA256[arch]


@pytest.mark.parametrize("agent_type", _LINUX_AGENT_TYPES)
def test_linux_maps_have_identical_keys(agent_type: str) -> None:
    """The arch and sha256 maps must have the exact same key set —
    a mismatch would let a supported arch slip past the checksum guard."""
    vs = _playbook_vars("install_slack_mcp.yaml", agent_type)
    assert set(vs["mcp_slack_arch_map"].keys()) == set(
        vs["mcp_slack_sha256_map"].keys()
    )


@pytest.mark.parametrize("agent_type", _LINUX_AGENT_TYPES)
def test_linux_armv7l_intentionally_absent(agent_type: str) -> None:
    """korotovsky/slack-mcp-server v1.3.0 does NOT ship an armv7l asset.
    The playbook's arch guard MUST fail-fast rather than silently skip
    slack setup on armv7l zeroclaw hosts. Regression signal so a
    future addition of armv7 shipping upstream also lands here."""
    vs = _playbook_vars("install_slack_mcp.yaml", agent_type)
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


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
def test_darwin_playbook_pins_mcp_slack_version(agent_type: str) -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml", agent_type)
    assert vs["mcp_slack_version"] == "v1.3.0"


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
@pytest.mark.parametrize(("arch", "expected_asset_suffix"), DARWIN_ARCH_TARGETS)
def test_darwin_arch_map_covers_arch(
    agent_type: str, arch: str, expected_asset_suffix: str
) -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml", agent_type)
    assert vs["mcp_slack_arch_map"][arch] == expected_asset_suffix


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_darwin_sha256_map_covers_arch(agent_type: str, arch: str) -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml", agent_type)
    assert vs["mcp_slack_sha256_map"][arch] == DARWIN_EXPECTED_SHA256[arch]


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
def test_darwin_maps_have_identical_keys(agent_type: str) -> None:
    vs = _playbook_vars("install_slack_mcp_macos.yaml", agent_type)
    assert set(vs["mcp_slack_arch_map"].keys()) == set(
        vs["mcp_slack_sha256_map"].keys()
    )


# ---------------------------------------------------------------------------
# Cross-file version lockstep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
def test_linux_and_darwin_pin_same_version(agent_type: str) -> None:
    """Per agent type, both runbooks must reference the same upstream
    release, else a partially-migrated pin bump silently ships a mixed
    fleet."""
    linux = _playbook_vars("install_slack_mcp.yaml", agent_type)
    darwin = _playbook_vars("install_slack_mcp_macos.yaml", agent_type)
    assert linux["mcp_slack_version"] == darwin["mcp_slack_version"]


def test_all_linux_agents_pin_same_version() -> None:
    """#835/#836: hermes, openclaw, zeroclaw share ONE upstream binary
    at ONE version. A drift here means agent types on the same fleet
    download different builds — a debugging nightmare when only one
    agent type surfaces a bug."""
    versions = {
        atype: _playbook_vars("install_slack_mcp.yaml", atype)["mcp_slack_version"]
        for atype in _LINUX_AGENT_TYPES
    }
    unique = set(versions.values())
    assert len(unique) == 1, (
        f"Linux slack-mcp-server pin drift across agent types: {versions!r}. "
        f"All agents must reference the same upstream release."
    )


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
@pytest.mark.parametrize(
    "runbook",
    ["install_slack_mcp.yaml", "install_slack_mcp_macos.yaml"],
)
def test_render_constant_matches_playbook_pin(agent_type: str, runbook: str) -> None:
    """`_HERMES_MCP_SLACK_VERSION` in render.py is the single Python
    source of truth for the upstream pin — drift silently, hosts
    silently. Lockstep is asserted against EACH runbook directly (per
    AGENTS.md §"Integration Binary Install" Rule 8): a transitive
    assertion via the separate Linux ↔ darwin equality test would
    silently fail to catch a darwin-only regression if the intermediate
    test were renamed or skipped.

    #835 note: the constant is named after hermes historically, but it
    is now the shared pin for BOTH hermes and openclaw slack-mcp-server
    installs. A future rename to `_MCP_SLACK_VERSION` is out of scope
    for Phase 2; the openclaw runbook references the same value via
    this test's direct assertion."""
    from clawrium.core.render import _HERMES_MCP_SLACK_VERSION

    vs = _playbook_vars(runbook, agent_type)
    assert _HERMES_MCP_SLACK_VERSION == vs["mcp_slack_version"]


def test_render_constant_matches_zeroclaw_linux_runbook_pin() -> None:
    """#836: Zeroclaw ships only the Linux runbook at v26.7 — darwin
    sibling deferred. Direct assertion so a rename or skip of the
    parametrized `test_render_constant_matches_playbook_pin` cannot
    silently break the zeroclaw lockstep."""
    from clawrium.core.render import _HERMES_MCP_SLACK_VERSION

    vs = _playbook_vars("install_slack_mcp.yaml", "zeroclaw")
    assert _HERMES_MCP_SLACK_VERSION == vs["mcp_slack_version"]


# ---------------------------------------------------------------------------
# AGENTS.md §"Integration Binary Install" Rule 2 regression guard.
# ---------------------------------------------------------------------------


def _runbook_tasks(runbook: str, agent_type: str = "hermes") -> list[dict]:
    """Load the runbook's task list via YAML parse — lets us assert
    structural properties (task-0 position, task action, `when:`
    clauses) instead of hoping a line-scan catches every regression."""
    path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / agent_type
        / "playbooks"
        / runbook
    )
    data = yaml.safe_load(path.read_text())
    return data[0]["tasks"]


@pytest.mark.parametrize("agent_type", _AGENT_TYPES)
@pytest.mark.parametrize(
    "runbook",
    ["install_slack_mcp.yaml", "install_slack_mcp_macos.yaml"],
)
def test_runbook_has_single_task0_dispatcher_guard(agent_type: str, runbook: str) -> None:
    """Rule 2 narrow exception: each runbook is permitted exactly ONE
    `when: ansible_os_family` clause, and it MUST be at task-0
    position, and it MUST fire only `ansible.builtin.fail` (not
    conditionally install anything — that would reintroduce OS
    branching inside install tasks).

    ATX iter-4 W1 introduced a line-scan version of this test; iter-5
    W3 upgraded to YAML parsing so all three sub-invariants (single
    guard, task-0 position, `fail:` action) are enforced structurally.
    """
    tasks = _runbook_tasks(runbook, agent_type)

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


def test_zeroclaw_linux_runbook_has_task0_dispatcher_guard() -> None:
    """#836: Zeroclaw ships only the Linux runbook — same Rule 2
    task-0 dispatcher-contract guard contract applies. Direct test
    because the parametrized `test_runbook_has_single_task0_dispatcher_guard`
    scopes to `_AGENT_TYPES` (hermes + openclaw, which have both
    Linux + darwin siblings)."""
    tasks = _runbook_tasks("install_slack_mcp.yaml", "zeroclaw")

    guarded = [
        t
        for t in tasks
        if "ansible_os_family" in str(t.get("when", ""))
    ]
    assert len(guarded) == 1
    assert tasks[0] is guarded[0]

    guard_action_keys = [
        k
        for k in tasks[0].keys()
        if k not in {"name", "when", "become", "become_user", "no_log"}
    ]
    assert guard_action_keys == ["ansible.builtin.fail"]
