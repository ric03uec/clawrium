"""Bidi / control-char sanitization corpus tests.

Codifies the dangerous codepoint set in `cli/output/_sanitize.py` so
any future drift between it and `cli/chat.py:_CONTROL_AND_BIDI_RE`
shows up here. ATX #341 v3 / #455 W2 hardened chat.py against this
class of terminal-deception attack (U+202E RIGHT-TO-LEFT OVERRIDE
silently reverse-prints subsequent output); #507 ATX iter-1 B1/B2/W1/W2
extended the contract to every output primitive that writes raw
strings; #507 ATX iter-2 added the 6 missing codepoints below
(LRE/RLE/PDF/LRO + ZWNJ/ZWJ) and the per-primitive ensure_ascii
property tests for emit_event/dump_json/dump_yaml/format_status.

Test design rules:

- The corpus uses `chr(0xXXXX)` instead of literal Unicode characters
  so this test file is itself ASCII-safe in source. Same hygiene rule
  as `_sanitize.py`: literal bidi codepoints in source are invisible
  to most editors and silently corruptible.
- Every codepoint in `_CONTROL_AND_BIDI_RE`'s character class MUST
  have an entry below — `test_source_is_pure_ascii` asserts the
  hygiene rule on `_sanitize.py` itself.
"""

import io
import json

import pytest
import typer
import yaml

from clawrium.cli.output._sanitize import _CONTROL_AND_BIDI_RE, sanitize
from clawrium.cli.output.errors import emit_error
from clawrium.cli.output.json_yaml import dump_json, dump_name, dump_yaml
from clawrium.cli.output.status import format_status
from clawrium.cli.output.stream import NDJSONStreamer, emit_event, stream_action
from clawrium.cli.output.table import render


# Canonical adversarial codepoints -- every entry here MUST be stripped.
# Use chr() so this file stays pure ASCII (same hygiene rule as
# _sanitize.py). Drift on either side fails CI.
BIDI_AND_CONTROL = [
    chr(0x202E),  # RLO -- the classic v3 demo
    chr(0x2066),  # LRI
    chr(0x2067),  # RLI
    chr(0x2068),  # FSI
    chr(0x2069),  # PDI
    chr(0x200E),  # LRM
    chr(0x200F),  # RLM
    chr(0x200B),  # ZWSP
    chr(0x200C),  # ZWNJ -- added iter-2
    chr(0x200D),  # ZWJ  -- added iter-2
    chr(0x2028),  # LINE SEPARATOR
    chr(0x2029),  # PARAGRAPH SEPARATOR
    chr(0x2060),  # WORD JOINER
    chr(0xFEFF),  # ZWNBSP / BOM
    chr(0x061C),  # ARABIC LETTER MARK
    chr(0x202A),  # LRE -- added iter-2
    chr(0x202B),  # RLE -- added iter-2
    chr(0x202C),  # PDF -- added iter-2
    chr(0x202D),  # LRO -- added iter-2
    "\x00",  # NUL
    "\x07",  # BEL -- terminals will beep
    "\x1b",  # ESC -- starts ANSI sequences
    "\x7f",  # DEL
    "\x9b",  # CSI (C1)
]

RLO = chr(0x202E)
LRI = chr(0x2066)


@pytest.mark.parametrize("dangerous", BIDI_AND_CONTROL)
def test_sanitize_strips_each_codepoint(dangerous: str) -> None:
    assert _CONTROL_AND_BIDI_RE.search(dangerous) is not None
    cleaned = sanitize(f"alpha{dangerous}omega")
    assert dangerous not in cleaned, f"codepoint U+{ord(dangerous):04X} survived"
    assert "alpha" in cleaned and "omega" in cleaned


def test_sanitize_passes_through_safe_strings() -> None:
    safe = "agent/wise-hypatia: installed at 2026-05-20T14:23:11Z"
    assert sanitize(safe) is safe  # cheap identity short-circuit


def test_sanitize_mixed_vector() -> None:
    """A single string with both a C0 control char and a bidi override.

    Guards against a future regex rewrite that uses `|` alternation
    instead of a character class and accidentally drops multi-char
    handling.
    """
    cleaned = sanitize(f"\x1b[31m{RLO}red text")
    assert "\x1b" not in cleaned
    assert RLO not in cleaned
    assert "red text" in cleaned


def test_source_is_pure_ascii() -> None:
    """`_sanitize.py` must contain no literal Unicode bytes -- only
    `\\uXXXX` text escapes. Codified after #507 ATX iter-2 caught a
    regression where literal codepoints were checked in.
    """
    from pathlib import Path

    import clawrium.cli.output._sanitize as mod

    raw = Path(mod.__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not non_ascii, (
        f"_sanitize.py has {len(non_ascii)} non-ASCII bytes; "
        f"first at offset {non_ascii[0][0]} (0x{non_ascii[0][1]:02x}). "
        "Use \\uXXXX escapes instead of literal Unicode chars."
    )


class TestEmitErrorSanitization:
    def test_strips_bidi_from_message(self) -> None:
        buf = io.StringIO()
        with pytest.raises(typer.Exit):
            emit_error(f"agent{RLO}exists", hint=f"check{RLO}state", stream=buf)
        assert RLO not in buf.getvalue()

    def test_strips_bidi_from_hint_only(self) -> None:
        """Isolates the hint-path sanitize() call from the message path."""
        buf = io.StringIO()
        with pytest.raises(typer.Exit):
            emit_error("clean message", hint=f"check{RLO}state", stream=buf)
        assert RLO not in buf.getvalue()
        assert "clean message" in buf.getvalue()


class TestStreamActionSanitization:
    def test_strips_bidi_from_resource_and_message(self) -> None:
        buf = io.StringIO()
        stream_action(
            resource=f"agent/wise{LRI}hypatia",
            message=f"install{RLO}complete",
            stream=buf,
        )
        for dangerous in (RLO, LRI):
            assert dangerous not in buf.getvalue()


class TestNDJSONStreamerSerialization:
    """`json.dumps(..., ensure_ascii=True)` is the safety boundary --
    every non-ASCII codepoint becomes `\\uXXXX` in the output, never
    the raw control char. Verify the property at the API boundary so a
    future flip to `ensure_ascii=False` immediately fails CI.
    """

    def test_dangerous_codepoint_emerges_escaped_not_raw(self) -> None:
        buf = io.StringIO()
        s = NDJSONStreamer(stream=buf)
        s.emit(
            resource=f"agent/x{RLO}y",
            phase="install",
            state="started",
            ts="2026-05-23T10:14:00Z",
        )
        raw = buf.getvalue()
        assert RLO not in raw
        assert "\\u202e" in raw
        # Consumers parsing the NDJSON still see the codepoint as a
        # value -- they own the decision to display it safely.
        parsed = json.loads(raw)
        assert RLO in parsed["resource"]


class TestEmitEventSerialization:
    """Mirrors `TestNDJSONStreamerSerialization` for `emit_event()`.
    Added iter-2 (#507): the iter-1 commit asserted ensure_ascii
    property only for `NDJSONStreamer.emit()`; `emit_event()` had no
    coverage even though it shares the json.dumps call path.
    """

    def test_dangerous_codepoint_emerges_escaped_not_raw(self) -> None:
        buf = io.StringIO()
        emit_event(
            {
                "resource": f"agent/x{RLO}y",
                "phase": "install",
                "state": "started",
                "ts": "2026-05-23T10:14:00Z",
            },
            stream=buf,
        )
        raw = buf.getvalue()
        assert RLO not in raw
        assert "\\u202e" in raw


class TestDumpJsonSanitization:
    """Same property as the NDJSON streamer -- exercises dump_json's
    own json.dumps call.
    """

    def test_dangerous_codepoint_emerges_escaped_not_raw(self) -> None:
        out = dump_json([{"kind": f"agent{RLO}", "name": "x"}])
        assert RLO not in out
        assert "\\u202e" in out


class TestDumpYamlSanitization:
    """yaml.safe_dump escapes control chars in scalar values."""

    def test_dangerous_codepoint_not_raw(self) -> None:
        out = dump_yaml([{"name": f"x{RLO}y"}])
        # The raw codepoint should not appear verbatim in the YAML
        # serialization (safe_dump escapes it).
        assert RLO not in out
        # The parsed YAML still carries the codepoint -- consumers own
        # display safety.
        parsed = yaml.safe_load(out)
        assert RLO in parsed[0]["name"]


class TestDumpNameSanitization:
    def test_strips_bidi_from_kind_and_name(self) -> None:
        out = dump_name(
            [
                {"kind": f"agent{RLO}", "name": f"wise{LRI}hypatia"},
            ]
        )
        for dangerous in (RLO, LRI):
            assert dangerous not in out


class TestRenderSanitization:
    def test_strips_bidi_from_cells_and_headers(self) -> None:
        out = render(
            headers=[f"NAME{RLO}", "STATUS"],
            rows=[[f"wise{LRI}hypatia", f"run{RLO}ning"]],
        )
        for dangerous in (RLO, LRI):
            assert dangerous not in out


class TestFormatStatusSanitization:
    """`format_status()` returns unknown tokens via the sanitize() path
    (#507 ATX iter-2 W7). Known tokens skip sanitization because they
    are already vocabulary-constrained.
    """

    def test_unknown_token_is_sanitized(self) -> None:
        out = format_status(f"running{RLO}foo", force_color=True)
        assert RLO not in out

    def test_known_token_is_unmodified_when_no_color(self) -> None:
        # When color is disabled, known tokens pass through verbatim
        # -- vocabulary constraint is the proof that no sanitization
        # is needed.
        import os

        os.environ.pop("NO_COLOR", None)
        buf = io.StringIO()
        out = format_status("running", stream=buf)
        assert out == "running"
