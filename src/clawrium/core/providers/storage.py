"""Provider storage operations for Clawrium."""

import fcntl
import ipaddress
import json
import os
import re
import socket
import tempfile
from contextlib import contextmanager
from typing import Callable
from urllib.parse import urlparse

import requests

from clawrium.core.config import get_config_dir, init_config_dir

__all__ = [
    "PROVIDERS_FILE",
    "PROVIDER_MODELS",
    "load_providers",
    "save_providers",
    "add_provider",
    "get_provider",
    "update_provider",
    "remove_provider",
    "validate_provider_name",
    "validate_provider_type",
    "validate_ollama_url",
    "get_models_for_type",
    "fetch_ollama_models",
    "get_provider_instance_key",
    "set_provider_api_key",
    "get_provider_api_key",
    "remove_provider_api_key",
    "set_provider_aws_credentials",
    "get_provider_aws_credentials",
    "remove_provider_aws_credentials",
    "ProvidersFileCorruptedError",
    "DuplicateProviderError",
    "InvalidProviderTypeError",
    "InvalidProviderNameError",
    "OllamaConnectionError",
    "InvalidOllamaUrlError",
]

PROVIDERS_FILE = "providers.json"

# Provider name pattern: starts with letter, alphanumeric/underscore/hyphen, 1-64 chars
PROVIDER_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

# Hardcoded model registry for supported providers
PROVIDER_MODELS: dict[str, dict] = {
    "openai": {
        "endpoint": "https://api.openai.com/v1",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "o1",
            "o1-mini",
            "o1-preview",
        ],
    },
    "anthropic": {
        "endpoint": "https://api.anthropic.com",
        "models": [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ],
    },
    "openrouter": {
        "endpoint": "https://openrouter.ai/api/v1",
        "models": [
            "anthropic/claude-opus-4",
            "anthropic/claude-sonnet-4",
            "openai/gpt-4o",
            "openai/o1",
            "openai/gpt-oss-120b",
            "google/gemini-2.5-pro",
            "meta-llama/llama-4-maverick",
            "deepseek/deepseek-chat-v3",
            "deepseek/deepseek-r1",
            "qwen/qwen3-235b",
            "z-ai/glm-4.5",
            "z-ai/glm-4.5-air",
            "moonshotai/kimi-k2",
            "minimax/minimax-m1",
        ],
    },
    "bedrock": {
        "endpoint": None,  # Uses AWS SDK
        "models": [
            "anthropic.claude-opus-4-20250514-v1:0",
            "anthropic.claude-sonnet-4-20250514-v1:0",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "anthropic.claude-3-5-haiku-20241022-v1:0",
            "anthropic.claude-3-haiku-20240307-v1:0",
            "amazon.titan-text-express-v1",
            "amazon.titan-text-lite-v1",
            "meta.llama3-70b-instruct-v1:0",
        ],
    },
    "vertex": {
        "endpoint": None,  # Uses Google SDK, requires project_id
        "models": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ],
    },
    "zai": {
        "endpoint": "https://open.bigmodel.cn/api/paas/v4",
        "models": [
            "glm-4",
            "glm-4-plus",
            "glm-4-air",
            "glm-4-airx",
            "glm-4-flash",
            "glm-4-long",
            "glm-4v",
            "glm-4v-plus",
        ],
    },
    "ollama": {
        "endpoint": None,  # User-provided
        "models": None,  # Dynamic discovery via fetch_ollama_models()
    },
}


class ProvidersFileCorruptedError(Exception):
    """Raised when providers.json cannot be parsed."""

    pass


class DuplicateProviderError(Exception):
    """Raised when trying to add a provider that already exists."""

    pass


class InvalidProviderTypeError(Exception):
    """Raised when an invalid provider type is specified."""

    pass


class InvalidProviderNameError(Exception):
    """Raised when an invalid provider name is specified."""

    pass


class OllamaConnectionError(Exception):
    """Raised when connection to Ollama server fails."""

    pass


class InvalidOllamaUrlError(Exception):
    """Raised when Ollama URL is invalid or points to a restricted address."""

    pass


def validate_provider_name(name: str | None) -> None:
    """Validate provider name format.

    Args:
        name: Provider name to validate.

    Raises:
        InvalidProviderNameError: If name is None or doesn't match pattern.
    """
    if not isinstance(name, str):
        raise InvalidProviderNameError("Provider name must be a string")

    if not PROVIDER_NAME_PATTERN.match(name):
        raise InvalidProviderNameError(
            f"Invalid provider name '{name}'. "
            "Must start with a letter, contain only alphanumeric characters, "
            "underscores, or hyphens, and be 1-64 characters long."
        )


def validate_provider_type(provider_type: str) -> None:
    """Validate provider type.

    Args:
        provider_type: Provider type to validate.

    Raises:
        InvalidProviderTypeError: If type is not in PROVIDER_MODELS.
    """
    if provider_type not in PROVIDER_MODELS:
        valid_types = ", ".join(sorted(PROVIDER_MODELS.keys()))
        raise InvalidProviderTypeError(
            f"Invalid provider type '{provider_type}'. Valid types: {valid_types}"
        )


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or reserved.

    Args:
        ip_str: IP address string.

    Returns:
        True if the IP is private/reserved, False otherwise.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            # AWS/cloud metadata endpoint
            or ip_str.startswith("169.254.")
        )
    except ValueError:
        # Not a valid IP address
        return False


def _is_metadata_endpoint(ip_str: str) -> bool:
    """Check if an IP address is a cloud metadata endpoint.

    Blocks the link-local range used by cloud provider metadata services
    (AWS 169.254.169.254, GCP 169.254.169.254, etc.).

    Args:
        ip_str: IP address string.

    Returns:
        True if the IP is a cloud metadata endpoint, False otherwise.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_link_local
    except ValueError:
        return False


def validate_ollama_url(url: str) -> str:
    """Validate Ollama server URL for security.

    Ensures the URL:
    - Has http or https scheme
    - Does not point to cloud metadata endpoints (169.254.x.x)

    Private and loopback addresses are allowed because Ollama is a self-hosted
    service typically running on local networks (e.g. http://192.168.1.17:11434).

    Args:
        url: URL to validate.

    Returns:
        Normalized URL (trailing slash removed).

    Raises:
        InvalidOllamaUrlError: If URL is invalid or points to a restricted address.
    """
    url = url.strip().rstrip("/")

    # ATX iter-2 W-SEC-1: reject characters that could break out of a
    # YAML/TOML/shell scalar in downstream template rendering. The
    # hermes config template renders this URL into a YAML double-quoted
    # scalar; a `"` or `\` (which urlparse accepts) would produce
    # malformed YAML and DoS the Ansible push step on every sync.
    # Whitespace and control characters are not valid in URLs per
    # RFC 3986 and are rejected here for defense in depth.
    if any(ch in url for ch in ('"', "\\", "\n", "\r", "\t")):
        raise InvalidOllamaUrlError(
            "URL must not contain quote, backslash, or whitespace characters"
        )

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise InvalidOllamaUrlError(f"Invalid URL format: {e}")

    # Check scheme
    if parsed.scheme not in ("http", "https"):
        raise InvalidOllamaUrlError(
            f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed."
        )

    # Get hostname
    hostname = parsed.hostname
    if not hostname:
        raise InvalidOllamaUrlError("URL must include a hostname")

    # Resolve hostname to IP and block cloud metadata endpoints only.
    # Private/loopback IPs are allowed - Ollama runs on local networks.
    try:
        addr_info = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if _is_metadata_endpoint(ip_str):
                raise InvalidOllamaUrlError(
                    f"URL resolves to a cloud metadata endpoint '{ip_str}'. "
                    "This address is not allowed for security."
                )
    except socket.gaierror:
        # Hostname doesn't resolve - let requests.get handle this later
        pass
    except InvalidOllamaUrlError:
        raise
    except Exception:
        # Other resolution errors - let requests.get handle this later
        pass

    return url


def get_models_for_type(provider_type: str) -> list[str] | None:
    """Get available models for a provider type.

    Args:
        provider_type: Provider type to get models for.

    Returns:
        List of model names, or None for dynamic providers (like Ollama).

    Raises:
        InvalidProviderTypeError: If type is not valid.
    """
    validate_provider_type(provider_type)
    return PROVIDER_MODELS[provider_type]["models"]


def fetch_ollama_models(endpoint: str, timeout: int = 10) -> list[str]:
    """Fetch available models from an Ollama server.

    Args:
        endpoint: Base URL of Ollama server (e.g., http://localhost:11434).
                  Must be validated with validate_ollama_url() first.
        timeout: Request timeout in seconds.

    Returns:
        List of model names available on the server.

    Raises:
        OllamaConnectionError: If connection fails or response is invalid.
    """
    # Normalize endpoint (remove trailing slash)
    endpoint = endpoint.rstrip("/")
    url = f"{endpoint}/api/tags"

    try:
        response = requests.get(
            url, timeout=timeout, allow_redirects=False, verify=True
        )
        response.raise_for_status()
        data = response.json()

        # Ollama returns {"models": [{"name": "llama3:latest", ...}, ...]}
        models = data.get("models", [])
        if not isinstance(models, list):
            raise OllamaConnectionError(
                "Invalid response from Ollama server: expected 'models' to be a list"
            )

        return [
            m.get("name", "") for m in models if isinstance(m, dict) and m.get("name")
        ]

    except requests.exceptions.ConnectionError:
        raise OllamaConnectionError(
            f"Could not connect to Ollama server at {endpoint}. "
            "Ensure the server is running."
        )
    except requests.exceptions.Timeout:
        raise OllamaConnectionError(
            f"Connection to Ollama server at {endpoint} timed out."
        )
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        raise OllamaConnectionError(f"Ollama server returned error: {status}")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise OllamaConnectionError(f"Invalid response from Ollama server: {e}")


# Provider API key storage using secrets module


def get_provider_instance_key(provider_name: str) -> str:
    """Generate secrets instance key for a provider.

    Args:
        provider_name: Name of the provider.

    Returns:
        Instance key in format "provider:{name}".
    """
    return f"provider:{provider_name}"


def set_provider_api_key(provider_name: str, api_key: str) -> bool:
    """Store API key for a provider securely.

    Uses the secrets module to store the API key.

    Args:
        provider_name: Name of the provider.
        api_key: API key to store.

    Returns:
        True if new secret created, False if existing secret updated.
    """
    from clawrium.core.secrets import set_instance_secret

    instance_key = get_provider_instance_key(provider_name)
    return set_instance_secret(
        instance_key,
        "API_KEY",
        api_key,
        description=f"API key for provider {provider_name}",
    )


def get_provider_api_key(provider_name: str) -> str | None:
    """Retrieve API key for a provider.

    Args:
        provider_name: Name of the provider.

    Returns:
        API key if found, None otherwise.
    """
    from clawrium.core.secrets import get_instance_secrets

    instance_key = get_provider_instance_key(provider_name)
    secrets = get_instance_secrets(instance_key)
    if "API_KEY" in secrets:
        return secrets["API_KEY"]["value"]
    return None


def remove_provider_api_key(provider_name: str) -> bool:
    """Remove API key for a provider.

    Args:
        provider_name: Name of the provider.

    Returns:
        True if secret was removed, False if it didn't exist.
    """
    from clawrium.core.secrets import remove_instance_secret

    instance_key = get_provider_instance_key(provider_name)
    return remove_instance_secret(instance_key, "API_KEY")


def set_provider_aws_credentials(
    provider_name: str, access_key: str, secret_key: str
) -> bool:
    """Store AWS credentials for a Bedrock provider securely.

    Uses the secrets module to store both AWS Access Key ID and Secret Access Key.

    Args:
        provider_name: Name of the provider.
        access_key: AWS Access Key ID.
        secret_key: AWS Secret Access Key.

    Returns:
        True if new secrets created, False if existing secrets updated.
    """
    from clawrium.core.secrets import set_instance_secret

    instance_key = get_provider_instance_key(provider_name)
    created1 = set_instance_secret(
        instance_key,
        "AWS_ACCESS_KEY_ID",
        access_key,
        description=f"AWS access key for provider {provider_name}",
    )
    created2 = set_instance_secret(
        instance_key,
        "AWS_SECRET_ACCESS_KEY",
        secret_key,
        description=f"AWS secret key for provider {provider_name}",
    )
    return created1 and created2


def get_provider_aws_credentials(provider_name: str) -> tuple[str | None, str | None]:
    """Retrieve AWS credentials for a Bedrock provider.

    Args:
        provider_name: Name of the provider.

    Returns:
        Tuple of (access_key, secret_key). Either value may be None if not found.
    """
    from clawrium.core.secrets import get_instance_secrets

    instance_key = get_provider_instance_key(provider_name)
    secrets = get_instance_secrets(instance_key)
    access_key = None
    secret_key = None
    if "AWS_ACCESS_KEY_ID" in secrets:
        access_key = secrets["AWS_ACCESS_KEY_ID"]["value"]
    if "AWS_SECRET_ACCESS_KEY" in secrets:
        secret_key = secrets["AWS_SECRET_ACCESS_KEY"]["value"]
    return (access_key, secret_key)


def remove_provider_aws_credentials(provider_name: str) -> bool:
    """Remove AWS credentials for a Bedrock provider.

    Args:
        provider_name: Name of the provider.

    Returns:
        True if any secret was removed, False if neither existed.
    """
    from clawrium.core.secrets import remove_instance_secret

    instance_key = get_provider_instance_key(provider_name)
    removed1 = remove_instance_secret(instance_key, "AWS_ACCESS_KEY_ID")
    removed2 = remove_instance_secret(instance_key, "AWS_SECRET_ACCESS_KEY")
    return removed1 or removed2


def load_providers() -> list[dict]:
    """Load providers from JSON file.

    Returns:
        List of provider dictionaries. Empty list if file doesn't exist.

    Raises:
        ProvidersFileCorruptedError: If providers.json exists but cannot be parsed.
    """
    providers_path = get_config_dir() / PROVIDERS_FILE
    if not providers_path.exists():
        return []

    try:
        with open(providers_path) as f:
            data = json.load(f)
            # Validate it's a list of dicts
            if not isinstance(data, list):
                raise ProvidersFileCorruptedError(
                    f"providers.json is not a list: {providers_path}"
                )
            if not all(isinstance(p, dict) for p in data):
                raise ProvidersFileCorruptedError(
                    f"providers.json contains invalid entries (expected list of objects): {providers_path}"
                )
            return data
    except json.JSONDecodeError as e:
        raise ProvidersFileCorruptedError(
            f"providers.json is corrupted: {e}. "
            f"Backup the file and delete it to recover: {providers_path}"
        ) from e


@contextmanager
def _providers_lock():
    """Context manager for exclusive access to providers.json.

    Uses fcntl.flock for advisory locking to prevent TOCTOU races
    when multiple processes try to modify providers.json concurrently.
    """
    config_dir = init_config_dir()
    lock_path = config_dir / ".providers.lock"

    # Create lock file if it doesn't exist
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _save_providers_atomic(providers: list[dict], config_dir) -> None:
    """Internal: Write providers atomically without acquiring lock.

    This function performs the atomic write (temp file + rename).
    Caller MUST hold the _providers_lock().

    Args:
        providers: List of provider dictionaries.
        config_dir: Path to config directory.
    """
    providers_path = config_dir / PROVIDERS_FILE
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
    try:
        # Set restrictive permissions on temp file before writing (survives rename)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(providers, f, indent=2)
        os.replace(tmp_path, providers_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_providers(providers: list[dict]) -> None:
    """Save providers to JSON file atomically with file locking.

    Creates config directory if it doesn't exist.
    Uses atomic write (temp file + rename) to prevent data loss on crash.
    Uses fcntl.flock to prevent concurrent write races.

    Args:
        providers: List of provider dictionaries to save.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()

    with _providers_lock():
        _save_providers_atomic(providers, config_dir)


def add_provider(provider: dict) -> None:
    """Add a provider to the registry atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent add_provider calls.

    Args:
        provider: Provider dictionary to add.

    Raises:
        DuplicateProviderError: If provider name already exists.
        InvalidProviderNameError: If provider name is invalid.
    """
    name = provider.get("name")
    validate_provider_name(name)

    with _providers_lock():
        providers = load_providers()

        # Check for duplicate
        for existing in providers:
            if existing.get("name") == name:
                raise DuplicateProviderError(f"Provider '{name}' already exists")

        providers.append(provider)

        # Save without re-acquiring lock
        config_dir = init_config_dir()
        _save_providers_atomic(providers, config_dir)


def get_provider(name: str) -> dict | None:
    """Get a provider by name.

    Args:
        name: Provider name to search for.

    Returns:
        Provider dictionary if found, None otherwise.
    """
    providers = load_providers()
    for provider in providers:
        if provider.get("name") == name:
            return provider
    return None


def update_provider(name: str, updater: Callable[[dict], dict]) -> bool:
    """Atomically update a provider record.

    Acquires exclusive lock, loads providers, applies updater function,
    and saves in a single atomic operation. Prevents TOCTOU races.

    Args:
        name: The name of the provider to update.
        updater: Function that takes provider dict and returns updated provider dict.

    Returns:
        True if provider was found and updated, False if not found.
    """
    with _providers_lock():
        providers = load_providers()
        found = False
        for i, provider in enumerate(providers):
            if provider.get("name") == name:
                providers[i] = updater(provider)
                found = True
                break

        if found:
            # Save without re-acquiring lock (we already hold it)
            config_dir = init_config_dir()
            _save_providers_atomic(providers, config_dir)

        return found


def remove_provider(name: str) -> bool:
    """Remove a provider by name atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent remove_provider calls.

    Args:
        name: The provider name to remove.

    Returns:
        True if provider was found and removed, False otherwise.
    """
    with _providers_lock():
        providers = load_providers()
        filtered = [p for p in providers if p.get("name") != name]

        if len(filtered) == len(providers):
            # No provider was removed
            return False

        # Save without re-acquiring lock
        config_dir = init_config_dir()
        _save_providers_atomic(filtered, config_dir)

        return True
