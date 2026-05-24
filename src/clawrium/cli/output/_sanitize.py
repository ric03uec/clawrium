"""Terminal-output sanitization for the `clawctl` output primitives.

The output module writes server-supplied strings (agent names from
hosts.json, ansible-runner event text, hermes HTTP response bodies,
etc.) directly to stdout/stderr. A malicious upstream emitting bidi
override codepoints (U+202E etc.) can silently reverse-print the
user's terminal output -- the exact class of bug ATX #341 v3 / #455 W2
hardened against in `cli/chat.py`.

`_CONTROL_AND_BIDI_RE` mirrors the pattern in `cli/chat.py` so the
coverage stays identical to the legacy parity contract. We re-state
the pattern here (rather than importing from chat.py) for two reasons:

1. The output module must stay self-contained -- bundles 3-5 will
   refactor `cli/chat.py` and the import could break or shift coverage.
2. Drift detection: `tests/cli/output/test_sanitize.py` codifies the
   character set; any future edit to either copy must update both,
   surfacing the drift in CI. The drift-detection guard in that file
   also asserts the source uses ASCII-only Python `\\uXXXX` escapes
   (no literal Unicode codepoints anywhere in this module).

**`sanitize()` IS NOT a secret redactor.** It only strips control and
bidi/zero-width codepoints; alphanumeric secrets (API keys, tokens)
pass through unmodified. Callers must never pass secret-valued strings
to any output primitive -- the safety boundary lives at the call site
that decides what to log, not at the writer that flushes it.

Sanitization is applied at every primitive that writes a raw string
to a terminal stream: `emit_error()`, `stream_action()`, `dump_name()`,
`render_table()` cells, and `format_status()`. `NDJSONStreamer.emit()`,
`emit_event()`, `dump_json()`, and `dump_yaml()` are safe by
serialization (json.dumps with `ensure_ascii=True` and yaml.safe_dump
escape control characters in their output).
"""

import re

_CONTROL_AND_BIDI_RE = re.compile(
    # Mirrors `cli/chat.py:_CONTROL_AND_BIDI_RE`. Explicit `\uXXXX`
    # text escapes only -- literal bidi / zero-width codepoints MUST
    # NOT appear in this source. They are invisible to most editors
    # and trivially corrupted by auto-formatters / BOM insertion /
    # careless paste. ATX iter-2 #507 caught a regression where the
    # pattern below was checked in with literal bytes; the contract
    # is now enforced by
    # `tests/cli/output/test_sanitize.py::test_source_is_pure_ascii`.
    "["
    "\x00-\x1f\x7f-\x9f"
    "\u061c"  # ARABIC LETTER MARK (UAX#9 bidi format char)
    "\u200b-\u200f"  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u2028-\u2029"  # LINE / PARAGRAPH SEPARATOR
    "\u202a-\u202e"  # LRE, RLE, PDF, LRO, RLO
    "\u2060"  # WORD JOINER
    "\u2066-\u2069"  # LRI, RLI, FSI, PDI
    "\ufeff"  # ZWNBSP / BOM
    "]"
)


def sanitize(value: str) -> str:
    """Strip control / bidi / zero-width chars; replace with a single space.

    Idempotent and pass-through for well-formed strings -- only the
    dangerous codepoints are touched. Returns the input unchanged when
    nothing matches (no allocation in the common case).

    NOTE: Whitespace control chars (`\\t`, `\\n`, `\\r`) ARE stripped
    because they fall in `\\x00-\\x1f`. This matches the chat.py parity
    contract; multi-line diagnostic structure in error messages is
    deliberately collapsed to a single line. Callers that need
    structured multi-line output should format BEFORE calling the
    sanitizer (or write to stderr in pieces with separate emit_error
    calls).
    """
    if not _CONTROL_AND_BIDI_RE.search(value):
        return value
    return _CONTROL_AND_BIDI_RE.sub(" ", value)
