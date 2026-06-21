"""Workspace overlay bidi-safety regression (issue #760 W3 iter-3).

A workspace filename containing U+202E (RTL override) must reach the
NDJSON path field and the text-mode banner with the bidi marker
stripped. Otherwise a malicious `evil-‮gpj.exe` renders as
`evil-exe.jpg` in operator terminals — the spoof class iter-3 W3 calls
out explicitly.
"""

from __future__ import annotations

from clawrium.cli.output._sanitize import sanitize_passthrough
from clawrium.core.workspace_sync import _emit_excluded, _emit_skip


def test_emit_excluded_strips_bidi_from_path() -> None:
    captured: list[dict] = []

    def cb(stage: str, payload: dict) -> None:
        captured.append(payload)

    bidi_name = "evil-‮gpj.exe"
    _emit_excluded(cb, bidi_name, agent_type_excl=True)
    assert captured
    assert "‮" not in captured[0]["path"]
    # Sanity: sanitizer collapses the codepoint, leaving the rest.
    assert captured[0]["path"] == sanitize_passthrough(bidi_name)


def test_emit_skip_strips_bidi_from_path() -> None:
    captured: list[dict] = []

    def cb(stage: str, payload: dict) -> None:
        captured.append(payload)

    bidi_name = "secret-‮fdp.png"
    _emit_skip(cb, bidi_name, reason="symlink")
    assert captured
    assert "‮" not in captured[0]["path"]
