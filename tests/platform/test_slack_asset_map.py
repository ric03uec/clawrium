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


@pytest.mark.parametrize(
    ("runbook", "acceptable_guards"),
    [
        # Linux runbook: fail if ansible_os_family == "Darwin"
        ("install_slack_mcp.yaml", ('== "Darwin"', "== 'Darwin'")),
        # Darwin runbook: fail if not-darwin (either `!= "Darwin"` or
        # `== "Linux"` shape is acceptable — both mean the same thing).
        (
            "install_slack_mcp_macos.yaml",
            ('!= "Darwin"', "!= 'Darwin'", '== "Linux"', "== 'Linux'"),
        ),
    ],
)
def test_runbook_has_single_task0_dispatcher_guard(
    runbook: str, acceptable_guards: tuple[str, ...]
) -> None:
    """Rule 2 narrow exception: each runbook is permitted exactly ONE
    `when: ansible_os_family` clause, and it MUST be on a task that
    only `fail:`s (dispatcher-contract guard — trip loudly when the
    wrong-OS sibling was routed here by mistake). Any additional
    `ansible_os_family` clause, or one that gates an install task,
    reintroduces the OS-branching-inside-runbook invariant Rule 2
    bans. ATX iter-4 W1."""
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
    body = path.read_text()
    guards = [
        line
        for line in body.splitlines()
        if "ansible_os_family" in line and line.lstrip().startswith("when:")
    ]
    assert len(guards) == 1, (
        f"{runbook}: expected exactly ONE `when: ansible_os_family` "
        f"clause (task-0 dispatcher-contract fail-fast); found "
        f"{len(guards)}. Rule 2 bans OS branching inside install "
        f"tasks."
    )
    # The single permitted guard refuses the wrong-OS host. Accept
    # either `== "OtherOS"` or `!= "MyOS"` shape — both express the
    # same dispatcher-contract intent.
    assert any(shape in guards[0] for shape in acceptable_guards), (
        f"{runbook}: task-0 dispatcher guard must refuse the wrong "
        f"OS. Acceptable shapes: {acceptable_guards!r}. Found: "
        f"{guards[0].strip()!r}"
    )
