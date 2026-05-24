"""NDJSON action streamer for `-o json` on lifecycle commands.

Plan §6.9: actions stream events to stdout, one JSON object per line,
each with at least `resource`, `phase`, `state`, `ts` keys. Extra keys
are passed through.

`stream_action()` is a convenience for the default (non-JSON) mode —
one human line per phase, e.g. `agent/wise-hypatia: installed`. Both
`resource` and `message` are bidi/control-char sanitized here (#507
ATX iter-1 B2): they will carry server-supplied strings (agent names
from hosts.json, ansible event text) once bundles 3-4 wire real
lifecycle ops to this primitive.

`NDJSONStreamer.emit()` and `emit_event()` are safe by serialization:
`json.dumps(..., ensure_ascii=True)` escapes control chars as `\\uXXXX`
in the output. Future audit point — if a caller passes a secret-valued
extra kwarg, it would still be serialized to the stream; this is
flagged for review when the first real caller lands in bundle 3.
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any, IO, Mapping, Optional

from clawrium.cli.output._sanitize import sanitize


def _utc_now_rfc3339() -> str:
    """Return the current UTC time as RFC3339 (`2026-05-23T10:14:00Z`)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NDJSONStreamer:
    """Emit one JSON object per line to a stream (default `sys.stdout`).

    The streamer is intentionally minimal — no buffering beyond the
    underlying stream's, no schema enforcement beyond the required keys.
    """

    REQUIRED_KEYS = ("resource", "phase", "state")

    def __init__(self, stream: Optional[IO[str]] = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def emit(
        self,
        *,
        resource: str,
        phase: str,
        state: str,
        ts: Optional[str] = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "resource": resource,
            "phase": phase,
            "state": state,
            "ts": ts if ts is not None else _utc_now_rfc3339(),
        }
        for key, value in extra.items():
            payload[key] = value
        # `ensure_ascii=True` is the explicit safety boundary cited in
        # `_sanitize.py` -- every non-ASCII codepoint becomes `\\uXXXX`
        # in the output, so raw bidi/control chars never reach the
        # terminal even though we don't call sanitize() here. Removing
        # this kwarg would silently regress the contract.
        self._stream.write(
            json.dumps(payload, sort_keys=False, ensure_ascii=True) + "\n"
        )
        self._stream.flush()


def stream_action(
    *,
    resource: str,
    message: str,
    stream: Optional[IO[str]] = None,
) -> None:
    """Emit one human-readable phase line: `<resource>: <message>`.

    Counterpart to `NDJSONStreamer.emit()` for the default (non-JSON)
    output mode. Flushes immediately so phase lines appear interleaved
    with whatever the underlying lifecycle code logs.
    """
    target = stream if stream is not None else sys.stdout
    target.write(f"{sanitize(resource)}: {sanitize(message)}\n")
    target.flush()


def emit_event(event: Mapping[str, Any], stream: Optional[IO[str]] = None) -> None:
    """Emit a pre-built event mapping as a single NDJSON line.

    Convenience for callers that already have the event payload in
    dict form (e.g. forwarded from a backend). Validates the required
    keys before writing — missing keys raise `KeyError` so the caller
    learns immediately.
    """
    for key in NDJSONStreamer.REQUIRED_KEYS:
        if key not in event:
            raise KeyError(f"missing required key: {key}")
    target = stream if stream is not None else sys.stdout
    # `ensure_ascii=True` is the explicit safety boundary -- see the
    # matching comment in `NDJSONStreamer.emit()`.
    target.write(json.dumps(dict(event), sort_keys=False, ensure_ascii=True) + "\n")
    target.flush()
