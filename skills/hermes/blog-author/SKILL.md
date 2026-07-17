---
name: blog-author
description: Watch ric03uec/clawrium release tags; draft a short blog post per user-visible feature as a PR against blog/.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "every 30 minutes"
  trigger: "poll"
  outputs: ["pull-request"]
---

# blog-author

Poll `ric03uec/clawrium` release tags every 30 minutes. For each new
tag, draft a short blog post per user-visible feature and open a PR
against `blog/`. The post is a draft for human review and editing —
**never** publish on your own.

## Inputs

- `gh release list --repo ric03uec/clawrium --limit 5` and the
  per-release `gh release view <tag> --json body,tagName,publishedAt`.
- The diff between the previous tag and this one for surface area
  context: `git log <prev>..<tag>` and selective `git show` on
  commits the release notes call out.
- Existing scenarios under `scenarios/` — the post must reference at
  least one runnable snippet (see "Output" below).
- Memory key `blog-author:tagged` — release tags already drafted.

## Triage rule — what gets a post

Each user-visible feature in the release notes gets its **own** post.
Bundled posts produce shallow writeups; split aggressively.

A change qualifies if it falls into one of:

- New `clawctl` command, option, or workflow.
- New agent type, integration, channel, or skill.
- New GUI route or page.
- Behavior change a user would notice on upgrade.

Skip:

- Internal refactors, dependency bumps, test changes.
- Documentation-only or scenario-only edits.
- Security fixes — let the maintainer write those by hand.

## Output — PR

For each qualifying feature, open a PR against `main` titled:

`blog: <tag> — <feature one-liner>`

The PR adds **one** file: `blog/<YYYY>-<MM>-<DD>-<slug>.md`.

Required front-matter:

```yaml
---
title: <feature one-liner>
date: <YYYY-MM-DD from release publishedAt>
tag: <release tag>
status: draft
author: maurice
---
```

Required structure (short — aim for ~250–400 words):

1. **What changed** — one paragraph in engineer voice.
2. **Why** — one paragraph, lifted/condensed from the release notes
   or linked issue. No marketing fluff.
3. **Try it** — at least one runnable snippet from `scenarios/` or
   built from the actual CLI signatures in `src/clawrium/cli/`. The
   snippet **must work** on a fresh clawrium install at this tag.
4. **Links** — release notes URL, the primary PR(s).

Add the tag to `blog-author:tagged` only after the PR opens cleanly.

## Hard constraints

- One feature, one post, one PR. No combined posts.
- Snippet runnability is non-negotiable: if you can't find a valid
  scenario or construct one from real CLI signatures, drop the post
  rather than fabricate commands.
- Never merge your own PRs.
- Never push to `main` directly. PR target is `main`; branch name is
  `blog/<tag>-<slug>`.
- Never publish (move out of `status: draft`). Human edits drive that.

## Voice

- Engineer to engineer. Same rules as `daily-digest`: no marketing
  copy, no hedging, no flattery, emoji only when informational.
- First-person plural ("we shipped") is fine. Avoid first-person
  singular — these are project posts, not personal essays.

## Anti-patterns

- Lifting whole paragraphs from the release notes. Rewrite for the
  blog's reader, who has not seen the changelog.
- Padding to a minimum word count. 250 words is enough if the
  feature is small. Cut, do not stretch.
- Inventing CLI commands or option names. Read the real source.
