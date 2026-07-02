"""Tests for the slack-mcp-server per-arch install matrix.

#835 (B9): the (arch → asset filename) and (arch → sha256) maps were
lifted out of the hermes `configure.yaml` / `configure_macos.yaml`
`vars:` blocks and now live in
`clawrium.core.playbook_resolver.mcp_slack_extravars`. The extravars
are threaded into BOTH hermes and openclaw configure playbooks by
`lifecycle.configure_agent`, so a single Python location owns the
pins for four YAML files. This test suite pins the resolver contract
directly — any drift between hermes and openclaw ships as one
resolver change or fails these tests.

macOS variants keep the divergent ansible arch naming (`arm64` vs
Linux's `aarch64`) — that's a fact about how ansible reports the
darwin architecture and cannot be normalized away.
"""

from __future__ import annotations

import pytest

from clawrium.core.playbook_resolver import mcp_slack_extravars


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------


LINUX_ARCH_TARGETS = [
    ("x86_64", "linux-amd64"),
    ("aarch64", "linux-arm64"),
]

LINUX_EXPECTED_SHA256 = {
    "x86_64": "d1525962e9b9dbfdd2eaf48d0a81ca1eca7d8f1862b8d34931b812c850b3e568",
    "aarch64": "a307a48d16c2261346bdc257274cdcdb8b2027c867dc971b41d52cef36472c88",
}


def test_linux_resolver_pins_mcp_slack_version() -> None:
    vs = mcp_slack_extravars("linux")
    assert vs["mcp_slack_version"] == "v1.3.0"


@pytest.mark.parametrize(("arch", "expected_asset_suffix"), LINUX_ARCH_TARGETS)
def test_linux_arch_map_covers_arch(arch: str, expected_asset_suffix: str) -> None:
    vs = mcp_slack_extravars("linux")
    assert vs["mcp_slack_arch_map"][arch] == expected_asset_suffix


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_linux_sha256_map_covers_arch(arch: str) -> None:
    vs = mcp_slack_extravars("linux")
    assert vs["mcp_slack_sha256_map"][arch] == LINUX_EXPECTED_SHA256[arch]


def test_linux_maps_have_identical_keys() -> None:
    """The arch and sha256 maps must have the exact same key set —
    a mismatch would let a supported arch slip past the checksum guard."""
    vs = mcp_slack_extravars("linux")
    assert set(vs["mcp_slack_arch_map"].keys()) == set(
        vs["mcp_slack_sha256_map"].keys()
    )


def test_linux_armv7l_intentionally_absent() -> None:
    """korotovsky/slack-mcp-server v1.3.0 does NOT ship an armv7l asset.
    The playbook's arch guard MUST fail-fast rather than silently skip
    slack setup on armv7l zeroclaw hosts. Regression signal so a
    future addition of armv7 shipping upstream also lands here."""
    vs = mcp_slack_extravars("linux")
    assert "armv7l" not in vs["mcp_slack_arch_map"]
    assert "armv7l" not in vs["mcp_slack_sha256_map"]


# ---------------------------------------------------------------------------
# Darwin
# ---------------------------------------------------------------------------


DARWIN_ARCH_TARGETS = [
    ("arm64", "darwin-arm64"),
    ("x86_64", "darwin-amd64"),
]

DARWIN_EXPECTED_SHA256 = {
    "arm64": "e839aa5c2e28253438ed704dd862aa4afb75711d688080ce447a3b1167855312",
    "x86_64": "e38142ee628b2c2ff241f0d021947b96e743540cfb702fc8b01f61a4f7a4a125",
}


def test_darwin_resolver_pins_mcp_slack_version() -> None:
    vs = mcp_slack_extravars("darwin")
    assert vs["mcp_slack_version"] == "v1.3.0"


@pytest.mark.parametrize(("arch", "expected_asset_suffix"), DARWIN_ARCH_TARGETS)
def test_darwin_arch_map_covers_arch(arch: str, expected_asset_suffix: str) -> None:
    vs = mcp_slack_extravars("darwin")
    assert vs["mcp_slack_arch_map"][arch] == expected_asset_suffix


@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_darwin_sha256_map_covers_arch(arch: str) -> None:
    vs = mcp_slack_extravars("darwin")
    assert vs["mcp_slack_sha256_map"][arch] == DARWIN_EXPECTED_SHA256[arch]


def test_darwin_maps_have_identical_keys() -> None:
    vs = mcp_slack_extravars("darwin")
    assert set(vs["mcp_slack_arch_map"].keys()) == set(
        vs["mcp_slack_sha256_map"].keys()
    )


# ---------------------------------------------------------------------------
# Cross-OS lockstep + guardrails
# ---------------------------------------------------------------------------


def test_linux_and_darwin_pin_same_version() -> None:
    """Both OS branches must reference the same upstream release, else a
    partially-migrated pin bump silently ships a mixed fleet."""
    linux = mcp_slack_extravars("linux")
    darwin = mcp_slack_extravars("darwin")
    assert linux["mcp_slack_version"] == darwin["mcp_slack_version"]


def test_render_helper_matches_resolver_pin() -> None:
    """The render.py lazy accessor MUST resolve to the same string the
    resolver hands to Ansible — drift here would render a Jinja comment
    that names a version different from the one Ansible actually
    downloaded (silent, no error surface)."""
    from clawrium.core.render import _hermes_mcp_slack_version

    linux = mcp_slack_extravars("linux")
    assert _hermes_mcp_slack_version() == linux["mcp_slack_version"]


def test_unsupported_os_family_raises() -> None:
    with pytest.raises(ValueError, match="unsupported os_family"):
        mcp_slack_extravars("windows")


# ---------------------------------------------------------------------------
# normalize_os_family — the shared normalization seam (#835 iter-1 W2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (None, "linux"),
        ({}, "linux"),
        ({"os_family": "linux"}, "linux"),
        ({"os_family": "Linux"}, "linux"),
        ({"os_family": "  linux  "}, "linux"),
        ({"os_family": "darwin"}, "darwin"),
        ({"os_family": "Darwin"}, "darwin"),
        ({"os_family": "mac"}, "darwin"),
        ({"os_family": "macos"}, "darwin"),
        ({"os_family": "macOS"}, "darwin"),
        ({"os_family": "OSX"}, "darwin"),
        ({"os_family": "osx"}, "darwin"),
        ({"os_family": None}, "linux"),
        ({"os_family": ""}, "linux"),
    ],
)
def test_normalize_os_family_covers_documented_aliases(host, expected):
    """#835 iter-1 W2 (iter-2 blocker): the normalizer is the single
    seam consumed by `lifecycle.configure_agent`, `lifecycle_canonical`,
    and `render_openclaw`. Any drift in the alias table would ship a
    linux-only render on a darwin host, exactly the bug the seam was
    extracted to prevent."""
    from clawrium.core.playbook_resolver import normalize_os_family

    assert normalize_os_family(host) == expected


def test_normalize_os_family_passes_exotic_values_through_unchanged():
    """Values outside {linux, darwin} + the mac aliases MUST pass
    through unchanged so downstream per-API validators (`render_hermes`,
    `render_openclaw`, `mcp_slack_extravars`) can raise with a useful
    trace of the original value. Silently coercing to `linux` here
    would mask the data bug."""
    from clawrium.core.playbook_resolver import normalize_os_family

    assert normalize_os_family({"os_family": "windows"}) == "windows"
    assert normalize_os_family({"os_family": "freebsd"}) == "freebsd"


def test_returned_dict_is_a_copy_not_shared() -> None:
    """The resolver must hand back a fresh dict on every call so an
    unfortunate caller that mutates it (e.g. ansible_vars.update / pop)
    cannot poison the next configure run's extravars."""
    a = mcp_slack_extravars("linux")
    a["mcp_slack_sha256_map"]["x86_64"] = "tampered"
    b = mcp_slack_extravars("linux")
    assert b["mcp_slack_sha256_map"]["x86_64"] == LINUX_EXPECTED_SHA256["x86_64"]
