---
authors: [maurice]
tags: [release]
---
# Clawrium: New providers, better UI, and declarative fleet control

<!-- truncate -->

## Add any OpenAI-compatible LLM as a provider

You can now point a provider at any OpenAI-compatible API — including local models, self-hosted gateways, or third-party services like Anthropic, Mistral, or Perplexity. Just add a `litellm` provider with the URL and API key. No more waiting for official support. If the model speaks OpenAI’s API, clawctl can use it.

```bash
clawctl provider add my-llm-gateway --type litellm \
  --url http://192.168.1.100:8000/v1 \
  --api-key ***
```

Related: [#705](https://github.com/ric03uec/clawrium/issues/705), [#706](https://github.com/ric03uec/clawrium/pull/706)

## Use AWS Bedrock with multiple agents, one set of credentials

You can now attach multiple agents to the same AWS Bedrock model using a single set of credentials. No need to copy your AWS key to every host. The provider config is stored once, and any agent can reference it by name.

```bash
clawctl provider add bedrock-prod --type bedrock \
  --aws-access-key-id AKIA... \
  --aws-secret-access-key ... \
  --aws-region us-west-2

clawctl agent create agent1 --provider bedrock-prod --model bedrock.claude-3-5-sonnet
clawctl agent create agent2 --provider bedrock-prod --model bedrock.claude-3-5-sonnet
```

This reduces secret sprawl and makes rotating keys a single operation.

Related: [#692](https://github.com/ric03uec/clawrium/pull/692)

## New Providers page: clear, simple, and actionable

The Providers page is now a clean table. You see the name, type, and which agents are using it — all in one view. The old modal-based flow is gone. You can add, edit, or delete providers in the table. The UI no longer asks you to pick a model before you’ve even created the provider.

Related: [#694](https://github.com/ric03uec/clawrium/issues/694), [#695](https://github.com/ric03uec/clawrium/pull/695), [#696](https://github.com/ric03uec/clawrium/pull/696), [#697](https://github.com/ric03uec/clawrium/pull/697)

## Declarative fleet management with ethos

You can now define your entire agent fleet in a single YAML file. The `ethos` agent type is new. It reads a manifest and ensures your actual setup matches it. Need 3 openclaw agents on host A, 2 hermes on host B? Write it once. Run `clawctl ethos apply -f fleet.yaml`. The system adds, removes, or reconfigures agents to match.

```yaml
# fleet.yaml
agents:
  - name: research-01
    type: openclaw
    host: mybox
    provider: litellm-llama-3-70b
  - name: research-02
    type: openclaw
    host: mybox
    provider: litellm-llama-3-70b
  - name: dev-01
    type: hermes
    host: devbox
    provider: bedrock-prod
```

You can version this file, review it in PRs, and roll back if something breaks.

Related: [#632](https://github.com/ric03uec/clawrium/issues/632), [#633](https://github.com/ric03uec/clawrium/pull/633)

## Per-agent local skills, now in the GUI

You can now add, update, and remove custom skills for each agent directly in the GUI. No more SSHing to the host to copy files into `~/.config/clawrium/skills/`. The new Skills tab shows you which skills are installed, and you can upload a `.py` file with a single drag-and-drop.

The skill is stored on the agent’s host, not the GUI machine. It runs in the agent’s own environment, with its own Python path and dependencies.

Related: [#411](https://github.com/ric03uec/clawrium/issues/411), [#637](https://github.com/ric03uec/clawrium/pull/637), [#638](https://github.com/ric03uec/clawrium/pull/638)