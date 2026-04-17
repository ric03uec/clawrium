# OpenRouter

**Status:** ✅ Supported

OpenRouter provides unified access to multiple AI models through a single API.

## Supported Models

<!-- MODEL-TABLE:START -->
### Anthropic

| Model ID | Name | Context |
|----------|------|---------|
| `anthropic/claude-3.5-haiku` | Claude Haiku 3.5 | 200K |
| `anthropic/claude-haiku-4.5` | Claude Haiku 4.5 | 200K |
| `anthropic/claude-opus-4` | Claude Opus 4 | 200K |
| `anthropic/claude-opus-4.1` | Claude Opus 4.1 | 200K |
| `anthropic/claude-opus-4.5` | Claude Opus 4.5 | 200K |
| `anthropic/claude-opus-4.6` | Claude Opus 4.6 | 1M |
| `anthropic/claude-opus-4.7` | Claude Opus 4.7 | 1M |
| `anthropic/claude-3.7-sonnet` | Claude Sonnet 3.7 | 200K |
| `anthropic/claude-sonnet-4` | Claude Sonnet 4 | 200K |
| `anthropic/claude-sonnet-4.5` | Claude Sonnet 4.5 | 1M |
| `anthropic/claude-sonnet-4.6` | Claude Sonnet 4.6 | 1M |

### Arcee Ai

| Model ID | Name | Context |
|----------|------|---------|
| `arcee-ai/trinity-large-preview:free` | Trinity Large Preview | 131K |
| `arcee-ai/trinity-large-thinking` | Trinity Large Thinking | 262K |

### Black Forest Labs

| Model ID | Name | Context |
|----------|------|---------|
| `black-forest-labs/flux.2-flex` | FLUX.2 Flex | 67K |
| `black-forest-labs/flux.2-klein-4b` | FLUX.2 Klein 4B | 40K |
| `black-forest-labs/flux.2-max` | FLUX.2 Max | 46K |
| `black-forest-labs/flux.2-pro` | FLUX.2 Pro | 46K |

### Bytedance Seed

| Model ID | Name | Context |
|----------|------|---------|
| `bytedance-seed/seedream-4.5` | Seedream 4.5 | 4K |

### Cognitivecomputations

| Model ID | Name | Context |
|----------|------|---------|
| `cognitivecomputations/dolphin-mistral-24b-venice-edition:free` | Uncensored (free) | 32K |

### Deepseek

| Model ID | Name | Context |
|----------|------|---------|
| `deepseek/deepseek-r1-distill-llama-70b` | DeepSeek R1 Distill Llama 70B | 8K |
| `deepseek/deepseek-chat-v3-0324` | DeepSeek V3 0324 | 16K |
| `deepseek/deepseek-v3.1-terminus` | DeepSeek V3.1 Terminus | 131K |
| `deepseek/deepseek-v3.1-terminus:exacto` | DeepSeek V3.1 Terminus (exacto) | 131K |
| `deepseek/deepseek-v3.2` | DeepSeek V3.2 | 163K |
| `deepseek/deepseek-v3.2-speciale` | DeepSeek V3.2 Speciale | 163K |
| `deepseek/deepseek-chat-v3.1` | DeepSeek-V3.1 | 163K |
| `deepseek/deepseek-r1` | DeepSeek: R1 | 64K |

### Google

| Model ID | Name | Context |
|----------|------|---------|
| `google/gemini-2.0-flash-001` | Gemini 2.0 Flash | 1M |
| `google/gemini-2.5-flash` | Gemini 2.5 Flash | 1M |
| `google/gemini-2.5-flash-lite` | Gemini 2.5 Flash Lite | 1M |
| `google/gemini-2.5-flash-lite-preview-09-2025` | Gemini 2.5 Flash Lite Preview 09-25 | 1M |
| `google/gemini-2.5-flash-preview-09-2025` | Gemini 2.5 Flash Preview 09-25 | 1M |
| `google/gemini-2.5-pro` | Gemini 2.5 Pro | 1M |
| `google/gemini-2.5-pro-preview-05-06` | Gemini 2.5 Pro Preview 05-06 | 1M |
| `google/gemini-2.5-pro-preview-06-05` | Gemini 2.5 Pro Preview 06-05 | 1M |
| `google/gemini-3-flash-preview` | Gemini 3 Flash Preview | 1M |
| `google/gemini-3-pro-preview` | Gemini 3 Pro Preview | 1M |
| `google/gemini-3.1-flash-lite-preview` | Gemini 3.1 Flash Lite Preview | 1M |
| `google/gemini-3.1-pro-preview` | Gemini 3.1 Pro Preview | 1M |
| `google/gemini-3.1-pro-preview-customtools` | Gemini 3.1 Pro Preview Custom Tools | 1M |
| `google/gemma-2-9b-it` | Gemma 2 9B | 8K |
| `google/gemma-3-12b-it` | Gemma 3 12B | 131K |
| `google/gemma-3-12b-it:free` | Gemma 3 12B (free) | 32K |
| `google/gemma-3-27b-it` | Gemma 3 27B | 96K |
| `google/gemma-3-27b-it:free` | Gemma 3 27B (free) | 131K |
| `google/gemma-3-4b-it` | Gemma 3 4B | 96K |
| `google/gemma-3-4b-it:free` | Gemma 3 4B (free) | 32K |
| `google/gemma-3n-e2b-it:free` | Gemma 3n 2B (free) | 8K |
| `google/gemma-3n-e4b-it` | Gemma 3n 4B | 32K |
| `google/gemma-3n-e4b-it:free` | Gemma 3n 4B (free) | 8K |
| `google/gemma-4-26b-a4b-it` | Gemma 4 26B A4B | 262K |
| `google/gemma-4-26b-a4b-it:free` | Gemma 4 26B A4B (free) | 262K |
| `google/gemma-4-31b-it` | Gemma 4 31B | 262K |
| `google/gemma-4-31b-it:free` | Gemma 4 31B (free) | 262K |

### Inception

| Model ID | Name | Context |
|----------|------|---------|
| `inception/mercury-2` | Mercury 2 | 128K |
| `inception/mercury-edit-2` | Mercury Edit 2 | 128K |

### Liquid

| Model ID | Name | Context |
|----------|------|---------|
| `liquid/lfm-2.5-1.2b-instruct:free` | LFM2.5-1.2B-Instruct (free) | 131K |
| `liquid/lfm-2.5-1.2b-thinking:free` | LFM2.5-1.2B-Thinking (free) | 131K |

### Meta Llama

| Model ID | Name | Context |
|----------|------|---------|
| `meta-llama/llama-3.2-11b-vision-instruct` | Llama 3.2 11B Vision Instruct | 131K |
| `meta-llama/llama-3.2-3b-instruct:free` | Llama 3.2 3B Instruct (free) | 131K |
| `meta-llama/llama-3.3-70b-instruct:free` | Llama 3.3 70B Instruct (free) | 131K |

### Minimax

| Model ID | Name | Context |
|----------|------|---------|
| `minimax/minimax-m1` | MiniMax M1 | 1M |
| `minimax/minimax-m2` | MiniMax M2 | 196K |
| `minimax/minimax-m2.1` | MiniMax M2.1 | 204K |
| `minimax/minimax-m2.5` | MiniMax M2.5 | 204K |
| `minimax/minimax-m2.5:free` | MiniMax M2.5 (free) | 204K |
| `minimax/minimax-m2.7` | MiniMax M2.7 | 204K |
| `minimax/minimax-01` | MiniMax-01 | 1M |

### Mistralai

| Model ID | Name | Context |
|----------|------|---------|
| `mistralai/codestral-2508` | Codestral 2508 | 256K |
| `mistralai/devstral-2512` | Devstral 2 2512 | 262K |
| `mistralai/devstral-medium-2507` | Devstral Medium | 131K |
| `mistralai/devstral-small-2505` | Devstral Small | 128K |
| `mistralai/devstral-small-2507` | Devstral Small 1.1 | 131K |
| `mistralai/mistral-medium-3` | Mistral Medium 3 | 131K |
| `mistralai/mistral-medium-3.1` | Mistral Medium 3.1 | 262K |
| `mistralai/mistral-small-3.1-24b-instruct` | Mistral Small 3.1 24B Instruct | 128K |
| `mistralai/mistral-small-3.2-24b-instruct` | Mistral Small 3.2 24B Instruct | 96K |
| `mistralai/mistral-small-2603` | Mistral Small 4 | 262K |

### Moonshotai

| Model ID | Name | Context |
|----------|------|---------|
| `moonshotai/kimi-k2` | Kimi K2 | 131K |
| `moonshotai/kimi-k2-0905` | Kimi K2 Instruct 0905 | 262K |
| `moonshotai/kimi-k2-0905:exacto` | Kimi K2 Instruct 0905 (exacto) | 262K |
| `moonshotai/kimi-k2-thinking` | Kimi K2 Thinking | 262K |
| `moonshotai/kimi-k2.5` | Kimi K2.5 | 262K |

### Nousresearch

| Model ID | Name | Context |
|----------|------|---------|
| `nousresearch/hermes-3-llama-3.1-405b:free` | Hermes 3 405B Instruct (free) | 131K |
| `nousresearch/hermes-4-405b` | Hermes 4 405B | 131K |
| `nousresearch/hermes-4-70b` | Hermes 4 70B | 131K |

### Nvidia

| Model ID | Name | Context |
|----------|------|---------|
| `nvidia/nemotron-3-nano-30b-a3b:free` | Nemotron 3 Nano 30B A3B (free) | 256K |
| `nvidia/nemotron-3-super-120b-a12b` | Nemotron 3 Super | 262K |
| `nvidia/nemotron-3-super-120b-a12b:free` | Nemotron 3 Super (free) | 262K |
| `nvidia/nemotron-nano-12b-v2-vl:free` | Nemotron Nano 12B 2 VL (free) | 128K |
| `nvidia/nemotron-nano-9b-v2:free` | Nemotron Nano 9B V2 (free) | 128K |
| `nvidia/nemotron-nano-9b-v2` | nvidia-nemotron-nano-9b-v2 | 131K |

### Openai

| Model ID | Name | Context |
|----------|------|---------|
| `openai/gpt-oss-120b` | GPT OSS 120B | 131K |
| `openai/gpt-oss-120b:exacto` | GPT OSS 120B (exacto) | 131K |
| `openai/gpt-oss-20b` | GPT OSS 20B | 131K |
| `openai/gpt-oss-safeguard-20b` | GPT OSS Safeguard 20B | 131K |
| `openai/gpt-4.1` | GPT-4.1 | 1M |
| `openai/gpt-4.1-mini` | GPT-4.1 Mini | 1M |
| `openai/gpt-4o-mini` | GPT-4o-mini | 128K |
| `openai/gpt-5` | GPT-5 | 400K |
| `openai/gpt-5-chat` | GPT-5 Chat (latest) | 400K |
| `openai/gpt-5-codex` | GPT-5 Codex | 400K |
| `openai/gpt-5-image` | GPT-5 Image | 400K |
| `openai/gpt-5-mini` | GPT-5 Mini | 400K |
| `openai/gpt-5-nano` | GPT-5 Nano | 400K |
| `openai/gpt-5-pro` | GPT-5 Pro | 400K |
| `openai/gpt-5.1` | GPT-5.1 | 400K |
| `openai/gpt-5.1-chat` | GPT-5.1 Chat | 128K |
| `openai/gpt-5.1-codex` | GPT-5.1-Codex | 400K |
| `openai/gpt-5.1-codex-max` | GPT-5.1-Codex-Max | 400K |
| `openai/gpt-5.1-codex-mini` | GPT-5.1-Codex-Mini | 400K |
| `openai/gpt-5.2` | GPT-5.2 | 400K |
| `openai/gpt-5.2-chat` | GPT-5.2 Chat | 128K |
| `openai/gpt-5.2-pro` | GPT-5.2 Pro | 400K |
| `openai/gpt-5.2-codex` | GPT-5.2-Codex | 400K |
| `openai/gpt-5.3-codex` | GPT-5.3-Codex | 400K |
| `openai/gpt-5.4` | GPT-5.4 | 1M |
| `openai/gpt-5.4-mini` | GPT-5.4 Mini | 400K |
| `openai/gpt-5.4-nano` | GPT-5.4 Nano | 400K |
| `openai/gpt-5.4-pro` | GPT-5.4 Pro | 1M |
| `openai/gpt-oss-120b:free` | gpt-oss-120b (free) | 131K |
| `openai/gpt-oss-20b:free` | gpt-oss-20b (free) | 131K |
| `openai/o4-mini` | o4 Mini | 200K |

### Openrouter

| Model ID | Name | Context |
|----------|------|---------|
| `openrouter/elephant-alpha` | Elephant (free) | 262K |
| `openrouter/free` | Free Models Router | 200K |

### Prime Intellect

| Model ID | Name | Context |
|----------|------|---------|
| `prime-intellect/intellect-3` | Intellect 3 | 131K |

### Qwen

| Model ID | Name | Context |
|----------|------|---------|
| `qwen/qwen-2.5-coder-32b-instruct` | Qwen2.5 Coder 32B Instruct | 32K |
| `qwen/qwen2.5-vl-72b-instruct` | Qwen2.5 VL 72B Instruct | 32K |
| `qwen/qwen3-235b-a22b-07-25` | Qwen3 235B A22B Instruct 2507 | 262K |
| `qwen/qwen3-235b-a22b-thinking-2507` | Qwen3 235B A22B Thinking 2507 | 262K |
| `qwen/qwen3-30b-a3b-instruct-2507` | Qwen3 30B A3B Instruct 2507 | 262K |
| `qwen/qwen3-30b-a3b-thinking-2507` | Qwen3 30B A3B Thinking 2507 | 262K |
| `qwen/qwen3-coder` | Qwen3 Coder | 262K |
| `qwen/qwen3-coder:exacto` | Qwen3 Coder (exacto) | 131K |
| `qwen/qwen3-coder-30b-a3b-instruct` | Qwen3 Coder 30B A3B Instruct | 160K |
| `qwen/qwen3-coder-flash` | Qwen3 Coder Flash | 128K |
| `qwen/qwen3-max` | Qwen3 Max | 262K |
| `qwen/qwen3-next-80b-a3b-instruct` | Qwen3 Next 80B A3B Instruct | 262K |
| `qwen/qwen3-next-80b-a3b-thinking` | Qwen3 Next 80B A3B Thinking | 262K |
| `qwen/qwen3.5-397b-a17b` | Qwen3.5 397B A17B | 262K |
| `qwen/qwen3.5-plus-02-15` | Qwen3.5 Plus 2026-02-15 | 1M |
| `qwen/qwen3.6-plus` | Qwen3.6 Plus | 1M |
| `qwen/qwen3.5-flash-02-23` | Qwen: Qwen3.5-Flash | 1M |

### Sourceful

| Model ID | Name | Context |
|----------|------|---------|
| `sourceful/riverflow-v2-fast-preview` | Riverflow V2 Fast Preview | 8K |
| `sourceful/riverflow-v2-max-preview` | Riverflow V2 Max Preview | 8K |
| `sourceful/riverflow-v2-standard-preview` | Riverflow V2 Standard Preview | 8K |

### Stepfun

| Model ID | Name | Context |
|----------|------|---------|
| `stepfun/step-3.5-flash` | Step 3.5 Flash | 256K |

### X Ai

| Model ID | Name | Context |
|----------|------|---------|
| `x-ai/grok-3` | Grok 3 | 131K |
| `x-ai/grok-3-beta` | Grok 3 Beta | 131K |
| `x-ai/grok-3-mini` | Grok 3 Mini | 131K |
| `x-ai/grok-3-mini-beta` | Grok 3 Mini Beta | 131K |
| `x-ai/grok-4` | Grok 4 | 256K |
| `x-ai/grok-4-fast` | Grok 4 Fast | 2M |
| `x-ai/grok-4.1-fast` | Grok 4.1 Fast | 2M |
| `x-ai/grok-4.20-beta` | Grok 4.20 Beta | 2M |
| `x-ai/grok-4.20-multi-agent-beta` | Grok 4.20 Multi - Agent Beta | 2M |
| `x-ai/grok-code-fast-1` | Grok Code Fast 1 | 256K |

### Xiaomi

| Model ID | Name | Context |
|----------|------|---------|
| `xiaomi/mimo-v2-flash` | MiMo-V2-Flash | 262K |
| `xiaomi/mimo-v2-omni` | MiMo-V2-Omni | 262K |
| `xiaomi/mimo-v2-pro` | MiMo-V2-Pro | 1M |

### Z Ai

| Model ID | Name | Context |
|----------|------|---------|
| `z-ai/glm-4.5` | GLM 4.5 | 128K |
| `z-ai/glm-4.5-air` | GLM 4.5 Air | 128K |
| `z-ai/glm-4.5-air:free` | GLM 4.5 Air (free) | 128K |
| `z-ai/glm-4.5v` | GLM 4.5V | 64K |
| `z-ai/glm-4.6` | GLM 4.6 | 200K |
| `z-ai/glm-4.6:exacto` | GLM 4.6 (exacto) | 200K |
| `z-ai/glm-4.7` | GLM-4.7 | 204K |
| `z-ai/glm-4.7-flash` | GLM-4.7-Flash | 200K |
| `z-ai/glm-5` | GLM-5 | 202K |
| `z-ai/glm-5-turbo` | GLM-5-Turbo | 202K |
| `z-ai/glm-5.1` | GLM-5.1 | 202K |
<!-- MODEL-TABLE:END -->

## Setup

### 1. Get API Key

1. Visit [OpenRouter](https://openrouter.ai/)
2. Create or log in to your account
3. Go to **Keys** → **Create Key**
4. Copy the key

### 2. Add to Clawrium

```bash
clm provider add my-router --type openrouter
```

You will be prompted to enter your API key securely.

### 3. Select Model

Choose from OpenRouter's extensive model list:
- `anthropic/claude-opus-4` (best quality)
- `google/gemini-2.5-pro` (competitive pricing)
- `openai/gpt-4o` (familiar API)

## Configuration

```bash
# View provider details
clm provider list

# Change default model
clm provider edit my-router --model anthropic/claude-sonnet-4

# Update API key
clm provider edit my-router --update-key

# Remove provider
clm provider remove my-router
```

## Benefits

- **Model fallback:** Automatically route to available models
- **Unified billing:** One account for multiple providers
- **Competitive pricing:** Often cheaper than direct provider access
- **Model variety:** Access to open-source and proprietary models

## Pricing

OpenRouter adds a small fee on top of provider costs. Check [OpenRouter pricing](https://openrouter.ai/docs#pricing) for current rates.

## Usage in Agents

During agent onboarding:

```bash
clm agent configure my-agent
# Select my-router when prompted for provider
```

## Model Routing

You can switch models without changing providers:

```bash
clm provider edit my-router --model deepseek/deepseek-chat-v3
```

Then restart your agent to use the new model.

## Troubleshooting

**"Model not available"**
- Check OpenRouter model status page
- Some models may have temporary outages
- Try a fallback model

**"Credits exhausted"**
- Add credits in OpenRouter dashboard
- Set up auto-recharge for production use

---

[Back to Providers](index.md)
