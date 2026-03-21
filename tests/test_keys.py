"""Tests for keys module - per-host SSH key management."""

from pathlib import Path


class TestGetHostKeyDir:
    """Tests for get_host_key_dir function."""

    def test_returns_path_to_keys_hostname_dir(self, isolated_config: Path):
        """get_host_key_dir returns keys/<hostname>/ under config dir."""
        from clawrium.core.keys import get_host_key_dir

        result = get_host_key_dir("192.168.1.100")

        assert result == isolated_config / "keys" / "192.168.1.100"

    def test_handles_hostname_with_dots(self, isolated_config: Path):
        """get_host_key_dir handles dotted hostnames correctly."""
        from clawrium.core.keys import get_host_key_dir

        result = get_host_key_dir("host.example.com")

        assert result == isolated_config / "keys" / "host.example.com"


class TestGetHostPrivateKey:
    """Tests for get_host_private_key function."""

    def test_returns_none_when_key_missing(self, isolated_config: Path):
        """get_host_private_key returns None when no key exists."""
        from clawrium.core.keys import get_host_private_key

        result = get_host_private_key("nonexistent")

        assert result is None

    def test_returns_path_when_key_exists(self, isolated_config: Path):
        """get_host_private_key returns path when key file exists."""
        from clawrium.core.keys import get_host_private_key

        # Setup: create key directory and file
        key_dir = isolated_config / "keys" / "testhost"
        key_dir.mkdir(parents=True)
        private_key = key_dir / "xclm_ed25519"
        private_key.write_text("fake-key")

        result = get_host_private_key("testhost")

        assert result == private_key


class TestGetHostPublicKey:
    """Tests for get_host_public_key function."""

    def test_returns_none_when_key_missing(self, isolated_config: Path):
        """get_host_public_key returns None when no key exists."""
        from clawrium.core.keys import get_host_public_key

        result = get_host_public_key("nonexistent")

        assert result is None

    def test_returns_path_when_key_exists(self, isolated_config: Path):
        """get_host_public_key returns path when public key file exists."""
        from clawrium.core.keys import get_host_public_key

        # Setup: create key directory and file
        key_dir = isolated_config / "keys" / "testhost"
        key_dir.mkdir(parents=True)
        public_key = key_dir / "xclm_ed25519.pub"
        public_key.write_text("ssh-ed25519 AAAA... test")

        result = get_host_public_key("testhost")

        assert result == public_key


class TestGenerateHostKeypair:
    """Tests for generate_host_keypair function."""

    def test_creates_keypair_files(self, isolated_config: Path):
        """generate_host_keypair creates both private and public key files."""
        from clawrium.core.keys import generate_host_keypair

        private_key, public_key = generate_host_keypair("testhost")

        assert private_key.exists()
        assert public_key.exists()
        assert private_key.name == "xclm_ed25519"
        assert public_key.name == "xclm_ed25519.pub"

    def test_private_key_has_correct_permissions(self, isolated_config: Path):
        """generate_host_keypair sets 0600 on private key."""
        from clawrium.core.keys import generate_host_keypair

        private_key, _ = generate_host_keypair("testhost")

        mode = private_key.stat().st_mode & 0o777
        assert mode == 0o600

    def test_key_directory_has_correct_permissions(self, isolated_config: Path):
        """generate_host_keypair sets 0700 on key directory."""
        from clawrium.core.keys import generate_host_keypair

        private_key, _ = generate_host_keypair("testhost")

        key_dir = private_key.parent
        mode = key_dir.stat().st_mode & 0o777
        assert mode == 0o700

    def test_private_key_is_ed25519_format(self, isolated_config: Path):
        """generate_host_keypair creates valid ed25519 private key."""
        from clawrium.core.keys import generate_host_keypair

        private_key, _ = generate_host_keypair("testhost")

        content = private_key.read_text()
        assert "OPENSSH PRIVATE KEY" in content or "PRIVATE KEY" in content

    def test_public_key_is_ssh_format(self, isolated_config: Path):
        """generate_host_keypair creates valid SSH public key."""
        from clawrium.core.keys import generate_host_keypair

        _, public_key = generate_host_keypair("testhost")

        content = public_key.read_text()
        assert content.startswith("ssh-ed25519 ")

    def test_returns_correct_paths(self, isolated_config: Path):
        """generate_host_keypair returns paths in correct location."""
        from clawrium.core.keys import generate_host_keypair

        private_key, public_key = generate_host_keypair("myhost")

        expected_dir = isolated_config / "keys" / "myhost"
        assert private_key == expected_dir / "xclm_ed25519"
        assert public_key == expected_dir / "xclm_ed25519.pub"


class TestDeleteHostKeys:
    """Tests for delete_host_keys function."""

    def test_returns_false_when_no_keys_exist(self, isolated_config: Path):
        """delete_host_keys returns False when key dir doesn't exist."""
        from clawrium.core.keys import delete_host_keys

        result = delete_host_keys("nonexistent")

        assert result is False

    def test_returns_true_and_deletes_directory(self, isolated_config: Path):
        """delete_host_keys deletes entire key directory."""
        from clawrium.core.keys import delete_host_keys

        # Setup: create key directory with files
        key_dir = isolated_config / "keys" / "testhost"
        key_dir.mkdir(parents=True)
        (key_dir / "xclm_ed25519").write_text("private")
        (key_dir / "xclm_ed25519.pub").write_text("public")

        result = delete_host_keys("testhost")

        assert result is True
        assert not key_dir.exists()


class TestReadPublicKey:
    """Tests for read_public_key function."""

    def test_returns_none_when_key_missing(self, isolated_config: Path):
        """read_public_key returns None when no public key exists."""
        from clawrium.core.keys import read_public_key

        result = read_public_key("nonexistent")

        assert result is None

    def test_returns_public_key_content(self, isolated_config: Path):
        """read_public_key returns content of public key file."""
        from clawrium.core.keys import read_public_key

        # Setup: create key directory and public key
        key_dir = isolated_config / "keys" / "testhost"
        key_dir.mkdir(parents=True)
        public_key = key_dir / "xclm_ed25519.pub"
        public_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... clawrium")

        result = read_public_key("testhost")

        assert result == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... clawrium"
