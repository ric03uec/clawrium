---
authors: [maurice]
tags: [release]
---
# New Provider, Refined UI: Clawrium’s June Update

This week, we made it easier to connect to AI proxy services and improved how you navigate the GUI. The changes are small but meaningful — no more guessing where to find your agents, and a new way to use LiteLLM-compatible backends.

<!-- truncate -->

## Add LiteLLM Provider for Proxy Gateways

You can now add LiteLLM, vLLM, or any OpenAI-compatible proxy as a provider. Just enter the base URL — like `http://192.168.1.100:8000/v1` — and the API key. The key is stored directly in the agent’s `config.yaml`, not in an environment variable. This means you can run two different proxies on the same host, each with its own key, without conflict. The system auto-discovers available models by calling `/v1/models` on startup. This is a Hermes-only feature for now (per #706); extension to other agent types is planned in a follow-up. If you use a proxy like Together.ai or Fireworks.ai, this is your on-ramp. You no longer need to run a separate config file or script to point your agent at a custom endpoint. The provider type is registered in the same way as OpenAI or Ollama. It’s a drop-in replacement for any service that speaks the OpenAI API. This reduces setup time from 15 minutes to 2.

Related: [#705](https://github.com/ric03uec/clawrium/issues/705)

## Move Fleet Agents to Dedicated Page

The Dashboard no longer shows your list of agents. That table has moved to a new "Agents" section in the sidebar. Now, the Dashboard is just metrics: uptime, model usage, and request rates. The change makes it easier to see at a glance which agents are running, which are offline, and who’s using them. Homelabbers with three or more machines can now scan their fleet without scrolling. Team leads get a clean, focused view of agent status — no more mixing performance data with inventory. The table shows agent name, type, host, status, and last seen. You can still start, stop, or view logs from this page. The separation helps you answer two different questions: "Is everything running?" (Dashboard) and "What agents do I have?" (Agents). It’s a small change, but it makes the interface more usable for daily use.

Related: [#701](https://github.com/ric03uec/clawrium/issues/701)

## Coming Soon Buttons with Upvote Path

The "MCPs", "Scheduled Jobs", and "Agent Builder" entries in the sidebar are no longer just grayed-out text. They’re now clickable buttons. Click one, and a modal opens with three options: upvote the GitHub issue, join the Discord discussion, or request a different feature. The upvote links go directly to the public issue trackers. This turns passive waiting into active input. If you’ve been waiting for scheduled jobs, you can now help bump the priority. Experimenters get a voice. The team gets real signals on what to build next. The modal is built on the same code as all other dialogs — it closes with Esc, has a backdrop, and returns focus to the button. It’s not a new UI component; it’s a new use of an existing one. The result: you no longer see a dead end. You see a path to influence.

Related: [#702](https://github.com/ric03uec/clawrium/issues/702), [#698](https://github.com/ric03uec/clawrium/issues/698), [#699](https://github.com/ric03uec/clawrium/issues/699), [#700](https://github.com/ric03uec/clawrium/issues/700)

## Settings Moved to Footer

The Settings button is no longer in the main navigation. It’s now in the footer, next to GitHub, Docs, and Discord. It has a gear icon and highlights when you’re on the settings page. This keeps the main menu focused on core features. You still find it quickly, but it’s not competing for space. Team leads won’t miss it. Homelabbers won’t be confused by a cluttered sidebar. The change is subtle, but it makes the interface feel more intentional. The footer is where users expect secondary actions — not primary ones. This aligns with how modern web apps work. You can still access settings from any page. The only difference is where the link lives. The change was made after user feedback: people were clicking "Settings" expecting to change their API keys, not to see a list of agents. This reorganization reduces confusion.

Related: [#702](https://github.com/ric03uec/clawrium/issues/702)

## Bedrock Provider Now Uses AWS Keys

Adding a Bedrock provider no longer asks for an API key. It now asks for your AWS Access Key ID, Secret Access Key, and region. This matches how AWS actually works. The provider list now shows columns: icon, type, model, used by, and created at. A new "Registry" tab shows all supported endpoint types and their model catalogs. You don’t need to migrate old records — they still work. This is a fix, not a breaking change. If you use Bedrock, this is the right way to connect now. The old API key field was misleading — it didn’t work with AWS IAM or temporary credentials. The new form supports all AWS auth methods, including role-based access. The region field defaults to `us-east-1` but can be changed. This change makes it possible to use Bedrock in any AWS region, not just the default. It’s a small form change, but it opens up a whole class of use cases.

Related: [#695](https://github.com/ric03uec/clawrium/issues/695)

## Openclaw Client-Server Protocol Now Compatible

The Openclaw daemon (v2026.5.28) and client (v2025.5.0) now negotiate protocol versions 3 and 4, eliminating the "protocol mismatch" error. Backward compatibility is confirmed for v2025.5.0 and later; support for older clients is under evaluation. This means you can upgrade your daemon on one host without breaking agents on other machines. Homelabbers can update one box at a time. AI experimenters can use older tools with the latest backend. No more waiting for everyone to upgrade in lockstep. The change was made by adding a version negotiation step in the handshake. The daemon now accepts both v3 and v4, and the client can speak either. The result: you can run a mix of old and new clients on the same network. This is especially helpful for teams that can’t update all machines at once. The change is transparent. You don’t need to re-pair. You don’t need to reconfigure. It just works. This backward compatibility is now part of our release policy.

Related: [#608](https://github.com/ric03uec/clawrium/issues/608)