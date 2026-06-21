"""Operator-overlay workspace sync (issue #760).

Mirrors files dropped under
`~/.config/clawrium/agents/<type>/<name>/workspace/` onto the agent
host at the manifest-declared `features.workspace_overlay.destination_root`.

Architecture (plan §1.5):

- Python side enumerates the local workspace, applies manifest excludes,
  filters symlinks + `.clawrium-*` dotfiles, stages an exact byte-copy
  into a managed `tempfile.TemporaryDirectory`, and hands an extravar
  payload off to ansible-runner.
- The per-type `playbooks/workspace.yaml` is the single host-write
  channel. No paramiko, no SFTP, no OS-family branch in this file —
  `core.playbook_resolver` is the OS seam.
- Bidi/control codepoints are stripped from every operator-controlled
  string at the NDJSON / text emission boundary via
  `cli.output._sanitize.sanitize_passthrough` (W4 iter-1).
- Secret-pattern files get a 0600 mode floor regardless of local mode
  (W13 iter-1). Pattern matching is case-insensitive (S4 iter-3).
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawrium.cli.output._sanitize import sanitize_passthrough
from clawrium.core.config import get_config_dir
from clawrium.core.names import validate_agent_name
from clawrium.core.playbook_resolver import resolve_agent_playbook
from clawrium.core.registry import load_manifest

logger = logging.getLogger(__name__)


# Closed enum for NDJSON `state` field (W3 iter-1). Any new state value
# requires a corresponding test update (U24).
WORKSPACE_STATE_QUEUED = "queued"
WORKSPACE_STATE_PUSHED = "pushed"
WORKSPACE_STATE_EXCLUDED = "excluded"
WORKSPACE_STATE_SKIPPED = "skipped"
WORKSPACE_STATE_FAILED = "failed"
WORKSPACE_STATE_COMPLETE = "complete"

WORKSPACE_STATES: frozenset[str] = frozenset(
    {
        WORKSPACE_STATE_QUEUED,
        WORKSPACE_STATE_PUSHED,
        WORKSPACE_STATE_EXCLUDED,
        WORKSPACE_STATE_SKIPPED,
        WORKSPACE_STATE_FAILED,
        WORKSPACE_STATE_COMPLETE,
    }
)


# Secret-pattern globs (W13 iter-1). Case-insensitive matching (S4 iter-3).
_SECRET_PATTERNS: tuple[str, ...] = (
    "*.key",
    "*.pem",
    "*.env",
    ".env",
    "*credentials*",
    "*secret*",
    "*token*",
    "*password*",
)


# Reserved prefix for future clawrium control-plane state inside the
# workspace slot. Always skipped at enumeration (U7).
_RESERVED_PREFIX = ".clawrium-"


class WorkspaceSyncError(Exception):
    """Any failure in the workspace overlay pipeline."""


@dataclass(frozen=True)
class WorkspaceOverlaySpec:
    """Typed view of `features.workspace_overlay` from a loaded manifest.

    `destination_root` is the absolute path on the agent host (under the
    agent's home dir) where workspace files land. `~`-rooted manifests
    are expanded against `/home/<agent_name>` at push time.

    `excludes_files` are exact-path (relative) entries; `excludes_dirs`
    are directory prefixes (originally trailing-slash entries in the
    manifest, stored without the slash here).
    """

    destination_root: str
    excludes_files: frozenset[str] = field(default_factory=frozenset)
    excludes_dirs: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_manifest(cls, agent_type: str) -> "WorkspaceOverlaySpec | None":
        """Build a spec from the bundled manifest, or return None if the
        agent has no `features.workspace_overlay` block.
        """
        manifest = load_manifest(agent_type)
        features = manifest.get("features") or {}
        overlay = features.get("workspace_overlay")
        if overlay is None:
            return None

        dest = overlay["destination_root"]
        excludes = list(overlay.get("excludes") or [])

        files: set[str] = set()
        dirs: list[str] = []
        for entry in excludes:
            if entry.endswith("/"):
                dirs.append(entry.rstrip("/"))
            else:
                files.add(entry)

        return cls(
            destination_root=dest,
            excludes_files=frozenset(files),
            excludes_dirs=tuple(dirs),
        )


@dataclass(frozen=True)
class WorkspaceFileEntry:
    """One enumerated workspace file ready for staging."""

    rel: str
    local_path: Path
    mode: str  # octal string, e.g. "0644"
    owner: str
    group: str

    def to_extravar(self, staged_path: str) -> dict[str, str]:
        return {
            "rel": self.rel,
            "src": staged_path,
            "mode": self.mode,
            "owner": self.owner,
            "group": self.group,
        }


@dataclass(frozen=True)
class WorkspacePhaseResult:
    """Outcome of one push_workspace_phase invocation."""

    success: bool
    files_pushed: tuple[str, ...]
    files_excluded: tuple[str, ...]
    files_skipped: tuple[str, ...] = ()
    error: str | None = None


def _local_workspace_root(agent_type: str, agent_name: str) -> Path:
    """Return the local control-plane workspace slot for an agent.

    Layout:
        <get_config_dir()>/agents/<type>/<name>/workspace/

    The dir may not exist; callers must treat a missing dir as
    "empty workspace, no-op" (U15).
    """
    return (
        get_config_dir()
        / "agents"
        / agent_type
        / agent_name
        / "workspace"
    )


def _is_secret_pattern(rel: str) -> bool:
    """Return True if the workspace file matches a secret-pattern glob.

    Match against the lowercased basename so `MyAPI.KEY` and `.ENV`
    trigger the 0600 floor (S4 iter-3, U35).
    """
    basename = os.path.basename(rel).lower()
    return any(fnmatch.fnmatch(basename, p) for p in _SECRET_PATTERNS)


def _floor_mode_for(rel: str, local_mode: int) -> str:
    """Return the octal mode string honoring the secret-pattern floor.

    Secret-pattern files get exactly 0600. Other files keep their local
    mode bits (rwx for user/group/other) with executability preserved.
    """
    if _is_secret_pattern(rel):
        return "0600"
    # Mask to the permission bits only (0o7777 covers setuid/setgid/sticky
    # in addition to rwx, which we deliberately preserve here).
    return f"0{local_mode & 0o7777:o}"


def enumerate_workspace_files(
    workspace_root: Path,
    spec: WorkspaceOverlaySpec,
    *,
    agent_name: str,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[list[WorkspaceFileEntry], list[str], list[str]]:
    """Walk `workspace_root` and return enumerated entries + skip/excl lists.

    Returns a 3-tuple `(entries, excluded_paths, skipped_paths)`:
        - `entries`: in deterministic sorted order, one per file to push.
        - `excluded_paths`: rels matched by the manifest exclude set.
        - `skipped_paths`: rels skipped for safety reasons (symlinks,
          `.clawrium-*` reserved dotfiles).

    The function does NOT touch the host. It does enforce:
        * symlink rejection at enumeration (U6, W18 iter-2 first line)
        * path traversal rejection (U8)
        * relative-path preservation (U9)
        * `.clawrium-*` skip (U7)
    """
    entries: list[WorkspaceFileEntry] = []
    excluded: list[str] = []
    skipped: list[str] = []

    if not workspace_root.exists():
        return entries, excluded, skipped

    # `Path.walk` would be cleaner but is Python 3.12+; the repo targets
    # Python 3.11 (see pyproject.toml). Use `os.walk` for broader compat.
    workspace_root_resolved = workspace_root.resolve()

    for dirpath, dirnames, filenames in os.walk(workspace_root, followlinks=False):
        # Stable enumeration order — same input → same payload.
        dirnames.sort()
        filenames.sort()

        for fname in filenames:
            abs_path = Path(dirpath) / fname
            try:
                rel = str(abs_path.relative_to(workspace_root))
            except ValueError:
                # Should be impossible under os.walk(workspace_root), but
                # guard so a future change to the walk loop cannot bypass
                # the containment invariant.
                skipped.append(fname)
                _emit_skip(
                    on_event, fname, reason="outside_workspace_root"
                )
                continue

            # POSIX-style separators in the manifest exclude payload and
            # the playbook extravar.
            rel = rel.replace(os.sep, "/")

            if abs_path.is_symlink():
                skipped.append(rel)
                _emit_skip(on_event, rel, reason="symlink")
                continue

            if any(
                part.startswith(_RESERVED_PREFIX)
                for part in rel.split("/")
            ):
                skipped.append(rel)
                _emit_skip(on_event, rel, reason="reserved_dotfile")
                continue

            # Path-traversal containment check (U8). `Path.resolve()`
            # follows symlinks on intermediate dirs; combine with the
            # symlink-leaf check above to keep the workspace sealed.
            try:
                resolved = abs_path.resolve(strict=True)
            except (FileNotFoundError, OSError):
                skipped.append(rel)
                _emit_skip(on_event, rel, reason="unreadable")
                continue
            try:
                resolved.relative_to(workspace_root_resolved)
            except ValueError:
                skipped.append(rel)
                _emit_skip(on_event, rel, reason="path_traversal")
                continue

            if _is_excluded(rel, spec):
                excluded.append(rel)
                _emit_excluded(on_event, rel, agent_type_excl=True)
                continue

            try:
                stat = abs_path.stat()
            except OSError:
                skipped.append(rel)
                _emit_skip(on_event, rel, reason="stat_failed")
                continue

            mode = _floor_mode_for(rel, stat.st_mode)
            entries.append(
                WorkspaceFileEntry(
                    rel=rel,
                    local_path=abs_path,
                    mode=mode,
                    owner=agent_name,
                    group=agent_name,
                )
            )

    return entries, excluded, skipped


def _is_excluded(rel: str, spec: WorkspaceOverlaySpec) -> bool:
    """Apply manifest exclude semantics (W10).

    File entries match exactly. Directory entries (originally
    trailing-slash) match every descendant.
    """
    if rel in spec.excludes_files:
        return True
    for d in spec.excludes_dirs:
        prefix = d.rstrip("/") + "/"
        if rel == d or rel.startswith(prefix):
            return True
    return False


def _emit_excluded(
    on_event: Callable[[str, dict[str, Any]], None] | None,
    rel: str,
    *,
    agent_type_excl: bool,
) -> None:
    if on_event is None:
        return
    on_event(
        "push_workspace",
        {
            "state": WORKSPACE_STATE_EXCLUDED,
            "path": sanitize_passthrough(rel),
            "reason": "manifest_exclude",
        },
    )


def _emit_skip(
    on_event: Callable[[str, dict[str, Any]], None] | None,
    rel: str,
    *,
    reason: str,
) -> None:
    if on_event is None:
        return
    on_event(
        "push_workspace",
        {
            "state": WORKSPACE_STATE_SKIPPED,
            "path": sanitize_passthrough(rel),
            "reason": reason,
        },
    )


def _expand_destination_root(spec: WorkspaceOverlaySpec, agent_name: str) -> str:
    """Expand `~` in `destination_root` to `/home/<agent_name>`.

    The Ansible playbook re-asserts the result begins with
    `/home/<agent_name>/`. We do the expansion Python-side too so the
    extravar payload is unambiguous and the playbook assert sees the
    final rendered string (B1 iter-3 backstop).
    """
    dest = spec.destination_root
    if dest.startswith("~/"):
        dest = f"/home/{agent_name}/" + dest[2:]
    elif dest == "~":
        dest = f"/home/{agent_name}"
    return dest


def _build_inventory(host: dict, ssh_key_path: str) -> dict:
    """Build the ansible-runner inventory dict for the workspace playbook.

    Mirrors the shape used by `core/lifecycle.py:configure_agent` so the
    same host conventions apply (ServerAlive tuning, become timeout).
    """
    return {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_host": host["hostname"],
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": ssh_key_path,
                    "ansible_become_timeout": 120,
                    "ansible_pipelining": True,
                    "ansible_ssh_extra_args": (
                        "-o ServerAliveInterval=30 "
                        "-o ServerAliveCountMax=10 -o ConnectTimeout=60"
                    ),
                }
            },
        }
    }


def _stage_files(
    entries: list[WorkspaceFileEntry], staging_dir: Path
) -> list[dict[str, str]]:
    """Copy each enumerated file into `staging_dir` with `shutil.copy2`.

    Returns the extravar payload list (one dict per file) the playbook
    consumes via `workspace_files`. `shutil.copy2` preserves mode bits
    so the playbook's `mode: "{{ item.mode }}"` matches the staged
    file's perms (S3 iter-3).
    """
    payload: list[dict[str, str]] = []
    for entry in entries:
        staged_path = staging_dir / entry.rel
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.local_path, staged_path)
        # Re-apply the floored mode on the staged copy so a 0600
        # secret-pattern file is not group/world readable inside the
        # staging dir while ansible-runner is still reading it.
        os.chmod(staged_path, int(entry.mode, 8))
        payload.append(entry.to_extravar(str(staged_path)))
    return payload


def push_workspace_phase(
    *,
    host: dict,
    agent_type: str,
    agent_name: str,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    dry_run: bool = False,
) -> WorkspacePhaseResult:
    """Push the operator workspace overlay for one agent.

    The shared helper called by both `core/lifecycle_canonical.py`
    (`sync_agent_canonical`) and `core/lifecycle.py:configure_agent`
    so the two surface paths cannot drift (W9 iter-1, U27).

    Args:
        host: hosts.json host record (provides hostname, user, ssh key).
        agent_type: registry agent type (e.g. "openclaw").
        agent_name: unix user / agent instance name on host.
        on_event: optional `(phase, payload_dict)` callback for NDJSON.
        dry_run: when True, the workspace playbook runs in ansible-runner
            check mode (`--check`); no host writes occur (I6).

    Returns a `WorkspacePhaseResult`. A `False` `success` carries the
    failure message in `.error`; callers (sync / configure) decide
    whether to short-circuit downstream phases (W2 iter-1: workspace
    failure does not advance to restart).
    """
    valid, msg = validate_agent_name(agent_name)
    if not valid:
        return WorkspacePhaseResult(
            success=False,
            files_pushed=(),
            files_excluded=(),
            error=f"agent name rejected: {msg}",
        )

    spec = WorkspaceOverlaySpec.from_manifest(agent_type)
    if spec is None:
        # Agent has no overlay feature declared — silent no-op.
        return WorkspacePhaseResult(
            success=True, files_pushed=(), files_excluded=()
        )

    workspace_root = _local_workspace_root(agent_type, agent_name)
    entries, excluded, skipped = enumerate_workspace_files(
        workspace_root,
        spec,
        agent_name=agent_name,
        on_event=on_event,
    )

    if not entries:
        if on_event is not None:
            on_event(
                "push_workspace",
                {
                    "state": WORKSPACE_STATE_COMPLETE,
                    "files_pushed": [],
                    "files_excluded": [sanitize_passthrough(e) for e in excluded],
                },
            )
        return WorkspacePhaseResult(
            success=True,
            files_pushed=(),
            files_excluded=tuple(excluded),
            files_skipped=tuple(skipped),
        )

    # `ssh_key_path` is loaded lazily so the no-op path above doesn't
    # require host key state to be initialized.
    from clawrium.core.keys import get_host_private_key

    key_id = host.get("key_id") or host.get("hostname")
    ssh_key = get_host_private_key(key_id) if key_id else None
    if ssh_key is None:
        return WorkspacePhaseResult(
            success=False,
            files_pushed=(),
            files_excluded=tuple(excluded),
            files_skipped=tuple(skipped),
            error=f"no SSH key registered for host {key_id!r}",
        )

    os_family = host.get("os_family", "linux")
    try:
        playbook_path = resolve_agent_playbook(
            agent_type, "workspace", os_family
        )
    except FileNotFoundError as exc:
        return WorkspacePhaseResult(
            success=False,
            files_pushed=(),
            files_excluded=tuple(excluded),
            files_skipped=tuple(skipped),
            error=str(exc),
        )

    workspace_dest_root = _expand_destination_root(spec, agent_name)

    # Stage under `${clawrium_config}/staging/workspace/<name>/` so the
    # playbook's defense-in-depth substring check ('/clawrium/staging/
    # workspace/' in staging_dir) passes. Managed by
    # `tempfile.TemporaryDirectory` so the dir is cleaned up on every
    # exit path including ansible-runner crashes (W16 iter-2, U29/U30).
    staging_root = get_config_dir() / "staging" / "workspace"
    staging_root.mkdir(parents=True, exist_ok=True)

    import ansible_runner  # Local import keeps module import-cheap.

    success = True
    error: str | None = None
    private_data_dir_path: Path | None = None

    with tempfile.TemporaryDirectory(
        prefix=f"{agent_name}-", dir=str(staging_root)
    ) as staging_dir_str:
        staging_dir = Path(staging_dir_str)
        payload = _stage_files(entries, staging_dir)

        # Emit per-file queued events so NDJSON consumers see the intent
        # before ansible-runner begins.
        if on_event is not None:
            for entry in entries:
                on_event(
                    "push_workspace",
                    {
                        "state": WORKSPACE_STATE_QUEUED,
                        "path": sanitize_passthrough(entry.rel),
                        "remote_path": sanitize_passthrough(
                            f"{workspace_dest_root}/{entry.rel}"
                        ),
                        "mode": entry.mode,
                        "owner": entry.owner,
                    },
                )

        inventory = _build_inventory(host, str(ssh_key))
        # extravars carry the file list and destination root; they live
        # at the play level (passed via `extravars=`), not host vars,
        # so they appear under `private_data_dir/env/extravars` and are
        # cleaned up alongside the staging dir.
        extravars = {
            "agent_name": agent_name,
            "agent_type": agent_type,
            "workspace_dest_root": workspace_dest_root,
            "workspace_files": payload,
            "staging_dir": str(staging_dir),
        }

        private_data_dir = tempfile.mkdtemp(
            prefix=f"ws-{agent_name}-", dir=str(staging_root)
        )
        private_data_dir_path = Path(private_data_dir)

        try:
            run_result = ansible_runner.run(
                private_data_dir=private_data_dir,
                inventory=inventory,
                playbook=str(playbook_path),
                extravars=extravars,
                envvars={
                    "ANSIBLE_HOST_KEY_CHECKING": "False",
                    "ANSIBLE_PIPELINING": "True",
                },
                cmdline="--check" if dry_run else None,
                quiet=True,
                timeout=300,
            )

            status = getattr(run_result, "status", None)
            rc = getattr(run_result, "rc", None)
            if status != "successful" or rc not in (0, None):
                success = False
                error = (
                    f"workspace playbook failed for {agent_name!r} "
                    f"(status={status}, rc={rc})"
                )
        except Exception as exc:  # ansible-runner raised
            success = False
            error = f"workspace playbook crashed: {exc}"
        finally:
            # CWE-312: ansible-runner caches extravars under
            # `<private_data_dir>/env/extravars` and artifacts under
            # `<private_data_dir>/artifacts/<uuid>/`. Wipe the whole
            # temp dir tree so no operator path stays on disk past
            # the sync (S7 iter-3, U30).
            if private_data_dir_path is not None:
                shutil.rmtree(private_data_dir_path, ignore_errors=True)

    files_pushed_payload: list[str] = []
    if success:
        files_pushed_payload = [e.rel for e in entries]
        if on_event is not None:
            for entry in entries:
                on_event(
                    "push_workspace",
                    {
                        "state": WORKSPACE_STATE_PUSHED,
                        "path": sanitize_passthrough(entry.rel),
                        "remote_path": sanitize_passthrough(
                            f"{workspace_dest_root}/{entry.rel}"
                        ),
                        "mode": entry.mode,
                        "owner": entry.owner,
                    },
                )
            on_event(
                "push_workspace",
                {
                    "state": WORKSPACE_STATE_COMPLETE,
                    "files_pushed": [
                        sanitize_passthrough(p) for p in files_pushed_payload
                    ],
                    "files_excluded": [
                        sanitize_passthrough(e) for e in excluded
                    ],
                },
            )
    else:
        if on_event is not None:
            on_event(
                "push_workspace",
                {
                    "state": WORKSPACE_STATE_FAILED,
                    "reason": sanitize_passthrough(error or "unknown"),
                },
            )

    return WorkspacePhaseResult(
        success=success,
        files_pushed=tuple(files_pushed_payload),
        files_excluded=tuple(excluded),
        files_skipped=tuple(skipped),
        error=error,
    )
