# skills/zeroclaw/

Native zeroclaw skills. Files placed here are installable **only** onto
agents of type `zeroclaw`. The CLI rejects cross-claw installs with
`IncompatibleSkillRegistry` (Phase 2).

Layout:

```
skills/zeroclaw/<name>/
└── SKILL.md   # frontmatter validated against _schema/native/zeroclaw.schema.json
```

Native zeroclaw installs go through `zeroclaw skills install` (v0.7.5
audit gate). The on-disk source directory name MUST match the registry
slug `<name>`, because `zeroclaw skills remove` keys on the source
directory name, not the SKILL.md `name:` field — see
[`.itx/364/02_PHASE0_FINDINGS.md`](../../.itx/364/02_PHASE0_FINDINGS.md).

A cross-agent skill belongs in `skills/clawrium/` instead — see the
top-level [`skills/README.md`](../README.md). No native zeroclaw skills
ship in this initial cut; this directory is a registered registry so that
`clawctl skill list --registry zeroclaw` returns an empty list rather than a
"registry not found" error.
