---
name: daily-digest
description: Post a daily engineer-tone summary of the last 24h of activity on ric03uec/clawrium to Discord.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "daily"
  trigger: "cron"
  outputs: ["discord-message"]
---

# daily-digest

Once per day, summarize what happened on `ric03uec/clawrium` in the
last 24 hours and post it to the project's home Discord channel.

## Inputs (last 24h, in `ric03uec/clawrium`)

- Merged PRs — title, number, author, one-line summary you derive from
  the PR body.
- Issues opened — title, number, current labels.
- Issues closed — title, number, the closing PR if any.
- Your own run logs from the previous day (memory keyed
  `daily-digest:last-run`). Use it to avoid repeating the same items.

Commands:

```bash
gh pr list --repo ric03uec/clawrium --state merged --search \
  "merged:>$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --json number,title,author,body
gh issue list --repo ric03uec/clawrium --state open --search \
  "created:>$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --json number,title,labels
gh issue list --repo ric03uec/clawrium --state closed --search \
  "closed:>$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --json number,title,closedByPullRequestsReferences
```

## Output

A single Discord message in the home channel, structured as:

```
**clawrium digest — <YYYY-MM-DD>**

**Shipped (N)**
- #<num> <title> — <one-line summary>

**Opened (N)**
- #<num> <title> — <labels>

**Closed (N)**
- #<num> <title> — closed by #<pr>

Quiet day: <only if nothing material happened>
```

Send via the hermes Discord channel adapter (the agent already has the
home channel id bound). Do **not** open a thread; the message is the
unit.

## Voice

- Engineer to engineer. No marketing copy ("exciting", "robust",
  "delights"), no hedging through verbosity.
- Emoji only when it encodes information (✅ for a green CI run that
  unblocks a release; 🔒 for a security fix). Skip them for flair.
- Past tense for shipped; present tense for state ("Open: 14").
- If a single PR did the heavy lifting, say so explicitly — don't
  level the slope.

## Hard constraints

- One message per day. Idempotent — re-runs within the same day update
  rather than duplicate (track the last-message id in skill memory).
- Never `@here` or `@everyone`.
- If 0 PRs merged and 0 issues opened or closed, post a one-line
  "Quiet day on clawrium." entry — silence reads as "the bot is
  broken."

## Anti-patterns

- Paraphrasing each PR body into a paragraph. One line per PR.
- Listing internal refactors that did not change user-visible
  behavior. Group them: "+ 4 internal cleanups (#a, #b, #c, #d)".
- Restating yesterday's items. Use the run log to dedup.
