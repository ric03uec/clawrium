# Issue #305 — Bug Report (no plan yet)

Bug filed via `/itx:bug-new` on 2026-05-09. No implementation plan yet — run `/itx:plan-create 305` to scope a fix.

Surfaced while testing PR #304 (issue #163) against the `maurice` openclaw agent on `wolf-i`. The version-aware skip path could not fire because the runtime binary the systemd service executes (`/usr/local/bin/openclaw`, found via `which openclaw`) drifts in version from the per-agent install location (`/home/<agent>/.openclaw/bin/openclaw`). Result: every reinstall rotates gateway token + device credentials.

See issue body on GitHub for full reproducer and three suggested fix directions.

---

<details>
<summary>Prompt Log</summary>

**Stage**: bug-creation
**Skill**: /itx:bug-new
**Timestamp**: 2026-05-09T19:05:00Z
**Model**: claude-opus-4-7

```prompt
yes add a bug with details
[surfaced from prior conversation: testing PR #304 on wolf-i/maurice revealed
 that /usr/local/bin/openclaw drifts in version from per-agent install path,
 making the new version-aware skip path unreachable on hosts in this state]
```

</details>
