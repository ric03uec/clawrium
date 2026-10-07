"""Pi encrypted exec transport must fail when CMS encryption cannot run."""

import subprocess
from pathlib import Path
import yaml
import pytest


@pytest.mark.parametrize("name", ["exec.yaml", "exec_macos.yaml"])
def test_pi_exec_capture_fails_when_cms_recipient_is_invalid(tmp_path, name):
    play = yaml.safe_load(
        Path("src/clawrium/platform/registry/pi/playbooks", name).read_text()
    )[0]
    home = tmp_path / "home"
    env = home / ".pi/agent/clawrium-provider.env"
    env.parent.mkdir(parents=True)
    env.write_text("OPENROUTER_API_KEY=x\n")
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            play["vars"]["pi_exec_capture_bootstrap"],
            "pi",
            play["vars"]["pi_exec_capture_program"],
            "not-a-certificate",
            "/bin/true",
        ],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
