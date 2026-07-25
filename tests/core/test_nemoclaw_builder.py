"""Tests for the Phase 2 NemoClaw CLI wrapper API (`core/nemoclaw.py`).

Closes ATX iter-1 B4 — the wrapper is the injection-prevention seam
that Phase 3 will delegate every openclaw lifecycle verb through, so
the builder + validators need direct coverage.
"""

from __future__ import annotations

import pytest

from clawrium.core import nemoclaw
from clawrium.core.nemoclaw import (
    NEMOCLAW_BINARY,
    NemoclawCommand,
    _build,
    _validate_sandbox_name,
    default_sandbox_name,
)


class TestValidateSandboxName:
    @pytest.mark.parametrize(
        "name",
        [
            "a",
            "e2e-openclaw",
            "e2e-openclaw-nemo",
            "sandbox_1",
            "a" + "b" * 31,  # length 32 — boundary hit
        ],
    )
    def test_accepts_valid(self, name):
        _validate_sandbox_name(name)  # does not raise

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "1sandbox",  # leading digit
            "-sandbox",  # leading dash
            "_sandbox",  # leading underscore
            "Sandbox",  # uppercase
            "sandbox!",  # special char
            "sandbox; rm -rf /",  # shell smuggling
            "sandbox\nname",  # newline
            "a" + "b" * 32,  # length 33 — one past boundary
        ],
    )
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError, match="sandbox_name"):
            _validate_sandbox_name(name)

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="invalid sandbox_name"):
            _validate_sandbox_name(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="invalid sandbox_name"):
            _validate_sandbox_name(42)  # type: ignore[arg-type]


class TestBuild:
    def test_build_returns_command_with_argv(self):
        cmd = _build("onboard", "e2e-openclaw")
        assert isinstance(cmd, NemoclawCommand)
        assert cmd.verb == "onboard"
        assert cmd.sandbox_name == "e2e-openclaw"
        assert cmd.argv == (NEMOCLAW_BINARY, "onboard", "e2e-openclaw")

    def test_unknown_verb_raises(self):
        with pytest.raises(ValueError, match="unknown verb"):
            _build("delete", "e2e-openclaw")

    def test_build_validates_sandbox_name(self):
        with pytest.raises(ValueError, match="sandbox_name"):
            _build("onboard", "1invalid")


class TestVerbWrappers:
    @pytest.mark.parametrize(
        "fn,verb",
        [
            (nemoclaw.onboard, "onboard"),
            (nemoclaw.start, "start"),
            (nemoclaw.stop, "stop"),
            (nemoclaw.status, "status"),
            (nemoclaw.logs, "logs"),
            (nemoclaw.destroy, "destroy"),
        ],
    )
    def test_verb_wrapper_argv(self, fn, verb):
        cmd = fn("e2e-openclaw")
        assert cmd.verb == verb
        assert cmd.argv == (NEMOCLAW_BINARY, verb, "e2e-openclaw")

    def test_verb_wrapper_rejects_bad_sandbox(self):
        with pytest.raises(ValueError, match="sandbox_name"):
            nemoclaw.onboard("Bad Name")


class TestGatewayRegisterProvider:
    """Phase 4 (#946): gateway_register_provider builder.

    Argv shape is guessed per orchestrator directive and matches
    `.itx/946/00_BLOCKED.md` §7.5 UNRESOLVED — single seam that swaps to
    the real upstream shape once §7.5 is answered.
    """

    def test_argv_shape(self):
        cmd = nemoclaw.gateway_register_provider(
            "e2e-openclaw", "openai-primary", "sk-secret-1", "https://api.openai.com/v1"
        )
        assert cmd.verb == "gateway-provider-add"
        assert cmd.sandbox_name == "e2e-openclaw"
        assert cmd.argv == (
            NEMOCLAW_BINARY,
            "e2e-openclaw",
            "gateway",
            "provider",
            "add",
            "openai-primary",
            "--api-key",
            "sk-secret-1",
            "--base-url",
            "https://api.openai.com/v1",
        )

    def test_rejects_invalid_sandbox_name(self):
        with pytest.raises(ValueError, match="sandbox_name"):
            nemoclaw.gateway_register_provider(
                "Bad Sandbox", "p", "k", "https://example.com"
            )

    @pytest.mark.parametrize(
        "provider_name",
        ["", "!bad", "with space", "a" * 65],
    )
    def test_rejects_invalid_provider_name(self, provider_name):
        with pytest.raises(ValueError, match="provider name"):
            nemoclaw.gateway_register_provider(
                "sbx", provider_name, "k", "https://example.com"
            )

    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "example.com",           # no scheme
            "ftp://example.com",     # wrong scheme
            "https://ex.com/\nfoo",  # newline injection
            "https://ex .com",       # embedded space
        ],
    )
    def test_rejects_invalid_base_url(self, base_url):
        with pytest.raises(ValueError, match="base_url"):
            nemoclaw.gateway_register_provider("sbx", "p", "k", base_url)

    @pytest.mark.parametrize("api_key", ["", "sk-\nleak", "sk-\x00"])
    def test_rejects_invalid_api_key(self, api_key):
        with pytest.raises(ValueError, match="api_key"):
            nemoclaw.gateway_register_provider(
                "sbx", "p", api_key, "https://example.com"
            )


class TestDefaultSandboxName:
    def test_identity_for_valid_agent(self):
        assert default_sandbox_name("e2e-openclaw") == "e2e-openclaw"

    def test_rejects_invalid_agent_name(self):
        with pytest.raises(ValueError, match="sandbox_name"):
            default_sandbox_name("Bad Agent")
