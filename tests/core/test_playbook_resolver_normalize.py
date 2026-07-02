"""Tests for `clawrium.core.playbook_resolver.normalize_os_family`.

#835 (ATX iter-1 W2): the normalizer was extracted so
`lifecycle.configure_agent`'s previously-duplicated `os_family`
coercion blocks stay in lockstep. This test file directly exercises
the alias table + fallback contract so a bug in the shared seam
surfaces here (not indirectly through a downstream lifecycle test).
"""

from __future__ import annotations

import pytest

from clawrium.core.playbook_resolver import normalize_os_family


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
    """Any drift in the alias table would ship a linux-only render on
    a darwin host, exactly the bug the seam was extracted to prevent."""
    assert normalize_os_family(host) == expected


def test_normalize_os_family_passes_exotic_values_through_unchanged():
    """Values outside {linux, darwin} + the mac aliases MUST pass
    through unchanged so downstream per-API validators (`render_hermes`,
    `render_openclaw`) can raise with a useful trace of the original
    value. Silently coercing to `linux` here would mask the data bug."""
    assert normalize_os_family({"os_family": "windows"}) == "windows"
    assert normalize_os_family({"os_family": "freebsd"}) == "freebsd"
