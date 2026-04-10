"""Tests for Ansible playbooks structure and content."""

from pathlib import Path


def test_base_playbook_exists():
    """Test that base playbook exists."""

    # Base playbook is at src/clawrium/platform/playbooks/base.yaml
    project_root = Path(__file__).parent.parent
    base_playbook = (
        project_root / "src" / "clawrium" / "platform" / "playbooks" / "base.yaml"
    )

    assert base_playbook.exists(), "base.yaml playbook should exist"


def test_base_playbook_structure():
    """Test that base playbook has required structure."""
    import yaml

    project_root = Path(__file__).parent.parent
    base_playbook = (
        project_root / "src" / "clawrium" / "platform" / "playbooks" / "base.yaml"
    )

    content = base_playbook.read_text()

    # Check for required elements in raw content
    assert "- hosts:" in content, "Should have hosts directive"
    assert "become: yes" in content or "become: true" in content, "Should require sudo"

    # Parse YAML to validate structure and package lists
    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"

    # Extract all tasks from the first play
    tasks = data[0].get("tasks", [])

    # Find and validate Node.js installation
    # Look for the specific task "Install Node.js"
    nodejs_tasks = [t for t in tasks if t.get("name") == "Install Node.js"]
    assert len(nodejs_tasks) > 0, "Should have task to install Node.js"
    nodejs_task = nodejs_tasks[0]
    apt_module = nodejs_task.get("ansible.builtin.apt", {})
    assert apt_module.get("name") == "nodejs", (
        "Node.js task should install nodejs package"
    )

    # Find and validate build-essential installation
    build_essential_tasks = [
        t for t in tasks if "build-essential" in str(t.get("name", "")).lower()
    ]
    assert len(build_essential_tasks) > 0, "Should have task to install build-essential"
    build_essential_task = build_essential_tasks[0]
    apt_module = build_essential_task.get("ansible.builtin.apt", {})
    assert apt_module.get("name") == "build-essential", (
        "build-essential task should install build-essential package"
    )

    # Find and validate git/gh installation
    git_gh_tasks = [
        t
        for t in tasks
        if "git" in str(t.get("name", "")).lower()
        and "github" in str(t.get("name", "")).lower()
    ]
    assert len(git_gh_tasks) > 0, "Should have task to install git and GitHub CLI"
    git_gh_task = git_gh_tasks[0]
    apt_module = git_gh_task.get("ansible.builtin.apt", {})
    packages = apt_module.get("name", [])
    assert isinstance(packages, list), "git/gh task should install list of packages"
    assert "git" in packages, "Should install git package"
    assert "gh" in packages, "Should install gh (GitHub CLI) package"


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
    assert "agent_name" in content, "Should use agent_name variable"
    assert "install-cli.sh" in content, "Should use official install-cli.sh installer"
    assert "/.openclaw/bin/openclaw gateway run" in content, (
        "Should start gateway from installed runtime prefix"
    )
    assert "--allow-unconfigured" in content, (
        "Should allow startup before interactive setup is completed"
    )
    assert "EnvironmentFile=" in content, "Should load environment file in service"

    # Parse YAML to ensure it's valid
    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"
