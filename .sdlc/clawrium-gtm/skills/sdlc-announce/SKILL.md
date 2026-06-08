---
name: sdlc-announce
description: SDLC pipeline GTM — announces a merged PR to #announcements and updates CHANGELOG.md [Unreleased] if needed.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "on-demand"
  trigger: "manual"
  outputs: ["discord-message", "pull-request"]
---

# sdlc-announce

GTM close-the-loop skill. Given a merged PR number, post a human-readable
announcement and optionally update the CHANGELOG.

## Inputs

- PR number P (required)
- Issue number N (required — the issue the PR closes)
- Repo: `ric03uec/clawrium`

## Steps

1. Fetch PR metadata and diff summary:
   ```bash
   gh pr view <P> --repo ric03uec/clawrium --json title,body,mergedAt,url,files
   ```

2. Verify PR is merged. If not: stop with message "PR #<P> is not merged yet".

3. Compose announcement (one paragraph, ≤ 120 words):
   ```
   **Shipped: <PR title>**
   <1–2 sentences describing what changed and why it matters to users>
   PR: <url>
   ```
   Base this on the actual diff — do not copy the PR title blindly.

4. Post to Discord `#announcements`:
   - Channel ID: `1494197384094416906` (Clawrium Discord server, #announcements)
   - Send as a plain message (no embeds for MVP)

5. Check `CHANGELOG.md [Unreleased]` in the repo. Clone or pull first:
   ```bash
   git -C ~/sdlc-gtm/clawrium pull
   ```

6. If the merged change is user-visible (not docs-only, not chore) and not
   already mentioned under `[Unreleased]`:
   - Add a one-liner under the appropriate sub-heading (Added / Changed / Fixed)
   - Open PR `docs/gtm/<P>-changelog` → `main`
   - Title: `docs(changelog): record #<P> in [Unreleased]`

7. If the Discord token is missing or the channel is unreachable, write the
   announcement to `~/.hermes/gtm-pending/<P>.txt` and stop. Do NOT silently
   discard it.

## Hard Constraints

- Post ONLY to `#announcements`. No DMs, no other channels.
- Never merge the changelog PR yourself.
- Docs-only or chore PRs: post a one-liner in `#announcements`, skip CHANGELOG.
- If you cannot determine what changed (empty diff), post "Merged #<P> — <title>"
  and stop.
