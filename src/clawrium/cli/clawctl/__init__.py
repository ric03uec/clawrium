"""Stub group apps for `clawctl` noun-groups.

Each module in this package exports a Typer app for one top-level noun
(`host`, `agent`, `provider`, `channel`, `integration`, `skill`).
This bundle (#507) only registers the groups and stubs their verbs;
real implementations land in bundles 3-4 (#508, #509) by editing the
respective module files.

The convention for stub verbs is `not_implemented(group, verb)` — a
helper from `_stub` that prints `Not implemented: <group> <verb>` and
exits 0. This matches today's `clm snapshot` placeholder behavior.

Living under `clawrium.cli.clawctl.*` (not `clawrium.cli.*`) is
deliberate: the legacy `clm` CLI kept its modules at `clawrium.cli.*`
(`cli/agent.py`, `cli/chat.py`, etc.); the `clm` entry and orphan
modules were removed in #706 and #707 Phase 1 respectively, and the
remaining hybrids are tracked for removal in the follow-up phases of
#707. Splitting namespaces originally kept bundle 2 from touching any
legacy code path and now cleanly isolates the surviving hybrids until
they are migrated.
"""
