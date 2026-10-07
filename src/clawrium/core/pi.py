"""Bounded OpenRouter selection and private activation for Pi agents.

Pi 0.73.1 accepts a provider/model pair directly on its CLI.  Clawrium owns
that selection: this module accepts only the Pi-supported OpenRouter provider
and a conservative OpenRouter model ID grammar; credentials never enter the
agent record or a rendered diff.
"""

from __future__ import annotations

import fcntl
import os
import re
import threading
from contextlib import contextmanager
from clawrium.core.config import init_config_dir

__all__ = [
    "PI_OPENROUTER_ENVIRONMENT_PATH",
    "PiProvisioningError",
    "pi_credential_lock",
    "pi_chat_argv",
    "render_openrouter_environment",
    "validate_openrouter_provider",
]

PI_OPENROUTER_ENVIRONMENT_PATH = ".pi/agent/clawrium-openrouter.env"
_PI_LOCK_STATE = threading.local()
# Provider/model IDs accepted by OpenRouter and Pi's 0.73.1 custom-model
# fallback.  Reject whitespace, option-like values, provider prefixes, and
# shell/control characters rather than passing arbitrary model syntax through.
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


@contextmanager
def pi_credential_lock(agent_name: str):
    """Serialize Pi credential lifecycle actions across local CLI processes."""
    held = getattr(_PI_LOCK_STATE, "held", {})
    if agent_name in held:
        held[agent_name] += 1
        _PI_LOCK_STATE.held = held
        try:
            yield
        finally:
            held[agent_name] -= 1
        return
    lock_dir = init_config_dir() / "locks"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(str(lock_dir / f"pi-{agent_name}.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        held[agent_name] = 1
        _PI_LOCK_STATE.held = held
        yield
    finally:
        held.pop(agent_name, None)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class PiProvisioningError(ValueError):
    """A Pi provider selection cannot be provisioned safely."""


def validate_openrouter_provider(provider: object) -> str:
    """Return the selected Pi model or raise a secret-free actionable error."""
    if not isinstance(provider, dict) or provider.get("type") != "openrouter":
        raise PiProvisioningError(
            "Pi supports only an OpenRouter provider; attach a registered openrouter provider"
        )
    model = provider.get("default_model")
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        raise PiProvisioningError(
            "Pi requires a supported OpenRouter default_model (1-192 characters: letters, digits, '.', '_', ':', '/', '-'); "
            "set one with `clawctl provider registry update <provider> --model <model-id>`"
        )
    # `--provider openrouter --model <id>` is the pinned Pi protocol. A
    # provider prefix would make selection ambiguous and lets a caller escape
    # the control-plane provider boundary.
    if model.startswith("openrouter/"):
        raise PiProvisioningError(
            "Pi OpenRouter model IDs must not include the 'openrouter/' provider prefix"
        )
    return model


def render_openrouter_environment(api_key: str | None) -> str:
    """Render the only secret-bearing Pi artifact for the dedicated account."""
    if not isinstance(api_key, str) or any(
        ord(char) < 32 or ord(char) == 127 for char in api_key
    ):
        raise PiProvisioningError(
            "OpenRouter provider API key contains unsupported control characters"
        )
    key = api_key
    if not key:
        raise PiProvisioningError(
            "OpenRouter provider is missing API key in secrets.json; set it with `clawctl provider registry update <provider> --api-key-stdin`"
        )
    # No shell quoting is required or desirable: the playbooks read this as a
    # line-oriented environment file, never shell source it.
    return f"OPENROUTER_API_KEY={key}\n"


def pi_chat_argv(model: str, session_id: str, *, resume: bool) -> list[str]:
    """Build fixed Pi print-mode argv; all caller values are validated first."""
    validated_model = validate_openrouter_provider(
        {"type": "openrouter", "default_model": model}
    )
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,35}", session_id):
        raise PiProvisioningError("Pi chat session is invalid")
    argv = [
        "--provider",
        "openrouter",
        "--model",
        validated_model,
        "--print",
        "--no-tools",
        "--no-context-files",
        "--no-extensions",
    ]
    # Each browser/CLI conversation gets an isolated session directory. Pi
    # creates the first session implicitly; later turns use --continue inside
    # that directory rather than attempting to resume a UUID that does not yet
    # exist on the first turn.
    argv.extend(["--session-dir", f".pi/agent/clawrium-sessions/{session_id}"])
    if resume:
        argv.append("--continue")
    return argv
