---
authors: [maurice]
tags: [release]
---
# Declarative Fleets and Agent Expansion

This week we introduced declarative fleet management and the new Ethos agent type, expanded the flexibility of provider attachments, and enhanced agent skillset capabilities.

<!-- truncate -->

## Declarative Fleet Management and Ethos

Users can now deploy and manage Ethos agents declaratively without manual SSH steps. The new declarative model allows describing the entire fleet in a single YAML manifest. You can run `clawctl apply -f fleet.yaml` to synchronize the actual state of your hosts, providers, and agents. A new `clawctl diff` command lets you preview exactly what will change—such as agent version bumps or provider attachments—before applying a manifest. This eliminates the need for long, fragile sequences of imperative commands. Upgrading an agent is now as simple as bumping a version number in the YAML and re-running the apply command. Remote Ethos CLI commands, like checking status or errors, are now accessible via `clawctl agent exec`.

Related: [#570](https://github.com/ric03uec/clawrium/issues/570), [#632](https://github.com/ric03uec/clawrium/issues/632), [#633](https://github.com/ric03uec/clawrium/pull/633)

## Multi-Provider Hermes Agents

Hermes agents now support multiple provider attachments with specialized roles. Operators can designate one primary provider for general chat and assign auxiliaries for tasks like `vision` or `web_extract`. This enables a heterogeneous setup, where a high-end cloud API handles primary logic while a cheap local model handles `compression` or `title_generation`. `clawctl agent sync` now ensures every attached provider and its associated API key is correctly materialized on the remote host. Fixed render bugs now prevent the system from silently dropping auxiliary providers during the sync process. Users no longer have to worry about their multi-provider configuration being ignored by the remote daemon.

Related: [#589](https://github.com/ric03uec/clawrium/issues/589), [#621](https://github.com/ric03uec/clawrium/issues/621), [#622](https://github.com/ric03uec/clawrium/issues/622), [#627](https://github.com/ric03uec/clawrium/pull/627)

## Per-Agent Local Skills

Agents can now be equipped with ad-hoc local skills that do not require registration in the global registry. This allows team leads to provide agent-specific tools tailored to a particular project without modifying the central catalog. Local skills are stored in a per-agent directory, ensuring that experimental tools don't leak into the wider fleet. The system provides native materialization helpers for Hermes, Openclaw, and Zeroclaw, ensuring consistent behavior across agent types. Comprehensive new documentation now explains how to implement and deploy these local skillsets. This approach allows AI experimenters to iterate on toolsets rapidly without the overhead of formal registry updates.

Related: [#411](https://github.com/ric03uec/clawrium/issues/411), [#653](https://github.com/ric03uec/clawrium/issues/653), [#636](https://github.com/ric03uec/clawrium/pull/636), [#655](https://github.com/ric03uec/clawrium/pull/655)

## Validation Metrics

These are the automated validation metrics for the features
described above. Numbers aggregate every [ATX](https://github.com/atx-ci)
review iteration across the PRs that shipped these changes. ATX
is the multi-agent code review system that runs against every
PR; the metrics below reflect its work.

| Metric | Value |
|---|---|
| PRs covered | 4 |
| Automated review iterations | 6 |
| Blocking issues resolved | 4 |
| Total review cost | ~$15.90 |
| Total review time | ~32 min |
| Models used by [ATX](https://github.com/atx-ci) | _Not exposed per agent today; see [#704](https://github.com/ric03uec/clawrium/issues/704)_ |
| Models used by gtm pipeline | gather: operator-pre-fetched + qwen3-coder:30b-128k assembly · writer: gemma4:31b · reviewer: qwen3-coder:30b-128k |
