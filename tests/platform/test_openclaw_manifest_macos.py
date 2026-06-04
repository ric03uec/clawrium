"""Manifest entry tests for openclaw on darwin/arm64 (issue #604)."""

from pathlib import Path

import yaml


def _manifest() -> dict:
    path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / "openclaw"
        / "manifest.yaml"
    )
    return yaml.safe_load(path.read_text())


def test_openclaw_manifest_has_macos_arm64_entry():
    platforms = _manifest()["platforms"]
    macos_entries = [
        p for p in platforms if p.get("os") == "macos" and p.get("arch") == "arm64"
    ]
    assert macos_entries, "expected at least one macos/arm64 platform entry"
    entry = macos_entries[0]
    assert entry["os_version"].startswith(">=")
    assert entry["requirements"]["gpu_required"] is False


def test_openclaw_manifest_web_ui_resolver_contract():
    """web_ui fields drive `clawctl agent open` routing — assert the
    bundled openclaw manifest declares the resolver-required shape."""
    web_ui = _manifest()["features"]["web_ui"]
    assert web_ui["enabled"] is True
    assert web_ui["bind"] == "wildcard"
    assert web_ui["port_field"] == "gateway.port"
    # Per AGENTS.md `Native Dashboards`, bundled manifests must NOT set
    # default_port — install.py picks a per-instance port instead.
    assert "default_port" not in web_ui


def test_openclaw_manifest_has_no_macos_x86_64_entry():
    """darwin/x86_64 is intentionally unsupported — guard against silent
    fallback to a linux/x86_64 entry on Intel Macs."""
    platforms = _manifest()["platforms"]
    assert not [
        p
        for p in platforms
        if p.get("os") == "macos" and p.get("arch") == "x86_64"
    ]
