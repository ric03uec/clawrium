# Issue #1059 — Hermes Atlassian sync

## Goal
Ensure `clawctl agent sync` provisionally installs a reliable `uv` launcher for every Hermes agent with an attached Atlassian integration before canonical configuration is written and the service restarts.

## Plan
1. Change the canonical Hermes MCP render from the unprovisioned `uvx` path to the installed `uv` executable using `uv tool run --from mcp-atlassian==<pin> mcp-atlassian`.
2. Add dedicated Linux and macOS checksum-verified Atlassian installer runbooks. They retain a newer existing `uv`, install the pinned launcher only when missing or older, and follow the sync-time integration installer contract.
3. Invoke the installer from the Hermes canonical sync phase before config writes and restart, gate it on attached `atlassian` integrations, and surface installer failures as `CanonicalSyncError`.
4. Remove the obsolete configure-playbook bootstrap, add render, lifecycle ordering/failure/gating, runbook and direct pin-lockstep tests, then update canonical docs, website mirror, and changelog.
