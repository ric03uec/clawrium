---
authors: [maurice]
tags: [release]
---
# Organizing the Providers Experience

Managing your AI providers is now more organized. The Providers page has been split to separate active configurations from global discovery.

<!-- truncate -->

## Provider page restructure

The Providers page now uses a two-tab layout. You can switch between your active configurations and the global registry. This removes the clutter of having everything on one long page. It helps you focus on managing your current setup without distractions. Now, configuring a provider and browsing supported models are distinct actions. This structure makes the interface more intuitive for team leads managing multiple keys.

Related: [#694](https://github.com/ric03uec/clawrium/issues/694), [#696](https://github.com/ric03uec/clawrium/pull/696)

## Configured Providers table

Your active providers are now displayed in a clear table. You can see the provider name, type, and default model at a glance. A new "Used by" column shows which agents are using that specific provider. If no agent is attached, it is marked as "Unassigned". You can also check when each provider was created to track old configurations. This view makes it easier to audit your fleet's connectivity without digging into individual records.

Related: [#694](https://github.com/ric03uec/clawrium/issues/694), [#696](https://github.com/ric03uec/clawrium/pull/696)

## Registry tab

The model catalog has moved to its own dedicated Registry tab. This tab serves as a directory of all endpoint types Clawrium supports. You can expand each provider type to see the full list of available models. This separation means you no longer have to scroll to the bottom of the page to find model IDs. It provides a clean reference for what you can add to your environment. Experimenters can quickly find new models to test without losing their place in the config.

Related: [#694](https://github.com/ric03uec/clawrium/issues/694), [#696](https://github.com/ric03uec/clawrium/pull/696)

## Bedrock credentials

Setting up AWS Bedrock is now more accurate. The form no longer asks for a generic API key that Bedrock does not use. Instead, it requests your AWS Access Key ID and Secret Access Key. You can also specify your AWS Region, which defaults to us-east-1 but remains editable. This ensures that Bedrock providers are configured with the correct AWS authentication flow. AI experimenters can now deploy Bedrock agents without credential errors.

Related: [#694](https://github.com/ric03uec/clawrium/issues/694), [#696](https://github.com/ric03uec/clawrium/pull/696)

## Validation Metrics

These are the automated validation metrics for the features described
above. Numbers aggregate every [ATX](https://github.com/ric03uec/atx)
review iteration across the PRs that shipped these changes. ATX is
the multi-agent code review system that runs against every PR; the
metrics below reflect its work.

| Metric | Value |
|---|---|
| PRs covered | 1 |
| Automated review iterations | 4 |
| Blocking issues resolved | 17 |
| Total review cost | ~$8.52 |
| Total review time | ~21 min |
| Models used by [ATX](https://github.com/ric03uec/atx) | _Not exposed per agent today; see [#704](https://github.com/ric03uec/clawrium/issues/704)_ |
| Models used by gtm pipeline | gather: `qwen3-coder:30b-128k` · writer: `gemma4:31b` · reviewer: `qwen3-coder:30b-128k` |
