# Pi OpenRouter and chat — interactive worker brief for #1038

You are the implementing Pi worker in interactive tmux, branch
`issue-1038-pi-openrouter`, based on `issue-1032-pi-agent` (PR #1044).
The human may attach to your session. Read `AGENTS.md`,
`.claude/skills/itx-execute/SKILL.md`, `.itx/1032/00_PLAN.md`, GitHub issue
#1038 and the preceding foundation PR. Follow the `/itx-execute` task
checklist, prompt log, verification and PR requirements, with the stricter
review and UAT gates below. Log this execution in `.itx/1038/01_EXECUTION.md`.

## Customer outcome and scope of this PR

An operator selects an **existing Clawrium OpenRouter provider and an actually
available Pi-supported model** in the control plane; Clawrium provisions the
selected model and agent-scoped credential to an isolated Pi account on the
fleet host. Pi consumes that access rather than requesting a grant. With no
manual Pi-side configuration, the operator gets a real answer via native exec,
two-turn CLI chat, and GUI chat with continuation and reset. GUI fleet detail
shows the selected provider/model while native Pi dashboard remains absent.

Deliver milestones 2 and 3 of the parent plan together. Implement bounded
provider/model mapping, configure/sync and safe credential handoff, a finite
on-demand Pi chat adapter with session continuity/reset, and CLI/GUI dispatch.
Explicitly reject unsupported models and missing access; avoid unsupported
multi-provider semantics and unintended mutation of other agent types. Preserve
the foundation's secure native exec and Linux/macOS lifecycle boundaries.
Update tests, user-facing docs and the root unreleased changelog. If
`docs/installation.md` changes, mirror its body verbatim to
`website/docs/installation.md` while preserving the website frontmatter.

## Live wolf-i gate (mandatory before PR)

Inspect redacted host/provider/model capabilities without exposing tokens.
Use a **new unique** Pi agent on `wolf-i` with an already-registered OpenRouter
provider (for example `clm-openrouter`, if actually present) and a confirmed
accessible model. Attach/sync, then get a nonempty correct authenticated model
answer using the actual Pi binary under the dedicated remote account. Exercise
native exec, CLI chat second-turn continuity, and real GUI chat continuation
and reset on that provisioned model; mocks, env-only checks, or a provider
entry alone do not count. Verify no daemon/native UI, credential isolation,
and no secrets in state, logs, review data or PR evidence. Remove the test
agent and confirm scoped remote/local cleanup and that existing fleet agents
remain. Clean up even on failure. `mac-test` was offline at foundation PR;
exercise macOS mapping with automated tests and disclose unverified live macOS
if still inaccessible. Do not use another production Mac without permission.

## Review/PR gate

- Run `make test` and `make lint` in this worktree; run meaningful regression
  checks for mapping, unsupported model, credential isolation, both chat
  surfaces and cleanup. No mocked result may be reported as a live response.
- Before committing, stage intended files, then run stateless
  `atx review request -p "Review the full diff of issue-1038-pi-openrouter against issue-1032-pi-agent for #1038 OpenRouter provisioning, real CLI/native/GUI Pi chat, session semantics and security. Read git diff issue-1032-pi-agent...HEAD plus git diff --cached and unstaged files. Rate /5, identify blocking findings." --format json --timeout 15m`.
  Do not use Claude-session `atx review`. Fix actual blockers and repeat until
  the rendered **leader rating is >3/5 and current blocking findings are
  empty**; check the rendered leader/body if metadata contradicts it. No PR
  while tests, review, or wolf-i live UAT is incomplete. Persist
  `.itx/1038/atx-session.json` and document review iterations.
- Inspect status/diff/log, commit only intended files and no credentials;
  push branch and create PR **base `issue-1032-pi-agent`**, not main. Include
  `Stacked on top of issue-1032-pi-agent`, ATX history, redacted real-host
  evidence, `Co-Authored-By: @atx-ci <269048218+atx-ci@users.noreply.github.com>`
  in both commit and PR, and `## Callouts` even if empty. Do not close parent
  #1032. Do not create #1039/#1040 branches or merge anything.
- When blocked, leave the interactive session open and report exact blocker
  without exposing secrets. The orchestrator starts the next worker only
  after this PR is open with passing checks and UAT.

## Original user instruction

> ok. fine. then use /itx-execute to implement this feature. you're the orchestrator and will NOT EXECUTE any code. you'll spin up tmux+pi(gpt terra, medium thinking) and ask that agent to execute these tasks. send stacked prs once atx review (use atx cli) are passing acording to the repo rules  use pi in an interactive mode so i can rview the changes if needed. send stacked prs when done. verify it on a real agent. use wolf-i as the test host to create a new agent and remove it. uAT is mandatory before you claim  you're done
