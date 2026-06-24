---
description: Check hermes / openclaw / zeroclaw upstream releases and open one parent + per-agent child GitHub issues when the manifest pin lags behind
---

Run the upstream-version sync pass for tracked agent types.

$ARGUMENTS

See `.opencode/skills/sync-upstream/SKILL.md` for the full skill — it
holds the upstream lookup commands (GitHub `release list` for hermes /
zeroclaw, `npm view openclaw dist-tags.latest` for openclaw), the
manifest-pin parser, the de-dup rules, and the parent + child issue
body templates.

This command is **read-only on the local repo and the running fleet** —
it never edits `manifest.yaml`, never restarts agents, never opens PRs.
It only opens GitHub issues, and only after the user types the literal
token `open-issues` at the confirmation prompt.

If `$ARGUMENTS` is non-empty, restrict the sync to the listed agent
types — each token MUST match the allow-list `{hermes, openclaw,
zeroclaw}` exactly. Any other value aborts the run.
