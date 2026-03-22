"""Tests for Ansible playbooks structure and content."""

from pathlib import Path


def test_base_playbook_exists():
    """Test that base playbook exists."""

    # Base playbook is at platform/playbooks/base.yaml (project root)
    project_root = Path(__file__).parent.parent
    base_playbook = project_root / "platform" / "playbooks" / "base.yaml"

    assert base_playbook.exists(), "base.yaml playbook should exist"


def test_base_playbook_structure():
    """Test that base playbook has required structure."""
    import yaml

    project_root = Path(__file__).parent.parent
    base_playbook = project_root / "platform" / "playbooks" / "base.yaml"

    content = base_playbook.read_text()

    # Check for required elements
    assert "- hosts:" in content, "Should have hosts directive"
    assert "become: yes" in content or "become: true" in content, "Should require sudo"
    assert "nodejs" in content.lower(), "Should install nodejs"
    assert "build-essential" in content, "Should install build-essential"

    # Parse YAML to ensure it's valid
    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"


def test_openclaw_install_playbook_exists():
    """Test that openclaw install playbook exists."""
    from importlib.resources import files

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_dir = openclaw_package / "playbooks"
    install_playbook = playbook_dir / "install.yaml"

    # Since we're using importlib.resources, check if it's readable
    assert install_playbook.is_file(), "install.yaml playbook should exist"


def test_openclaw_install_playbook_structure():
    """Test that openclaw install playbook has required structure."""
    from importlib.resources import files
    import yaml

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_path = openclaw_package / "playbooks" / "install.yaml"

    content = playbook_path.read_text()

    # Check for required elements
    assert "- hosts:" in content, "Should have hosts directive"
    assert "opc-" in content, "Should create opc- user"
    assert "inventory_hostname" in content, "Should use inventory_hostname variable"
    assert "npm install" in content, "Should run npm install"
    assert "openclaw" in content.lower(), "Should reference openclaw repository"

    # Parse YAML to ensure it's valid
    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"
