# Issue #1018 Plan

This execution child implements parent issue #994 as one sequential pull
request. The authoritative architecture and planning discussion are on #994.

## Scope

- Install Herdr only for Hermes and Claude Code.
- Hermes receives the documented Herdr integration; Claude receives only the
  shared binary.
- OpenClaw, ZeroClaw, and Ethos are excluded.
- Host mutations use Ansible only and installation is idempotent.

## Execution Boundary

Use a dedicated Herdr OS-specific playbook selected only for Hermes and Claude
between the generic base and agent install playbooks. Keep generic base
playbooks unchanged. Update canonical Hermes rendering so a later configure or
sync keeps the official Herdr configuration.

## Prompt Log

**Stage**: execution-child-creation
**Skill**: /itx-execute orchestrate
**Timestamp**: 2026-10-04T03:09:40Z
**Model**: openai/gpt-5.6-terra

```prompt
ok. you're the orchestrator now with a goal to complete this issue. YOU WILL
NOT EXECUTE any issue. use /itx-execute orchestrate to spin up tmux+pi(with
gpt terra) to execute each issue one at a time. use atx cli for reviews. steer
stacked prs till all issues are verified and completed. ask me any clarfyign
questionb efore ststarting but once you start contine till all the tasks are
```

**Output**: Created one linked execution child to preserve the requested one
implementation PR while satisfying orchestrate-mode subissue structure.
