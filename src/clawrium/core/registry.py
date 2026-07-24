"""Registry loading and agent manifest management.

This module discovers available agent types from bundled manifests and validates
platform compatibility, onboarding metadata, and secret requirements.
"""

import logging
import re
from typing import Any, Literal, NotRequired, TypedDict

import yaml
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)


class InvalidAgentTypeError(Exception):
    """Raised when an agent type contains invalid characters."""

    pass


# Backward-compatible alias for external imports.
InvalidClawNameError = InvalidAgentTypeError


def validate_agent_type(agent_type: str) -> None:
    """Validate agent type to prevent path traversal attacks.

    Args:
        agent_type: Type identifier to validate

    Raises:
        InvalidAgentTypeError: If the identifier contains invalid characters
    """
    if not agent_type:
        raise InvalidAgentTypeError("Agent type cannot be empty")

    if not re.match(r"^[a-zA-Z0-9_-]+$", agent_type):
        raise InvalidAgentTypeError(
            f"Agent type '{agent_type}' contains invalid characters. "
            "Only alphanumeric, underscore, and hyphen are allowed."
        )

    if ".." in agent_type or "/" in agent_type or "\\" in agent_type:
        raise InvalidAgentTypeError(
            f"Agent type '{agent_type}' contains path traversal characters"
        )


class Requirements(TypedDict):
    """Runtime requirements for a supported platform entry."""

    min_memory_mb: int
    gpu_required: bool
    dependencies: dict[str, str]


class SecretDefinition(TypedDict):
    """Secret definition in a manifest."""

    key: str
    description: str


class PlatformEntry(TypedDict):
    """Single supported platform in an agent manifest."""

    version: str
    os: str
    os_version: str
    arch: str
    requirements: Requirements
    sha256: NotRequired[str]


class OnboardingTask(TypedDict):
    """Task definition within an onboarding stage."""

    id: str
    name: str
    type: str
    path: NotRequired[str]
    template: NotRequired[str]
    prompt: NotRequired[str]
    options: NotRequired[list[str]]
    default: NotRequired[str | bool]
    message: NotRequired[str]
    command: NotRequired[str]
    paths: NotRequired[list[str]]
    fields: NotRequired[list[dict[str, Any]]]
    min_select: NotRequired[int]


class OnboardingStage(TypedDict):
    """Onboarding stage configuration."""

    required: NotRequired[bool]
    description: str
    tasks: NotRequired[list[OnboardingTask]]
    auto_skip: NotRequired[bool]


class OnboardingConfig(TypedDict):
    """Onboarding configuration container."""

    stages: NotRequired[dict[str, OnboardingStage]]


class ManifestSecrets(TypedDict):
    """Secret definitions for an agent manifest."""

    required: NotRequired[list[SecretDefinition]]
    optional: NotRequired[list[SecretDefinition]]


class AgentInfo(TypedDict):
    """Agent metadata at the top of a manifest."""

    type: str
    description: str


class WorkspaceConfig(TypedDict):
    """Workspace metadata consumed by cross-claw subsystems (e.g. memory CLI)."""

    memory_path: NotRequired[str]


class ChatFeatureConfig(TypedDict):
    """Chat capability descriptor."""

    type: Literal["openai", "websocket", "zeroclaw"]


class WebUIFeatureConfig(TypedDict):
    """Native web UI capability descriptor.

    `bind` is a closed enum: `loopback` (agent listens on 127.0.0.1 only)
    or `wildcard` (agent listens on 0.0.0.0). Either way the SSH tunnel
    target on the remote is loopback, so `BIND_ADDRESS_MAP` resolves both
    to `127.0.0.1`; the distinction exists so the manifest accurately
    describes the agent's bind, not because tunneling differs.

    `port_field` is a dotted path into the agent's `hosts.json` config
    record (for example, `dashboard.port` or `gateway.port`) so callers
    can locate the persisted per-instance port.

    `default_port` is optional. In practice every agent type computes a
    per-instance port at install time and persists it under `port_field`,
    so a single manifest-wide default would silently collide when a host
    runs multiple agents of the same type. Manifests should omit
    `default_port` when no static fallback exists; resolvers surface a
    missing persisted port as "no UI available" rather than serving a
    different instance's URL.
    """

    enabled: bool
    bind: Literal["loopback", "wildcard"]
    default_port: NotRequired[int]
    port_field: str


class WorkspaceOverlayConfig(TypedDict):
    """Operator-overlay descriptor for `features.workspace_overlay`.

    `destination_root` is the absolute path on the agent host (under the
    agent's home dir) where files from the local
    `~/.config/clawrium/agents/<type>/<name>/workspace/` slot are mirrored
    on every `clawctl agent sync`. The leading `~` is expanded against
    the agent's home (`/home/<agent_name>` on Linux). The Python
    enumerator and Ansible playbook agree on this expansion via the
    `workspace_dest_root` extravar; the playbook asserts the rendered
    path begins with `/home/{{ agent_name }}/` and never references
    `ansible_user_dir` (B1 iter-3).

    `excludes` is a list of relative-path strings interpreted with two
    shapes (W10):
      * No trailing slash → exact file match (`config.yaml` excludes
        only the workspace-root `config.yaml`, never a nested
        `profiles/x/config.yaml`).
      * Trailing slash → directory prefix (`sessions/` excludes every
        descendant of `sessions/`).
    """

    destination_root: str
    excludes: NotRequired[list[str]]


class FeaturesConfig(TypedDict):
    """Capability flags advertised by an agent manifest."""

    memory: NotRequired[bool]
    chat: NotRequired[ChatFeatureConfig]
    web_ui: NotRequired[WebUIFeatureConfig]
    workspace_overlay: NotRequired[WorkspaceOverlayConfig]


class AgentManifest(TypedDict):
    """Complete agent manifest."""

    agent: AgentInfo
    platforms: list[PlatformEntry]
    secrets: NotRequired[ManifestSecrets]
    onboarding: NotRequired[OnboardingConfig]
    workspace: NotRequired[WorkspaceConfig]
    features: NotRequired[FeaturesConfig]


class CompatibilityResult(TypedDict):
    """Result of a host compatibility check."""

    compatible: bool
    matched_entry: PlatformEntry | None
    reasons: list[str]


class ManifestNotFoundError(Exception):
    """Raised when an agent manifest is not found."""

    pass


class ManifestParseError(Exception):
    """Raised when a manifest is malformed."""

    pass


def _raise_parse_error(agent_type: str, message: str) -> None:
    """Raise a manifest parse error with a stable prefix."""
    raise ManifestParseError(f"Manifest for '{agent_type}' {message}")


def _as_dict(value: object, path: str, agent_type: str) -> dict[str, Any]:
    """Validate and return a dictionary value."""
    if not isinstance(value, dict):
        _raise_parse_error(
            agent_type, f"has invalid `{path}` section (expected object)"
        )
    return value


def _validate_requirements(
    requirements_value: object,
    agent_type: str,
    platform_index: int,
) -> Requirements:
    """Validate requirements for a platform entry."""
    path = f"platforms[{platform_index}].requirements"
    requirements = _as_dict(requirements_value, path, agent_type)

    min_memory = requirements.get("min_memory_mb")
    if not isinstance(min_memory, int) or min_memory < 0:
        _raise_parse_error(
            agent_type,
            f"has invalid `{path}.min_memory_mb` (expected non-negative integer)",
        )

    gpu_required = requirements.get("gpu_required")
    if not isinstance(gpu_required, bool):
        _raise_parse_error(
            agent_type, f"has invalid `{path}.gpu_required` (expected boolean)"
        )

    dependencies_value = requirements.get("dependencies")
    if not isinstance(dependencies_value, dict):
        _raise_parse_error(
            agent_type, f"has invalid `{path}.dependencies` (expected object)"
        )

    dependencies: dict[str, str] = {}
    for dependency_name, dependency_version in dependencies_value.items():
        if not isinstance(dependency_name, str) or not dependency_name:
            _raise_parse_error(
                agent_type, f"has invalid dependency key in `{path}.dependencies`"
            )
        if not isinstance(dependency_version, str) or not dependency_version:
            _raise_parse_error(
                agent_type,
                f"has invalid dependency constraint for `{dependency_name}` in `{path}.dependencies`",
            )
        dependencies[dependency_name] = dependency_version

    return {
        "min_memory_mb": min_memory,
        "gpu_required": gpu_required,
        "dependencies": dependencies,
    }


def _validate_platform_entry(
    entry_value: object,
    agent_type: str,
    platform_index: int,
) -> PlatformEntry:
    """Validate one platform entry."""
    path = f"platforms[{platform_index}]"
    entry = _as_dict(entry_value, path, agent_type)

    required_string_fields = ["version", "os", "os_version", "arch"]
    validated_entry: PlatformEntry = {
        "version": "",
        "os": "",
        "os_version": "",
        "arch": "",
        "requirements": {
            "min_memory_mb": 0,
            "gpu_required": False,
            "dependencies": {},
        },
    }

    for field_name in required_string_fields:
        field_value = entry.get(field_name)
        if not isinstance(field_value, str) or not field_value:
            _raise_parse_error(
                agent_type,
                f"has invalid `{path}.{field_name}` (expected non-empty string)",
            )
        validated_entry[field_name] = field_value  # type: ignore[literal-required]

    validated_entry["requirements"] = _validate_requirements(
        entry.get("requirements"),
        agent_type,
        platform_index,
    )

    if "sha256" in entry:
        sha256 = entry["sha256"]
        if not isinstance(sha256, str) or not sha256:
            _raise_parse_error(
                agent_type, f"has invalid `{path}.sha256` (expected non-empty string)"
            )
        validated_entry["sha256"] = sha256

    return validated_entry


def _validate_secret_definitions(
    secrets_value: object,
    agent_type: str,
) -> ManifestSecrets:
    """Validate secret definitions."""
    secrets = _as_dict(secrets_value, "secrets", agent_type)
    validated: ManifestSecrets = {}

    for secret_class in ("required", "optional"):
        if secret_class not in secrets:
            continue

        section_value = secrets[secret_class]
        if not isinstance(section_value, list):
            _raise_parse_error(
                agent_type,
                f"has invalid `secrets.{secret_class}` (expected list)",
            )

        section_entries: list[SecretDefinition] = []
        for index, item in enumerate(section_value):
            item_path = f"secrets.{secret_class}[{index}]"
            secret_definition = _as_dict(item, item_path, agent_type)

            key = secret_definition.get("key")
            if not isinstance(key, str) or not key:
                _raise_parse_error(
                    agent_type,
                    f"has invalid `{item_path}.key` (expected non-empty string)",
                )

            description = secret_definition.get("description")
            if not isinstance(description, str) or not description:
                _raise_parse_error(
                    agent_type,
                    f"has invalid `{item_path}.description` (expected non-empty string)",
                )

            section_entries.append({"key": key, "description": description})

        validated[secret_class] = section_entries

    return validated


def _validate_onboarding_task(
    task_value: object,
    agent_type: str,
    stage_name: str,
    task_index: int,
) -> OnboardingTask:
    """Validate one onboarding task."""
    path = f"onboarding.stages.{stage_name}.tasks[{task_index}]"
    task = _as_dict(task_value, path, agent_type)

    required_string_fields = ["id", "name", "type"]
    validated_task: OnboardingTask = {"id": "", "name": "", "type": ""}

    for field_name in required_string_fields:
        field_value = task.get(field_name)
        if not isinstance(field_value, str) or not field_value:
            _raise_parse_error(
                agent_type,
                f"has invalid `{path}.{field_name}` (expected non-empty string)",
            )
        validated_task[field_name] = field_value  # type: ignore[literal-required]

    optional_string_fields = ["path", "template", "prompt", "message", "command"]
    for field_name in optional_string_fields:
        if field_name in task:
            field_value = task[field_name]
            if not isinstance(field_value, str):
                _raise_parse_error(
                    agent_type, f"has invalid `{path}.{field_name}` (expected string)"
                )
            validated_task[field_name] = field_value  # type: ignore[literal-required]

    if "options" in task:
        options = task["options"]
        if not isinstance(options, list) or any(
            not isinstance(option, str) for option in options
        ):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.options` (expected string list)"
            )
        validated_task["options"] = options

    if "paths" in task:
        paths = task["paths"]
        if not isinstance(paths, list) or any(
            not isinstance(item, str) for item in paths
        ):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.paths` (expected string list)"
            )
        validated_task["paths"] = paths

    if "fields" in task:
        fields = task["fields"]
        if not isinstance(fields, list) or any(
            not isinstance(field, dict) for field in fields
        ):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.fields` (expected object list)"
            )
        validated_task["fields"] = fields  # type: ignore[assignment]

    if "default" in task:
        default = task["default"]
        if not isinstance(default, (str, bool)):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.default` (expected string or boolean)"
            )
        validated_task["default"] = default

    if "min_select" in task:
        min_select = task["min_select"]
        if not isinstance(min_select, int) or min_select < 0:
            _raise_parse_error(
                agent_type,
                f"has invalid `{path}.min_select` (expected non-negative integer)",
            )
        validated_task["min_select"] = min_select

    return validated_task


def _validate_onboarding_stage(
    stage_value: object,
    agent_type: str,
    stage_name: str,
) -> OnboardingStage:
    """Validate one onboarding stage definition."""
    path = f"onboarding.stages.{stage_name}"
    stage = _as_dict(stage_value, path, agent_type)

    description = stage.get("description")
    if not isinstance(description, str) or not description:
        _raise_parse_error(
            agent_type, f"has invalid `{path}.description` (expected non-empty string)"
        )

    validated_stage: OnboardingStage = {"description": description}

    if "required" in stage:
        required = stage["required"]
        if not isinstance(required, bool):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.required` (expected boolean)"
            )
        validated_stage["required"] = required

    if "auto_skip" in stage:
        auto_skip = stage["auto_skip"]
        if not isinstance(auto_skip, bool):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.auto_skip` (expected boolean)"
            )
        validated_stage["auto_skip"] = auto_skip

    if "tasks" in stage:
        tasks = stage["tasks"]
        if not isinstance(tasks, list):
            _raise_parse_error(
                agent_type, f"has invalid `{path}.tasks` (expected list)"
            )
        validated_stage["tasks"] = [
            _validate_onboarding_task(task, agent_type, stage_name, index)
            for index, task in enumerate(tasks)
        ]

    return validated_stage


def _validate_onboarding(
    onboarding_value: object,
    agent_type: str,
) -> OnboardingConfig:
    """Validate onboarding metadata."""
    onboarding = _as_dict(onboarding_value, "onboarding", agent_type)
    validated: OnboardingConfig = {}

    if "stages" not in onboarding:
        return validated

    stages_value = onboarding["stages"]
    stages = _as_dict(stages_value, "onboarding.stages", agent_type)

    validated_stages: dict[str, OnboardingStage] = {}
    for stage_name, stage_value in stages.items():
        if not isinstance(stage_name, str) or not stage_name:
            _raise_parse_error(
                agent_type, "has invalid stage name under `onboarding.stages`"
            )
        validated_stages[stage_name] = _validate_onboarding_stage(
            stage_value,
            agent_type,
            stage_name,
        )

    validated["stages"] = validated_stages
    return validated


def _validate_workspace(workspace_value: object, agent_type: str) -> WorkspaceConfig:
    """Validate workspace metadata block."""
    workspace = _as_dict(workspace_value, "workspace", agent_type)
    validated: WorkspaceConfig = {}

    if "memory_path" in workspace:
        memory_path = workspace["memory_path"]
        if not isinstance(memory_path, str) or not memory_path:
            _raise_parse_error(
                agent_type,
                "has invalid `workspace.memory_path` (expected non-empty string)",
            )
        validated["memory_path"] = memory_path

    return validated


_ALLOWED_CHAT_TYPES = ("openai", "websocket", "zeroclaw")
_ALLOWED_WEB_UI_BINDS = ("loopback", "wildcard")

# `port_field` is a dotted path that downstream code uses both as a config
# lookup (`agent_record.config.<port_field>`) and — in Phase 2 — as an
# Ansible extra-var. Constrain to dotted identifier segments so a tampered
# or third-party manifest cannot smuggle path-traversal, prototype-pollution,
# or shell-metachar payloads through this field.
_PORT_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")


def _validate_web_ui(web_ui_value: object, agent_type: str) -> WebUIFeatureConfig:
    """Validate `features.web_ui` block.

    `bind` is a closed enum: `loopback` or `wildcard`. `enabled`, `bind`,
    and `port_field` are required; `default_port` is optional (most
    agents compute a per-instance port at install time and persist it
    under `port_field`, so a single manifest-wide default would silently
    collide for hosts running multiple instances of the same agent type).
    When present, `default_port` is constrained to 1024..65535 —
    privileged ports (<1024) are rejected outright because non-root
    agent processes cannot bind them. `port_field` must be a dotted
    identifier path (e.g. `dashboard.port`, `gateway.port`).
    """
    web_ui = _as_dict(web_ui_value, "features.web_ui", agent_type)

    enabled = web_ui.get("enabled")
    if not isinstance(enabled, bool):
        _raise_parse_error(
            agent_type, "has invalid `features.web_ui.enabled` (expected boolean)"
        )

    bind = web_ui.get("bind")
    if bind not in _ALLOWED_WEB_UI_BINDS:
        allowed = ", ".join(repr(b) for b in _ALLOWED_WEB_UI_BINDS)
        _raise_parse_error(
            agent_type,
            f"has invalid `features.web_ui.bind` (expected one of {allowed})",
        )

    has_default_port = "default_port" in web_ui
    default_port = web_ui.get("default_port")
    if has_default_port and (
        not isinstance(default_port, int)
        or isinstance(default_port, bool)
        or default_port < 1024
        or default_port > 65535
    ):
        # Privileged ports (1..1023) are rejected outright — non-root agent
        # processes cannot bind them, and `logger.warning` is invisible in
        # the default uv-tool deployment, so a silent accept would be a
        # latent footgun. Fail loudly at manifest-load time instead.
        _raise_parse_error(
            agent_type,
            "has invalid `features.web_ui.default_port` "
            "(expected integer in 1024..65535)",
        )

    port_field = web_ui.get("port_field")
    has_port_field = "port_field" in web_ui
    if not has_port_field:
        _raise_parse_error(
            agent_type,
            "features.web_ui.port_field is required "
            "(dotted path into agent config, e.g. 'gateway.port')",
        )
    if not isinstance(port_field, str) or not port_field.strip() or not _PORT_FIELD_RE.fullmatch(port_field):
        _raise_parse_error(
            agent_type,
            "has invalid `features.web_ui.port_field` "
            "(expected dotted identifier path, e.g. 'dashboard.port')",
        )

    result: WebUIFeatureConfig = {
        "enabled": enabled,
        "bind": bind,
        "port_field": port_field if has_port_field else "",
    }
    if has_default_port:
        result["default_port"] = default_port
    return result


def _validate_features(features_value: object, agent_type: str) -> FeaturesConfig:
    """Validate features capability block."""
    features = _as_dict(features_value, "features", agent_type)
    validated: FeaturesConfig = {}

    if "memory" in features:
        memory_flag = features["memory"]
        if not isinstance(memory_flag, bool):
            _raise_parse_error(
                agent_type, "has invalid `features.memory` (expected boolean)"
            )
        validated["memory"] = memory_flag

    if "chat" in features:
        chat_value = features["chat"]
        chat_block = _as_dict(chat_value, "features.chat", agent_type)
        chat_type = chat_block.get("type")
        if chat_type not in _ALLOWED_CHAT_TYPES:
            allowed = ", ".join(repr(t) for t in _ALLOWED_CHAT_TYPES)
            _raise_parse_error(
                agent_type,
                f"has invalid `features.chat.type` (expected one of {allowed})",
            )
        validated["chat"] = {"type": chat_type}

    if "web_ui" in features:
        validated["web_ui"] = _validate_web_ui(features["web_ui"], agent_type)

    if "workspace_overlay" in features:
        validated["workspace_overlay"] = _validate_workspace_overlay(
            features["workspace_overlay"], agent_type
        )

    return validated


def _validate_workspace_overlay(
    overlay_value: object, agent_type: str
) -> WorkspaceOverlayConfig:
    """Validate `features.workspace_overlay` block.

    Required: `destination_root` (non-empty string, absolute or `~`-rooted).
    Optional: `excludes` (list of strings). `null` is normalized to `[]`.
    Trailing-slash entries are dir-prefix; bare entries are exact-file.
    """
    overlay = _as_dict(overlay_value, "features.workspace_overlay", agent_type)
    dest = overlay.get("destination_root")
    if not isinstance(dest, str) or not dest.strip():
        _raise_parse_error(
            agent_type,
            "has invalid `features.workspace_overlay.destination_root` "
            "(expected non-empty string)",
        )
    dest = dest.strip()
    if not (dest.startswith("/") or dest.startswith("~")):
        _raise_parse_error(
            agent_type,
            "has invalid `features.workspace_overlay.destination_root` "
            f"(expected absolute path or `~`-rooted, got {dest!r})",
        )

    validated: WorkspaceOverlayConfig = {"destination_root": dest}

    if "excludes" in overlay:
        raw_excludes = overlay["excludes"]
        if raw_excludes is None:
            validated["excludes"] = []
        elif isinstance(raw_excludes, list):
            cleaned: list[str] = []
            for entry in raw_excludes:
                if not isinstance(entry, str) or not entry.strip():
                    _raise_parse_error(
                        agent_type,
                        "has invalid entry in "
                        "`features.workspace_overlay.excludes` "
                        "(expected non-empty string)",
                    )
                stripped = entry.strip()
                if stripped.startswith("/") or ".." in stripped.split("/"):
                    _raise_parse_error(
                        agent_type,
                        "has invalid entry in "
                        "`features.workspace_overlay.excludes` "
                        f"(must be a workspace-relative path, got {stripped!r})",
                    )
                cleaned.append(stripped)
            validated["excludes"] = cleaned
        else:
            _raise_parse_error(
                agent_type,
                "has invalid `features.workspace_overlay.excludes` "
                "(expected list or null)",
            )
    else:
        validated["excludes"] = []

    return validated


def _validate_manifest(manifest_data: object, agent_type: str) -> AgentManifest:
    """Validate the full manifest and return normalized data."""
    root = _as_dict(manifest_data, "root", agent_type)

    required_fields = ["agent", "platforms"]
    missing_fields = [
        field_name for field_name in required_fields if field_name not in root
    ]
    if missing_fields:
        _raise_parse_error(
            agent_type,
            f"is missing required fields ({', '.join(missing_fields)})",
        )

    agent_info = _as_dict(root["agent"], "agent", agent_type)

    manifest_agent_type = agent_info.get("type")
    if not isinstance(manifest_agent_type, str) or not manifest_agent_type:
        _raise_parse_error(
            agent_type, "has invalid `agent.type` (expected non-empty string)"
        )
    if manifest_agent_type != agent_type:
        _raise_parse_error(
            agent_type,
            f"has `agent.type={manifest_agent_type}` but was loaded as '{agent_type}'",
        )

    description = agent_info.get("description", "")
    if not isinstance(description, str):
        _raise_parse_error(
            agent_type, "has invalid `agent.description` (expected string)"
        )

    platforms_value = root["platforms"]
    if not isinstance(platforms_value, list) or not platforms_value:
        _raise_parse_error(
            agent_type, "has invalid `platforms` (expected non-empty list)"
        )

    platforms = [
        _validate_platform_entry(entry, agent_type, index)
        for index, entry in enumerate(platforms_value)
    ]

    validated_manifest: AgentManifest = {
        "agent": {
            "type": manifest_agent_type,
            "description": description,
        },
        "platforms": platforms,
    }

    if "secrets" in root:
        validated_manifest["secrets"] = _validate_secret_definitions(
            root["secrets"],
            agent_type,
        )

    if "onboarding" in root:
        validated_manifest["onboarding"] = _validate_onboarding(
            root["onboarding"],
            agent_type,
        )

    if "workspace" in root:
        validated_manifest["workspace"] = _validate_workspace(
            root["workspace"],
            agent_type,
        )

    if "features" in root:
        validated_manifest["features"] = _validate_features(
            root["features"],
            agent_type,
        )

    return validated_manifest


def load_manifest(claw_name: str) -> AgentManifest:
    """Load an agent manifest from the bundled registry.

    Args:
        claw_name: Agent type identifier (for example, ``openclaw``)

    Returns:
        Parsed and validated `AgentManifest`

    Raises:
        ManifestNotFoundError: If the registry directory does not exist
        ManifestParseError: If the manifest file is malformed
        InvalidAgentTypeError: If the provided type identifier is invalid
    """
    validate_agent_type(claw_name)

    try:
        from importlib.resources import files

        registry_package = files("clawrium.platform.registry")
        agent_dir = registry_package / claw_name

        if not agent_dir.is_dir():
            raise ManifestNotFoundError(
                f"Agent type '{claw_name}' not found in registry"
            )

        manifest_file = agent_dir / "manifest.yaml"
        manifest_text = manifest_file.read_text()
        manifest_data = yaml.safe_load(manifest_text)

        return _validate_manifest(manifest_data, claw_name)

    except FileNotFoundError as error:
        raise ManifestNotFoundError(
            f"Agent type '{claw_name}' not found in registry"
        ) from error
    except yaml.YAMLError as error:
        raise ManifestParseError(
            f"Failed to parse manifest for '{claw_name}': {error}"
        ) from error


def list_claws() -> list[str]:
    """List all available agent types in the registry.

    Returns:
        Sorted list of available type identifiers
    """
    try:
        from importlib.resources import files

        registry_package = files("clawrium.platform.registry")

        agent_types: list[str] = []
        for item in registry_package.iterdir():
            if not item.is_dir():
                continue

            manifest_file = item / "manifest.yaml"
            try:
                _ = manifest_file.read_text()
                agent_types.append(item.name)
            except (FileNotFoundError, AttributeError):
                continue

        return sorted(agent_types)

    except (ModuleNotFoundError, FileNotFoundError) as error:
        logger.error("Failed to list agent types: %s", error)
        return []


def get_claw_info(claw_name: str) -> dict[str, Any]:
    """Get summary information about an agent type.

    Args:
        claw_name: Agent type identifier

    Returns:
        Dictionary with: agent_type, description, latest_version, supported_platforms

    Raises:
        ManifestNotFoundError: If the type is not available
        ManifestParseError: If no valid versions are found
    """
    manifest = load_manifest(claw_name)

    versions: list[Version] = []
    for platform in manifest["platforms"]:
        try:
            versions.append(Version(platform["version"]))
        except InvalidVersion:
            logger.warning(
                "Invalid version '%s' in manifest for %s",
                platform["version"],
                claw_name,
            )

    if not versions:
        raise ManifestParseError(
            f"No valid versions found in manifest for '{claw_name}'"
        )

    latest_version = str(max(versions))

    supported_platforms: list[str] = []
    for platform in manifest["platforms"]:
        platform_label = f"{platform['os']} {platform['os_version']} {platform['arch']}"
        if platform_label not in supported_platforms:
            supported_platforms.append(platform_label)

    return {
        "agent_type": manifest["agent"]["type"],
        "description": manifest["agent"].get("description", ""),
        "latest_version": latest_version,
        "supported_platforms": sorted(supported_platforms),
    }


def get_required_secrets(claw_name: str) -> list[SecretDefinition]:
    """Get required secret definitions for an agent type.

    Args:
        claw_name: Agent type identifier

    Returns:
        List of required `SecretDefinition` objects
    """
    manifest = load_manifest(claw_name)
    return manifest.get("secrets", {}).get("required", [])


def get_optional_secrets(claw_name: str) -> list[SecretDefinition]:
    """Get optional secret definitions for an agent type.

    Args:
        claw_name: Agent type identifier

    Returns:
        List of optional `SecretDefinition` objects
    """
    manifest = load_manifest(claw_name)
    return manifest.get("secrets", {}).get("optional", [])


def _parse_version_safe(version_text: str) -> Version:
    """Parse semantic version text safely.

    Invalid versions are mapped to `0.0.0` so sorting remains deterministic.
    """
    try:
        return Version(version_text)
    except InvalidVersion:
        return Version("0.0.0")


_VERSION_SPEC_RE = re.compile(r"^\s*(>=|<=|>|<|==|!=)\s*(.+?)\s*$")


def _version_matches(spec: str, actual: str) -> bool:
    """Check whether `actual` satisfies the `spec` os_version constraint.

    Accepts:
      - exact string equality (back-compat: "24.04" == "24.04")
      - operator-prefixed specs: ">=14", ">14", "<=15", "<15", "==14", "!=14"

    A malformed spec raises ValueError. Missing/empty actual is never a match
    for an operator spec, but still allowed as an exact match against an empty
    spec (defensive — callers normalize to empty string for unknown facts).
    """
    if spec is None:
        raise ValueError("os_version spec must not be None")
    if actual is None:
        actual = ""

    match = _VERSION_SPEC_RE.match(spec)
    if not match:
        # Treat as exact-equality back-compat path.
        return spec == actual

    op, rhs = match.group(1), match.group(2)
    try:
        rhs_v = Version(rhs)
    except InvalidVersion as exc:
        raise ValueError(f"invalid version in spec {spec!r}: {exc}") from exc

    if not actual:
        return False
    try:
        actual_v = Version(actual)
    except InvalidVersion:
        return False

    if op == ">=":
        return actual_v >= rhs_v
    if op == "<=":
        return actual_v <= rhs_v
    if op == ">":
        return actual_v > rhs_v
    if op == "<":
        return actual_v < rhs_v
    if op == "==":
        return actual_v == rhs_v
    if op == "!=":
        return actual_v != rhs_v
    raise ValueError(f"unsupported operator in spec {spec!r}: {op}")


def check_compatibility(
    claw_name: str,
    hardware: dict,
    version: str | None = None,
) -> CompatibilityResult:
    """Check whether host hardware is compatible with an agent type.

    Matching is sparse: only explicit platform entries are considered valid.

    Args:
        claw_name: Agent type identifier
        hardware: Host hardware details
        version: Optional specific version to evaluate

    Returns:
        Compatibility result with matched platform (if any) and reasons.
    """
    manifest = load_manifest(claw_name)

    platforms = manifest["platforms"]
    if version:
        try:
            requested_version = Version(version)
        except InvalidVersion:
            return {
                "compatible": False,
                "matched_entry": None,
                "reasons": [f"Invalid version format: {version}"],
            }

        platforms = [
            platform
            for platform in platforms
            if _parse_version_safe(platform["version"]) == requested_version
        ]
        if not platforms:
            return {
                "compatible": False,
                "matched_entry": None,
                "reasons": [f"Version {version} not found in manifest"],
            }
    else:
        platforms = sorted(
            platforms,
            key=lambda platform: _parse_version_safe(platform["version"]),
            reverse=True,
        )

    # Hardware not yet gathered (fresh host — no scan run yet) or gathered
    # only partially. Skip the requirements loop and route through the
    # install-refusal path so the operator sees a clean "missing facts"
    # message instead of manifest requirements formatted against sentinel
    # values (see issue #737).
    os_value = hardware.get("os")
    os_version_value = hardware.get("os_version")
    hardware_known = bool(
        os_value
        and os_value != "unknown"
        and os_version_value
        and os_version_value != "unknown"
        and hardware.get("memtotal_mb", 0) > 0
    )
    if not hardware_known:
        return {
            "compatible": True,
            "matched_entry": None,
            "reasons": [],
        }

    all_reasons: list[str] = []

    for platform in platforms:
        reasons: list[str] = []

        os_match = platform["os"] == hardware.get("os")
        os_version_match = _version_matches(
            spec=platform["os_version"],
            actual=hardware.get("os_version", ""),
        )
        arch_match = platform["arch"] == hardware.get("architecture")

        if not os_match or not os_version_match:
            reasons.append(
                f"Requires {platform['os']} {platform['os_version']}, "
                f"host has {hardware.get('os', 'unknown')} {hardware.get('os_version', 'unknown')}"
            )
        elif not arch_match:
            reasons.append(
                f"Requires {platform['arch']}, host has {hardware.get('architecture', 'unknown')}"
            )

        requirements = platform.get("requirements", {})
        min_memory = requirements.get("min_memory_mb", 0)
        host_memory = hardware.get("memtotal_mb", 0)
        if host_memory < min_memory:
            reasons.append(f"Requires {min_memory}MB RAM, host has {host_memory}MB")

        if requirements.get("gpu_required", False):
            gpu = hardware.get("gpu", {})
            gpu_present = gpu.get("present")
            if gpu_present is False:
                reasons.append("Requires GPU, host has none")
            elif gpu_present is None:
                reasons.append("Requires GPU, but GPU detection failed")

        if not reasons:
            return {
                "compatible": True,
                "matched_entry": platform,
                "reasons": [],
            }

        all_reasons.extend(reasons)

    unique_reasons: list[str] = []
    seen = set()
    for reason in all_reasons:
        if reason in seen:
            continue
        seen.add(reason)
        unique_reasons.append(reason)

    return {
        "compatible": False,
        "matched_entry": None,
        "reasons": unique_reasons,
    }


def latest_supported_version(claw_name: str, hardware: dict) -> str | None:
    """Return the max manifest version compatible with the host's OS+arch.

    This is a *narrower* filter than `check_compatibility`: it considers
    only `os`, `os_version`, and `arch`, and intentionally ignores the
    `requirements` block (`min_memory_mb`, `gpu_required`, dependency
    versions). The intent is to answer "which manifest versions can
    target this host's platform triple?" for the GUI's "Upgrade
    available" indicator — a richer compatibility verdict (memory, GPU,
    dependency depth) is left to `check_compatibility`, which the
    install / upgrade execution paths already invoke.

    Returns the max compatible `version`, or None if no platform entry
    matches the host's OS/arch.
    """
    try:
        manifest = load_manifest(claw_name)
    except ManifestNotFoundError:
        return None

    versions: list[Version] = []
    for platform in manifest.get("platforms", []):
        if platform.get("os") != hardware.get("os"):
            continue
        try:
            if not _version_matches(
                spec=platform.get("os_version", ""),
                actual=hardware.get("os_version", ""),
            ):
                continue
        except ValueError:
            continue
        if platform.get("arch") != hardware.get("architecture"):
            continue
        try:
            versions.append(Version(platform["version"]))
        except (InvalidVersion, KeyError):
            continue

    if not versions:
        return None
    return str(max(versions))


# ---------------------------------------------------------------------------
# Hermes version parsing
#
# `hermes --version` emits a string like:
#   Hermes Agent v0.13.0 (2026.5.7)
# The triple OUTSIDE the parentheses is the Python package version (changes
# rarely); the triple INSIDE is the upstream release tag pinned in the
# manifest. We match against the parenthesised tag because that aligns with
# the manifest's per-platform `version` field.
#
# The hermes install.yaml playbook encodes the same regex in Jinja2; this
# helper exists primarily so the regex is testable in pure Python.
# ---------------------------------------------------------------------------

_HERMES_VERSION_RE = re.compile(r"\(([0-9]+\.[0-9]+\.[0-9]+)\)")


def parse_hermes_version(output: str | None) -> str:
    """Parse the upstream release tag from `hermes --version` output.

    Args:
        output: stdout from `hermes --version`, or None when the binary is
            absent. Multiline / leading-whitespace output is supported.

    Returns:
        The parenthesised semver tag (e.g., "2026.5.7"), or "" if the output
        cannot be parsed. An empty return signals "version unknown" to callers
        so the install path can fall back to a safe reinstall.
    """
    if not output:
        return ""
    match = _HERMES_VERSION_RE.search(output)
    if not match:
        return ""
    return match.group(1)
