"""Channel storage operations for Clawrium.

Channels are chat surfaces (Discord, Slack) that agents can attach to
for incoming messages. This module is the canonical storage layer:
`~/.config/clawrium/channels.json` is created and mutated through the
functions exported here.

This is the **one deliberate `clawrium.core.*` addition** introduced by
issue #509 (Bundle 4 of #435). The plan §2 guardrail forbids
*modifying* existing `core.*` modules; adding a brand-new module is
explicitly allowed and documented in plan §8 / the bundle's PR
description (Risk R1).

The on-disk schema (per plan §8):

```yaml
name: my-discord
type: discord
credentials:
  bot_token: <stored separately via clawrium.core.secrets>
config:
  allowed_users:    [<id>, <id>]
  allowed_channels: [<id>]
  allowed_guilds:   [<id>]            # discord only
  home_channel:     <id>              # slack only
  require_mention:  true
  stream_mode:      replace | append
  stream_delay_ms:  100
```

Tokens are NEVER written to `channels.json` in plaintext — they are
stored via `clawrium.core.secrets:set_instance_secret` under the
instance key `channel:<name>`, mirroring the
`provider:<name>` / `integration:<name>` convention.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

from clawrium.core.config import get_config_dir, init_config_dir

__all__ = [
    "CHANNELS_FILE",
    "CHANNEL_TYPES",
    "ChannelInUseError",
    "ChannelsFileCorruptedError",
    "DuplicateChannelError",
    "InvalidChannelNameError",
    "InvalidChannelTypeError",
    "InvalidStreamModeError",
    "add_agent_channel",
    "add_channel",
    "find_agents_using_channel",
    "get_agent_channels",
    "get_channel",
    "get_channel_instance_key",
    "get_channel_token",
    "load_channels",
    "remove_agent_channel",
    "remove_channel",
    "remove_channel_credentials",
    "set_agent_channels",
    "set_channel_token",
    "update_channel",
    "validate_channel_name",
    "validate_channel_type",
    "validate_stream_mode",
]


CHANNELS_FILE = "channels.json"

# Channel name pattern mirrors provider/integration: starts with letter,
# alphanumeric/underscore/hyphen, 1-64 chars.
CHANNEL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

CHANNEL_TYPES: tuple[str, ...] = ("discord", "slack")
STREAM_MODES: tuple[str, ...] = ("replace", "append")

# Discord/Slack ID format: numeric strings (snowflakes for Discord, ID
# strings for Slack). We accept any non-empty string but reject:
#
#   - ASCII control chars  (\x00-\x1f, \x7f-\x9f)
#   - Bidi / zero-width / paragraph-separator codepoints (U+202A-202E,
#     U+2066-2069, U+200E, U+200F, U+200B-200D, U+2028, U+2029,
#     U+FEFF, U+061C, U+2060)
#
# ATX iter-2 W4: prior incidents (#341 v3 / #455 W2) showed that
# allowing bidi-override codepoints into stored identifiers lets an
# attacker reverse-print the terminal when the value is later echoed
# (e.g. by `clawctl channel registry describe`). The pattern below is
# explicit `\uXXXX` text escapes only — literal bidi / zero-width
# codepoints MUST NOT appear in this source (see
# `cli/output/_sanitize.py` for the matching contract).
_ID_FORBIDDEN = re.compile(
    "["
    "\x00-\x1f\x7f-\x9f"
    "\u061c"  # ARABIC LETTER MARK
    "\u200b-\u200f"  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u2028-\u2029"  # LINE / PARAGRAPH SEPARATOR
    "\u202a-\u202e"  # LRE, RLE, PDF, LRO, RLO
    "\u2060"  # WORD JOINER
    "\u2066-\u2069"  # LRI, RLI, FSI, PDI
    "\ufeff"  # ZWNBSP / BOM
    "]"
)


class ChannelsFileCorruptedError(Exception):
    """Raised when channels.json cannot be parsed."""


class DuplicateChannelError(Exception):
    """Raised when adding a channel name that already exists."""


class InvalidChannelTypeError(Exception):
    """Raised when an unsupported channel type is supplied."""


class InvalidChannelNameError(Exception):
    """Raised when a channel name fails the validation pattern."""


class InvalidStreamModeError(Exception):
    """Raised when stream_mode is not one of the supported tokens."""


class ChannelInUseError(Exception):
    """Raised when removing a channel still attached to one or more agents."""


def validate_channel_name(name: str | None) -> None:
    if not isinstance(name, str):
        raise InvalidChannelNameError("Channel name must be a string")
    if not CHANNEL_NAME_PATTERN.match(name):
        raise InvalidChannelNameError(
            f"Invalid channel name '{name}'. "
            "Must start with a letter, contain only alphanumeric characters, "
            "underscores, or hyphens, and be 1-64 characters long."
        )


def validate_channel_type(channel_type: str) -> None:
    if channel_type not in CHANNEL_TYPES:
        valid = ", ".join(CHANNEL_TYPES)
        raise InvalidChannelTypeError(
            f"Invalid channel type '{channel_type}'. Valid types: {valid}"
        )


def validate_stream_mode(mode: str | None) -> None:
    if mode is None:
        return
    if mode not in STREAM_MODES:
        valid = ", ".join(STREAM_MODES)
        raise InvalidStreamModeError(
            f"Invalid stream_mode '{mode}'. Valid values: {valid}"
        )


def _validate_id_list(items: list[str] | None, field: str) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError(f"{field} must be a list")
    out: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} entries must be non-empty strings")
        if _ID_FORBIDDEN.search(item):
            raise ValueError(f"{field} entries must not contain control characters")
        out.append(item.strip())
    return out


# ---------------------------------------------------------------------------
# Token storage (delegates to clawrium.core.secrets)
# ---------------------------------------------------------------------------


def get_channel_instance_key(channel_name: str) -> str:
    """Return the per-channel secret-store instance key."""
    return f"channel:{channel_name}"


def set_channel_token(channel_name: str, key: str, value: str) -> bool:
    """Store one channel credential value under the channel's instance key.

    `key` is the credential field name (`BOT_TOKEN`, `APP_TOKEN`).
    Returns `True` if a new entry was created, `False` on update.
    """
    from clawrium.core.secrets import set_instance_secret

    return set_instance_secret(
        get_channel_instance_key(channel_name),
        key,
        value,
        description=f"{key} for channel {channel_name}",
    )


def get_channel_token(channel_name: str, key: str = "BOT_TOKEN") -> str | None:
    """Retrieve one credential for a channel from the secret store."""
    from clawrium.core.secrets import get_instance_secrets

    secrets = get_instance_secrets(get_channel_instance_key(channel_name))
    entry = secrets.get(key)
    if not isinstance(entry, dict):
        return None
    return entry.get("value")


def remove_channel_credentials(channel_name: str) -> bool:
    """Remove every secret stored against this channel's instance key."""
    from clawrium.core.secrets import remove_instance_secrets

    return remove_instance_secrets(get_channel_instance_key(channel_name))


# ---------------------------------------------------------------------------
# channels.json read/write
# ---------------------------------------------------------------------------


def load_channels() -> list[dict]:
    """Load channels from `~/.config/clawrium/channels.json` (or `[]`)."""
    path = get_config_dir() / CHANNELS_FILE
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ChannelsFileCorruptedError(f"channels.json is not a list: {path}")
            if not all(isinstance(c, dict) for c in data):
                raise ChannelsFileCorruptedError(
                    f"channels.json contains invalid entries (expected list of objects): {path}"
                )
            return data
    except json.JSONDecodeError as exc:
        raise ChannelsFileCorruptedError(
            f"channels.json is corrupted: {exc}. Path: {path}"
        ) from exc


@contextmanager
def _channels_lock():
    config_dir = init_config_dir()
    lock_path = config_dir / ".channels.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _save_channels_atomic(channels: list[dict], config_dir) -> None:
    path = config_dir / CHANNELS_FILE
    fd, tmp = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(channels, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add_channel(channel: dict) -> None:
    """Add a channel to `channels.json` atomically.

    Caller is responsible for storing the token via `set_channel_token`
    *after* this returns successfully so a duplicate-name error leaves
    no orphan secret in the secrets store.
    """
    name = channel.get("name")
    validate_channel_name(name)
    ctype = channel.get("type")
    if ctype:
        validate_channel_type(ctype)
    cfg = channel.get("config") or {}
    if "stream_mode" in cfg:
        validate_stream_mode(cfg.get("stream_mode"))

    with _channels_lock():
        channels = load_channels()
        for existing in channels:
            if existing.get("name") == name:
                raise DuplicateChannelError(f"Channel '{name}' already exists")

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        channel.setdefault("created_at", now)
        channel.setdefault("updated_at", now)
        channels.append(channel)

        config_dir = init_config_dir()
        _save_channels_atomic(channels, config_dir)


def get_channel(name: str) -> dict | None:
    """Return a channel record by name, or `None`."""
    for c in load_channels():
        if c.get("name") == name:
            return c
    return None


def update_channel(name: str, updater: Callable[[dict], dict]) -> bool:
    """Apply `updater` to the channel record under the same lock as a write."""
    with _channels_lock():
        channels = load_channels()
        found = False
        for i, c in enumerate(channels):
            if c.get("name") == name:
                channels[i] = updater(c)
                found = True
                break
        if found:
            config_dir = init_config_dir()
            _save_channels_atomic(channels, config_dir)
        return found


def find_agents_using_channel(channel_name: str) -> list[tuple[str, str]]:
    """Return `(hostname, agent_key)` tuples for every agent attached to this channel."""
    from clawrium.core.hosts import load_hosts

    out: list[tuple[str, str]] = []
    for host in load_hosts():
        hostname = host.get("hostname", "")
        agents = host.get("agents", {}) or {}
        for agent_key, agent_data in agents.items():
            if not isinstance(agent_data, dict):
                continue
            attached = agent_data.get("channels", [])
            if isinstance(attached, list) and channel_name in attached:
                out.append((hostname, agent_key))
    return out


def remove_channel(name: str, force: bool = False) -> bool:
    """Delete a channel record (and its stored credentials).

    Raises `ChannelInUseError` when `force=False` and at least one
    agent still attaches the channel — mirror of integrations.py.
    """
    with _channels_lock():
        if not force:
            attached = find_agents_using_channel(name)
            if attached:
                snippet = ", ".join(f"{h}:{a}" for h, a in attached[:3])
                if len(attached) > 3:
                    snippet += f" and {len(attached) - 3} more"
                raise ChannelInUseError(
                    f"Channel '{name}' is attached to agents: {snippet}. "
                    "Detach first or use force=True."
                )

        channels = load_channels()
        remaining = [c for c in channels if c.get("name") != name]
        if len(remaining) == len(channels):
            return False

        # Remove credentials before the JSON record so a crash between
        # the two cannot leave orphan secrets for a same-name re-add.
        remove_channel_credentials(name)

        # ATX iter-2 W7 / W-NEW-3: an OSError during the atomic write
        # here leaves the channel record present but with credentials
        # already cleared — a zombie state. The CLI surface catches
        # this and surfaces an actionable error, but we also log the
        # state explicitly so it's visible in journals/aggregators
        # even when the call is non-CLI.
        try:
            config_dir = init_config_dir()
            _save_channels_atomic(remaining, config_dir)
        except OSError as exc:
            import logging

            logging.getLogger(__name__).warning(
                "remove_channel: channel %r is now in a zombie state "
                "(record present, credentials gone). channels.json "
                "write failed: %s. Re-run delete --force to complete.",
                name,
                exc,
            )
            raise

    return True


# ---------------------------------------------------------------------------
# Per-agent attachments
# ---------------------------------------------------------------------------


def get_agent_channels(host: str, agent_key: str) -> list[str]:
    """Return the list of channel names attached to a given agent."""
    from clawrium.core.hosts import get_host

    host_data = get_host(host)
    if not host_data:
        return []
    agents = host_data.get("agents", {}) or {}
    if agent_key not in agents:
        return []
    record = agents[agent_key]
    if not isinstance(record, dict):
        return []
    attached = record.get("channels", [])
    if not isinstance(attached, list):
        return []
    return list(attached)


def set_agent_channels(host: str, agent_key: str, channels: list[str]) -> bool:
    """Replace the list of attached channels for an agent.

    ATX iter-2 W8: `update_host` returns `True` whenever the host is
    found, even if the updater did not actually mutate the agents map
    (agent_key missing, record not a dict). Tracking the mutation via
    a `nonlocal updated` flag prevents a false-positive success return
    on a no-op write.
    """
    from clawrium.core.hosts import get_host, update_host

    host_data = get_host(host)
    if not host_data:
        return False

    hostname = host_data["hostname"]
    updated = False

    def updater(h: dict) -> dict:
        nonlocal updated
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h
        record = agents[agent_key]
        if not isinstance(record, dict):
            return h
        record["channels"] = list(channels)
        updated = True
        return h

    update_host(hostname, updater)
    return updated


def add_agent_channel(host: str, agent_key: str, channel_name: str) -> bool:
    """Attach a channel to an agent atomically.

    Returns `True` if the attachment was added, `False` if it already
    existed (or the agent could not be located).
    """
    from clawrium.core.hosts import get_host, update_host

    host_data = get_host(host)
    if not host_data:
        return False

    hostname = host_data["hostname"]
    added = False

    def updater(h: dict) -> dict:
        nonlocal added
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h
        record = agents[agent_key]
        if not isinstance(record, dict):
            return h
        current = record.get("channels", [])
        if not isinstance(current, list):
            current = []
        if channel_name in current:
            return h
        current.append(channel_name)
        record["channels"] = current
        added = True
        return h

    update_host(hostname, updater)
    return added


def remove_agent_channel(host: str, agent_key: str, channel_name: str) -> bool:
    """Detach a channel from an agent atomically. Returns `True` if removed."""
    from clawrium.core.hosts import get_host, update_host

    host_data = get_host(host)
    if not host_data:
        return False

    hostname = host_data["hostname"]
    removed = False

    def updater(h: dict) -> dict:
        nonlocal removed
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h
        record = agents[agent_key]
        if not isinstance(record, dict):
            return h
        current = record.get("channels", [])
        if not isinstance(current, list) or channel_name not in current:
            return h
        current.remove(channel_name)
        record["channels"] = current
        removed = True
        return h

    update_host(hostname, updater)
    return removed
