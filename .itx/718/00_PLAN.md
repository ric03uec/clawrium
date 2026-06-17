# Issue #718 — macOS Remote Login prerequisite

See the revised plan posted as the latest comment on issue #718 (tagged
2026-06-17) for the full plan; this file captures the artifact pointer
required by AGENTS.md.

## Summary

Surface the "enable Remote Login first" instruction for macOS hosts in two
places:

1. `docs/host-preparation.md` (mirrored to
   `website/docs/guides/host-setup.md`) — new top-level `Step 1.5`
   between Steps 1 and 2.
2. `src/clawrium/cli/clawctl/host/create.py` — separate macOS preflight
   print block before the existing SSH-paste block in
   `_print_manual_setup`.

Plus a CHANGELOG entry and three new ordering/framing assertions in
`tests/cli/clawctl/host/test_create_delete.py`.
