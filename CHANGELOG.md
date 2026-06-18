## [Unreleased]

### Added

- `openclaw` agents can now attach `type=litellm` providers — custom OpenAI-compatible endpoints (LiteLLM, vLLM, any `/v1/chat/completions` proxy). `clawctl agent configure` / `clawctl agent sync` render a `models.providers.<provider-name>` block into `.openclaw/openclaw.json` with `api: "openai-completions"`, inline `apiKey`, and `baseUrl` normalized to `<endpoint>/v1`. The bearer lives in `openclaw.json` exclusively — no new `.openclaw/env` var emitted. Closes #723.