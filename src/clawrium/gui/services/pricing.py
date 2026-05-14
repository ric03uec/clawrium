"""Model pricing lookup for cost estimation.

Prices are per 1M tokens (USD). Sources:
- OpenAI: https://openai.com/api/pricing
- Anthropic: https://docs.anthropic.com/en/docs/about-claude/models
- Others: Best-effort from public pricing pages
"""

# {model_id: {"input": price_per_1M_input_tokens, "output": price_per_1M_output_tokens}}
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    # Anthropic
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    # Bedrock (same models, different IDs)
    "anthropic.claude-opus-4-20250514-v1:0": {"input": 15.00, "output": 75.00},
    "anthropic.claude-sonnet-4-20250514-v1:0": {"input": 3.00, "output": 15.00},
    "anthropic.claude-3-5-sonnet-20241022-v2:0": {"input": 3.00, "output": 15.00},
    "anthropic.claude-3-5-haiku-20241022-v1:0": {"input": 0.80, "output": 4.00},
    # Google
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # DeepSeek
    "deepseek/deepseek-chat-v3": {"input": 0.27, "output": 1.10},
    "deepseek/deepseek-r1": {"input": 0.55, "output": 2.19},
    # Meta
    "meta-llama/llama-4-maverick": {"input": 0.50, "output": 0.70},
}


def estimate_cost(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float | None:
    """Estimate cost in USD for a given usage.

    Returns None if model pricing is not available.
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        # Try partial match (model might have version suffix)
        for key, p in MODEL_PRICING.items():
            if model.startswith(key) or key.startswith(model):
                pricing = p
                break

    if not pricing:
        return None

    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
