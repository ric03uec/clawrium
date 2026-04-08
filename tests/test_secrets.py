"""Tests for secrets storage module."""

import json
import pytest
from clawrium.core.secrets import (
    load_secrets,
    save_secrets,
    validate_secret_key,
    SECRETS_FILE,
    SecretsFileCorruptedError,
    InvalidSecretKeyError,
    InvalidInstanceKeyComponentError,
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
    remove_instance_secret,
    list_instances_with_secrets,
)


def test_load_secrets_no_file(isolated_config):
    """load_secrets() with no file returns empty dict."""
    secrets = load_secrets()
    assert secrets == {}


def test_load_secrets_valid_json(isolated_config):
    """load_secrets() with valid JSON returns dict[str, dict[str, SecretEntry]] (nested structure)."""
    # Setup: create secrets.json with test data (nested structure)
    isolated_config.mkdir(parents=True, exist_ok=True)
    secrets_path = isolated_config / SECRETS_FILE
    test_data = {
        "wolf:openclaw:work": {
            "OPENAI_API_KEY": {
                "key": "OPENAI_API_KEY",
                "value": "sk-test-123",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "OpenAI API key",
            },
            "ANTHROPIC_API_KEY": {
                "key": "ANTHROPIC_API_KEY",
                "value": "sk-ant-test-456",
                "created_at": "2024-01-02T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "description": "",
            },
        }
    }
    secrets_path.write_text(json.dumps(test_data))

    # Test
    secrets = load_secrets()
    assert secrets == test_data


def test_load_secrets_invalid_json(isolated_config):
    """load_secrets() with invalid JSON raises SecretsFileCorruptedError."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    secrets_path = isolated_config / SECRETS_FILE
    secrets_path.write_text("not valid json {{{")

    with pytest.raises(SecretsFileCorruptedError) as exc_info:
        load_secrets()
    assert "corrupted" in str(exc_info.value).lower()


def test_load_secrets_non_dict_json(isolated_config):
    """load_secrets() with valid JSON that is not a dict raises SecretsFileCorruptedError."""
    isolated_config.mkdir(parents=True, exist_ok=True)
    secrets_path = isolated_config / SECRETS_FILE
    secrets_path.write_text("[1, 2, 3]")  # Valid JSON, but not a dict

    with pytest.raises(SecretsFileCorruptedError) as exc_info:
        load_secrets()
    assert "not a dict" in str(exc_info.value).lower()


def test_save_secrets_creates_file(isolated_config):
    """save_secrets() creates file in config dir (nested structure)."""
    test_secrets = {
        "wolf:openclaw:work": {
            "OPENAI_API_KEY": {
                "key": "OPENAI_API_KEY",
                "value": "sk-test-123",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "OpenAI API key",
            }
        }
    }

    save_secrets(test_secrets)

    secrets_path = isolated_config / SECRETS_FILE
    assert secrets_path.exists()

    with open(secrets_path) as f:
        saved_data = json.load(f)
    assert saved_data == test_secrets


def test_save_secrets_file_permissions(isolated_config):
    """save_secrets() creates file with mode 0o600 (nested structure)."""
    test_secrets = {
        "wolf:openclaw:work": {
            "OPENAI_API_KEY": {
                "key": "OPENAI_API_KEY",
                "value": "sk-test-123",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "OpenAI API key",
            }
        }
    }
    save_secrets(test_secrets)

    secrets_path = isolated_config / SECRETS_FILE
    mode = secrets_path.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_save_secrets_creates_dir(tmp_path, monkeypatch):
    """save_secrets creates config directory if it doesn't exist (nested structure)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "clawrium"

    # Config dir doesn't exist yet
    assert not config_dir.exists()

    test_secrets = {
        "wolf:openclaw:work": {
            "OPENAI_API_KEY": {
                "key": "OPENAI_API_KEY",
                "value": "sk-test-123",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "OpenAI API key",
            }
        }
    }
    save_secrets(test_secrets)

    # Config dir should now exist
    assert config_dir.exists()
    assert (config_dir / SECRETS_FILE).exists()


# Old global functions tests removed - functionality moved to per-instance tests


def test_concurrent_write_protection(isolated_config):
    """Multiple save_secrets calls don't corrupt file (file locking test, nested structure)."""
    # This is a basic sanity check - true concurrency testing requires threading
    test_secrets1 = {
        "wolf:openclaw:work": {
            "KEY1": {
                "key": "KEY1",
                "value": "value1",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "",
            }
        }
    }
    test_secrets2 = {
        "bear:zeroclaw:personal": {
            "KEY2": {
                "key": "KEY2",
                "value": "value2",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "",
            }
        }
    }

    # Sequential writes should both succeed
    save_secrets(test_secrets1)
    save_secrets(test_secrets2)

    # Last write wins
    secrets = load_secrets()
    assert "bear:zeroclaw:personal" in secrets


# Tests for validate_secret_key (Issue 3 fix)


def test_validate_secret_key_valid():
    """validate_secret_key accepts valid env-var-safe keys."""
    assert validate_secret_key("OPENAI_API_KEY") == "OPENAI_API_KEY"
    assert validate_secret_key("A") == "A"
    assert validate_secret_key("API_KEY_123") == "API_KEY_123"
    assert validate_secret_key("X" * 128) == "X" * 128  # Max length


def test_validate_secret_key_empty():
    """validate_secret_key rejects empty key."""
    with pytest.raises(InvalidSecretKeyError) as exc_info:
        validate_secret_key("")
    assert "cannot be empty" in str(exc_info.value)


def test_validate_secret_key_lowercase():
    """validate_secret_key rejects lowercase keys."""
    with pytest.raises(InvalidSecretKeyError) as exc_info:
        validate_secret_key("openai_api_key")
    assert "must start with uppercase" in str(exc_info.value)


def test_validate_secret_key_starts_with_number():
    """validate_secret_key rejects keys starting with number."""
    with pytest.raises(InvalidSecretKeyError) as exc_info:
        validate_secret_key("123_KEY")
    assert "must start with uppercase" in str(exc_info.value)


def test_validate_secret_key_special_chars():
    """validate_secret_key rejects keys with special characters."""
    with pytest.raises(InvalidSecretKeyError):
        validate_secret_key("OPENAI-API-KEY")  # Hyphen not allowed

    with pytest.raises(InvalidSecretKeyError):
        validate_secret_key("OPENAI.API.KEY")  # Dot not allowed

    with pytest.raises(InvalidSecretKeyError):
        validate_secret_key("OPENAI API KEY")  # Space not allowed


def test_validate_secret_key_too_long():
    """validate_secret_key rejects keys longer than 128 characters."""
    with pytest.raises(InvalidSecretKeyError):
        validate_secret_key("X" * 129)


def test_validate_secret_key_null_bytes():
    """validate_secret_key rejects keys with null bytes."""
    with pytest.raises(InvalidSecretKeyError):
        validate_secret_key("OPENAI\x00KEY")


def test_validate_secret_key_newlines():
    """validate_secret_key rejects keys with newlines."""
    with pytest.raises(InvalidSecretKeyError):
        validate_secret_key("OPENAI\nKEY")


# Old global function tests for strict mode removed - DuplicateSecretError not used in per-instance API


# Tests for per-instance secret storage (Phase 06)


def test_get_instance_key():
    """get_instance_key(host, claw_type, claw_name) returns formatted key."""
    key = get_instance_key("wolf", "openclaw", "work")
    assert key == "wolf:openclaw:work"

    key = get_instance_key("bear", "zeroclaw", "personal")
    assert key == "bear:zeroclaw:personal"


def test_get_instance_key_rejects_colon_in_hostname():
    """get_instance_key rejects hostname containing colon (B1 ATX fix)."""
    with pytest.raises(InvalidInstanceKeyComponentError) as exc:
        get_instance_key("wolf:evil", "openclaw", "work")
    assert "hostname" in str(exc.value).lower()
    assert "alphanumeric" in str(exc.value).lower()


def test_get_instance_key_rejects_colon_in_claw_type():
    """get_instance_key rejects claw_type containing colon."""
    with pytest.raises(InvalidInstanceKeyComponentError) as exc:
        get_instance_key("wolf", "open:claw", "work")
    assert "claw_type" in str(exc.value).lower()


def test_get_instance_key_rejects_colon_in_claw_name():
    """get_instance_key rejects claw_name containing colon."""
    with pytest.raises(InvalidInstanceKeyComponentError) as exc:
        get_instance_key("wolf", "openclaw", "work:evil")
    assert "claw_name" in str(exc.value).lower()


def test_get_instance_key_rejects_empty_component():
    """get_instance_key rejects empty components."""
    with pytest.raises(InvalidInstanceKeyComponentError) as exc:
        get_instance_key("", "openclaw", "work")
    assert "empty" in str(exc.value).lower()


def test_get_instance_key_allows_valid_special_chars():
    """get_instance_key allows hyphens, underscores, dots in components."""
    # Hyphen is valid (common in hostnames and claw names)
    key = get_instance_key("wolf-server", "openclaw", "my-claw")
    assert key == "wolf-server:openclaw:my-claw"

    # Underscore is valid
    key = get_instance_key("wolf_server", "open_claw", "my_claw")
    assert key == "wolf_server:open_claw:my_claw"

    # Dot is valid (FQDN hostnames)
    key = get_instance_key("wolf.local", "openclaw", "work")
    assert key == "wolf.local:openclaw:work"


def test_set_instance_secret(isolated_config):
    """set_instance_secret creates nested entry."""
    instance_key = "wolf:openclaw:work"
    result = set_instance_secret(instance_key, "OPENAI_API_KEY", "sk-123", "OpenAI key")
    assert result is True  # Created new

    # Verify nested structure
    secrets = load_secrets()
    assert instance_key in secrets
    assert "OPENAI_API_KEY" in secrets[instance_key]

    entry = secrets[instance_key]["OPENAI_API_KEY"]
    assert entry["key"] == "OPENAI_API_KEY"
    assert entry["value"] == "sk-123"
    assert entry["description"] == "OpenAI key"
    assert "created_at" in entry
    assert "updated_at" in entry


def test_get_instance_secrets(isolated_config):
    """get_instance_secrets returns dict of secrets for instance."""
    instance_key = "wolf:openclaw:work"
    set_instance_secret(instance_key, "OPENAI_API_KEY", "sk-123")
    set_instance_secret(instance_key, "ANTHROPIC_API_KEY", "sk-ant-456")

    secrets = get_instance_secrets(instance_key)
    assert len(secrets) == 2
    assert "OPENAI_API_KEY" in secrets
    assert "ANTHROPIC_API_KEY" in secrets
    assert secrets["OPENAI_API_KEY"]["value"] == "sk-123"
    assert secrets["ANTHROPIC_API_KEY"]["value"] == "sk-ant-456"


def test_get_instance_secrets_empty(isolated_config):
    """get_instance_secrets returns empty dict for instance with no secrets."""
    secrets = get_instance_secrets("wolf:openclaw:work")
    assert secrets == {}


def test_same_key_different_instances(isolated_config):
    """Same secret key can have different values per instance."""
    instance1 = "wolf:openclaw:work"
    instance2 = "wolf:openclaw:personal"

    set_instance_secret(instance1, "OPENAI_API_KEY", "sk-work-123")
    set_instance_secret(instance2, "OPENAI_API_KEY", "sk-personal-456")

    secrets1 = get_instance_secrets(instance1)
    secrets2 = get_instance_secrets(instance2)

    assert secrets1["OPENAI_API_KEY"]["value"] == "sk-work-123"
    assert secrets2["OPENAI_API_KEY"]["value"] == "sk-personal-456"


def test_remove_instance_secret(isolated_config):
    """remove_instance_secret removes only from specified instance."""
    instance1 = "wolf:openclaw:work"
    instance2 = "wolf:openclaw:personal"

    # Set same key on both instances
    set_instance_secret(instance1, "OPENAI_API_KEY", "sk-work-123")
    set_instance_secret(instance2, "OPENAI_API_KEY", "sk-personal-456")

    # Remove from instance1
    result = remove_instance_secret(instance1, "OPENAI_API_KEY")
    assert result is True

    # Verify removed from instance1 but not instance2
    secrets1 = get_instance_secrets(instance1)
    secrets2 = get_instance_secrets(instance2)

    assert "OPENAI_API_KEY" not in secrets1
    assert "OPENAI_API_KEY" in secrets2
    assert secrets2["OPENAI_API_KEY"]["value"] == "sk-personal-456"


def test_remove_instance_secret_not_found(isolated_config):
    """remove_instance_secret returns False if not found."""
    result = remove_instance_secret("wolf:openclaw:work", "NONEXISTENT_KEY")
    assert result is False


def test_list_instances_with_secrets(isolated_config):
    """list_instances_with_secrets returns sorted list of instance keys."""
    # Create secrets for multiple instances
    set_instance_secret("wolf:openclaw:work", "OPENAI_API_KEY", "sk-123")
    set_instance_secret("bear:zeroclaw:personal", "ANTHROPIC_API_KEY", "sk-456")
    set_instance_secret("wolf:openclaw:personal", "TEST_KEY", "value")

    instances = list_instances_with_secrets()
    assert len(instances) == 3
    # Should be sorted
    assert instances == sorted(
        ["wolf:openclaw:work", "bear:zeroclaw:personal", "wolf:openclaw:personal"]
    )


def test_list_instances_with_secrets_empty(isolated_config):
    """list_instances_with_secrets returns empty list when no secrets."""
    instances = list_instances_with_secrets()
    assert instances == []


def test_set_instance_secret_updates_existing(isolated_config):
    """set_instance_secret updates existing secret, preserves created_at."""
    instance_key = "wolf:openclaw:work"

    # Create initial secret
    set_instance_secret(instance_key, "OPENAI_API_KEY", "sk-123", "Initial")
    secrets1 = get_instance_secrets(instance_key)
    created_at = secrets1["OPENAI_API_KEY"]["created_at"]

    import time

    time.sleep(0.1)  # Ensure timestamp difference

    # Update existing secret
    result = set_instance_secret(instance_key, "OPENAI_API_KEY", "sk-456")
    assert result is False  # Updated existing

    # Verify update
    secrets2 = get_instance_secrets(instance_key)
    assert secrets2["OPENAI_API_KEY"]["value"] == "sk-456"
    assert secrets2["OPENAI_API_KEY"]["created_at"] == created_at  # Preserved
    assert secrets2["OPENAI_API_KEY"]["updated_at"] != created_at  # Changed
    # Description preserved if not provided
    assert secrets2["OPENAI_API_KEY"]["description"] == "Initial"


def test_set_instance_secret_validates_key(isolated_config):
    """set_instance_secret validates secret key."""
    with pytest.raises(InvalidSecretKeyError):
        set_instance_secret("wolf:openclaw:work", "invalid-key", "value")


def test_remove_instance_secret_validates_key(isolated_config):
    """remove_instance_secret validates secret key."""
    with pytest.raises(InvalidSecretKeyError):
        remove_instance_secret("wolf:openclaw:work", "invalid-key")


def test_file_permissions_per_instance(isolated_config):
    """Secrets file still has 0o600 permissions with per-instance structure."""
    set_instance_secret("wolf:openclaw:work", "OPENAI_API_KEY", "sk-123")

    secrets_path = isolated_config / SECRETS_FILE
    mode = secrets_path.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_load_secrets_nested_structure(isolated_config):
    """load_secrets returns dict[str, dict[str, SecretEntry]] for nested structure."""
    # Setup: create secrets.json with nested data
    isolated_config.mkdir(parents=True, exist_ok=True)
    secrets_path = isolated_config / SECRETS_FILE
    test_data = {
        "wolf:openclaw:work": {
            "OPENAI_API_KEY": {
                "key": "OPENAI_API_KEY",
                "value": "sk-test-123",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "description": "OpenAI API key",
            }
        },
        "bear:zeroclaw:personal": {
            "ANTHROPIC_API_KEY": {
                "key": "ANTHROPIC_API_KEY",
                "value": "sk-ant-test-456",
                "created_at": "2024-01-02T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "description": "",
            }
        },
    }
    secrets_path.write_text(json.dumps(test_data))

    # Test
    secrets = load_secrets()
    assert secrets == test_data
    assert "wolf:openclaw:work" in secrets
    assert "OPENAI_API_KEY" in secrets["wolf:openclaw:work"]
