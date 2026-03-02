"""Model pricing calculations for LLM usage tracking.

Provides ``calc_price()`` for computing token costs per model,
used by the Langfuse instrumentation layer to attach cost details
to generation spans.

Supports both static (fixed-rate) and dynamic (context-length-based)
pricing models.  All prices are in USD per 1M tokens.

Sources:
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
- OpenAI: https://platform.openai.com/docs/pricing
- Google: https://ai.google.dev/gemini-api/docs/pricing
- DeepSeek: https://api-docs.deepseek.com/quick_start/pricing
"""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field
from pydantic_ai.usage import RequestUsage

K = 1_000
M = 1_000_000


class Price(TypedDict):
    input: float
    output: float
    cache_read_input_tokens: float
    cache_creation_input_tokens: float
    reasoning_tokens: float
    total: float


class Usage(TypedDict):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    reasoning_tokens: int
    total: int


class DynamicPricingModel(BaseModel):
    """Pricing model with rates that vary based on input context length.

    Thresholds are token counts; rates are per-1M-tokens prices.
    If input exceeds a threshold, the higher rate applies to ALL tokens.
    """

    input_tokens_1M_price: dict[int, float]
    output_tokens_1M_price: dict[int, float]
    cache_read_input_tokens_1M_price: dict[int, float] = Field(default_factory=dict)
    cache_creation_input_tokens_1M_price: dict[int, float] = Field(default_factory=dict)

    def calculate(self, usage: Usage) -> Price:
        raw_input_tokens = max(
            0,
            usage["input_tokens"] - usage["cache_read_input_tokens"] - usage["cache_creation_input_tokens"],
        )

        sorted_tiers = sorted(self.input_tokens_1M_price.keys())
        if not sorted_tiers:
            return _zero_price()

        active_threshold = sorted_tiers[-1]
        for threshold in sorted_tiers:
            if raw_input_tokens <= threshold:
                active_threshold = threshold
                break

        def _get(price_dict: dict[int, float], t: int) -> float:
            return price_dict.get(t, 0.0) if price_dict else 0.0

        input_cost = raw_input_tokens * _get(self.input_tokens_1M_price, active_threshold) / M
        output_cost = usage["output_tokens"] * _get(self.output_tokens_1M_price, active_threshold) / M
        cache_read_cost = (
            usage["cache_read_input_tokens"] * _get(self.cache_read_input_tokens_1M_price, active_threshold) / M
        )
        cache_creation_cost = (
            usage["cache_creation_input_tokens"] * _get(self.cache_creation_input_tokens_1M_price, active_threshold) / M
        )
        reasoning_cost = usage["reasoning_tokens"] * _get(self.output_tokens_1M_price, active_threshold) / M
        total_cost = input_cost + output_cost + cache_read_cost + cache_creation_cost

        return {
            "input": input_cost,
            "output": output_cost,
            "cache_read_input_tokens": cache_read_cost,
            "cache_creation_input_tokens": cache_creation_cost,
            "reasoning_tokens": reasoning_cost,
            "total": total_cost,
        }


class StaticPricingModel(BaseModel):
    """Pricing model with fixed rates regardless of context length."""

    input_tokens_1M_price: float
    output_tokens_1M_price: float
    cache_read_input_tokens_1M_price: float = 0
    cache_creation_input_tokens_1M_price: float = 0

    def calculate(self, usage: Usage) -> Price:
        raw_input_tokens = max(0, usage["input_tokens"] - usage["cache_read_input_tokens"])

        input_cost = raw_input_tokens * self.input_tokens_1M_price / M
        output_cost = usage["output_tokens"] * self.output_tokens_1M_price / M
        cache_read_cost = usage["cache_read_input_tokens"] * self.cache_read_input_tokens_1M_price / M
        cache_creation_cost = usage["cache_creation_input_tokens"] * self.cache_creation_input_tokens_1M_price / M
        reasoning_cost = usage["reasoning_tokens"] * self.output_tokens_1M_price / M
        total_cost = input_cost + output_cost + cache_read_cost + cache_creation_cost

        return {
            "input": input_cost,
            "output": output_cost,
            "cache_read_input_tokens": cache_read_cost,
            "cache_creation_input_tokens": cache_creation_cost,
            "reasoning_tokens": reasoning_cost,
            "total": total_cost,
        }


def _zero_price() -> Price:
    return {
        "input": 0.0,
        "output": 0.0,
        "cache_read_input_tokens": 0.0,
        "cache_creation_input_tokens": 0.0,
        "reasoning_tokens": 0.0,
        "total": 0.0,
    }


# =============================================================================
# Anthropic
# =============================================================================

OPUS_4_6_PRICING = StaticPricingModel(
    input_tokens_1M_price=5,
    cache_creation_input_tokens_1M_price=6.25,
    cache_read_input_tokens_1M_price=0.5,
    output_tokens_1M_price=25,
)
OPUS_4_5_PRICING = StaticPricingModel(
    input_tokens_1M_price=5,
    cache_creation_input_tokens_1M_price=6.25,
    cache_read_input_tokens_1M_price=0.5,
    output_tokens_1M_price=25,
)
OPUS_4_1_PRICING = StaticPricingModel(
    input_tokens_1M_price=15,
    cache_creation_input_tokens_1M_price=18.75,
    cache_read_input_tokens_1M_price=1.5,
    output_tokens_1M_price=75,
)
OPUS_4_PRICING = StaticPricingModel(
    input_tokens_1M_price=15,
    cache_creation_input_tokens_1M_price=18.75,
    cache_read_input_tokens_1M_price=1.5,
    output_tokens_1M_price=75,
)
SONNET_4_6_PRICING = StaticPricingModel(
    input_tokens_1M_price=3,
    cache_creation_input_tokens_1M_price=3.75,
    cache_read_input_tokens_1M_price=0.3,
    output_tokens_1M_price=15,
)
SONNET_PRICING = StaticPricingModel(
    input_tokens_1M_price=3,
    cache_creation_input_tokens_1M_price=3.75,
    cache_read_input_tokens_1M_price=0.3,
    output_tokens_1M_price=15,
)
HAIKU_4_5_PRICING = StaticPricingModel(
    input_tokens_1M_price=1,
    cache_creation_input_tokens_1M_price=1.25,
    cache_read_input_tokens_1M_price=0.1,
    output_tokens_1M_price=5,
)
HAIKU_3_5_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.8,
    cache_creation_input_tokens_1M_price=1,
    cache_read_input_tokens_1M_price=0.08,
    output_tokens_1M_price=4,
)

# =============================================================================
# OpenAI (standard tier pricing)
# =============================================================================

GPT_5_2_PRICING = StaticPricingModel(
    input_tokens_1M_price=1.75,
    cache_read_input_tokens_1M_price=0.175,
    output_tokens_1M_price=14,
)
GPT_5_1_PRICING = StaticPricingModel(
    input_tokens_1M_price=1.25,
    cache_read_input_tokens_1M_price=0.125,
    output_tokens_1M_price=10,
)
GPT_5_PRICING = StaticPricingModel(
    input_tokens_1M_price=1.25,
    cache_read_input_tokens_1M_price=0.125,
    output_tokens_1M_price=10,
)
GPT_5_MINI_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.25,
    cache_read_input_tokens_1M_price=0.025,
    output_tokens_1M_price=2,
)
GPT_5_NANO_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.05,
    cache_read_input_tokens_1M_price=0.005,
    output_tokens_1M_price=0.4,
)
GPT_5_2_PRO_PRICING = StaticPricingModel(
    input_tokens_1M_price=21,
    output_tokens_1M_price=168,
)
GPT_5_PRO_PRICING = StaticPricingModel(
    input_tokens_1M_price=15,
    output_tokens_1M_price=120,
)
GPT_4_1_PRICING = StaticPricingModel(
    input_tokens_1M_price=2,
    cache_read_input_tokens_1M_price=0.5,
    output_tokens_1M_price=8,
)
GPT_4_1_MINI_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.4,
    cache_read_input_tokens_1M_price=0.1,
    output_tokens_1M_price=1.6,
)
GPT_4_1_NANO_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.1,
    cache_read_input_tokens_1M_price=0.025,
    output_tokens_1M_price=0.4,
)
GPT_4O_PRICING = StaticPricingModel(
    input_tokens_1M_price=2.5,
    cache_read_input_tokens_1M_price=1.25,
    output_tokens_1M_price=10,
)
GPT_4O_MINI_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.15,
    cache_read_input_tokens_1M_price=0.075,
    output_tokens_1M_price=0.6,
)
O3_PRICING = StaticPricingModel(
    input_tokens_1M_price=2,
    cache_read_input_tokens_1M_price=0.5,
    output_tokens_1M_price=8,
)
O3_PRO_PRICING = StaticPricingModel(
    input_tokens_1M_price=20,
    output_tokens_1M_price=80,
)
O4_MINI_PRICING = StaticPricingModel(
    input_tokens_1M_price=1.10,
    cache_read_input_tokens_1M_price=0.275,
    output_tokens_1M_price=4.40,
)
O1_PRICING = StaticPricingModel(
    input_tokens_1M_price=15,
    cache_read_input_tokens_1M_price=7.5,
    output_tokens_1M_price=60,
)

# =============================================================================
# Google Gemini
# =============================================================================

GEMINI_3_1_PRO_PRICING = DynamicPricingModel(
    input_tokens_1M_price={200 * K: 2, 1 * M: 4},
    output_tokens_1M_price={200 * K: 12, 1 * M: 18},
    cache_read_input_tokens_1M_price={200 * K: 0.2, 1 * M: 0.4},
)
GEMINI_3_PRO_PRICING = DynamicPricingModel(
    input_tokens_1M_price={200 * K: 2, 1 * M: 4},
    output_tokens_1M_price={200 * K: 12, 1 * M: 18},
    cache_read_input_tokens_1M_price={200 * K: 0.2, 1 * M: 0.4},
)
GEMINI_3_FLASH_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.5,
    output_tokens_1M_price=3,
    cache_read_input_tokens_1M_price=0.05,
)
GEMINI_2_5_PRO_PRICING = DynamicPricingModel(
    input_tokens_1M_price={200 * K: 1.25, 1 * M: 2.50},
    output_tokens_1M_price={200 * K: 10, 1 * M: 15},
    cache_read_input_tokens_1M_price={200 * K: 0.125, 1 * M: 0.25},
)
GEMINI_2_5_FLASH_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.3,
    output_tokens_1M_price=2.5,
    cache_read_input_tokens_1M_price=0.03,
)
GEMINI_2_5_FLASH_LITE_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.1,
    output_tokens_1M_price=0.4,
    cache_read_input_tokens_1M_price=0.01,
)
GEMINI_2_0_FLASH_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.1,
    output_tokens_1M_price=0.4,
    cache_read_input_tokens_1M_price=0.025,
)
GEMINI_2_0_FLASH_LITE_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.075,
    output_tokens_1M_price=0.3,
)

# =============================================================================
# DeepSeek
# =============================================================================

DEEPSEEK_V3_2_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.28,
    cache_read_input_tokens_1M_price=0.028,
    output_tokens_1M_price=0.42,
)

# =============================================================================
# Kimi (Moonshot)
# =============================================================================

KIMI_K2_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.6,
    cache_read_input_tokens_1M_price=0.15,
    output_tokens_1M_price=2.5,
)
KIMI_K2_TURBO_PRICING = StaticPricingModel(
    input_tokens_1M_price=1.15,
    cache_read_input_tokens_1M_price=0.15,
    output_tokens_1M_price=8,
)
KIMI_K2_5_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.6,
    cache_read_input_tokens_1M_price=0.1,
    output_tokens_1M_price=3.0,
)

# =============================================================================
# Groq
# =============================================================================

GROQ_KIMI_K2_PRICING = StaticPricingModel(
    input_tokens_1M_price=1,
    cache_read_input_tokens_1M_price=0.5,
    output_tokens_1M_price=3,
)

# =============================================================================
# GLM (Zhipu)
# =============================================================================

GLM_4_5_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.6,
    cache_read_input_tokens_1M_price=0.11,
    output_tokens_1M_price=2.2,
)
GLM_4_5V_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.6,
    cache_read_input_tokens_1M_price=0.11,
    output_tokens_1M_price=1.8,
)
GLM_4_6_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.6,
    cache_read_input_tokens_1M_price=0.11,
    output_tokens_1M_price=2.2,
)
GLM_4_6V_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.3,
    cache_read_input_tokens_1M_price=0.05,
    output_tokens_1M_price=0.9,
)

# =============================================================================
# MiniMax
# =============================================================================

MINIMAX_M2_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.3,
    cache_read_input_tokens_1M_price=0.03,
    cache_creation_input_tokens_1M_price=0.375,
    output_tokens_1M_price=1.2,
)

# =============================================================================
# Doubao (ByteDance)
# =============================================================================

DOUBAO_SEED_CODE_PRICING = DynamicPricingModel(
    input_tokens_1M_price={32 * K: 1.2 / 7, 128 * K: 1.4 / 7, 256 * K: 2.8 / 7},
    output_tokens_1M_price={32 * K: 8.0 / 7, 128 * K: 12.0 / 7, 256 * K: 16.0 / 7},
    cache_read_input_tokens_1M_price={32 * K: 0.24 / 7, 128 * K: 0.24 / 7, 256 * K: 0.24 / 7},
)

# =============================================================================
# Qwen (Alibaba)
# =============================================================================

QWEN_3_PRICING = StaticPricingModel(
    input_tokens_1M_price=0.30,
    output_tokens_1M_price=1.20,
)

# =============================================================================
# Model name -> pricing model mapping
#
# Keys should match model identifiers as reported by pydantic-ai's
# ``model.model_name``.  Include common aliases (with/without provider
# prefix, date suffixes, azure/ prefix, etc.) to maximise hit rate.
# =============================================================================

REGISTERED_MODELS: dict[str, StaticPricingModel | DynamicPricingModel] = {
    # -------------------------------------------------------------------------
    # Anthropic
    # -------------------------------------------------------------------------
    # Opus
    "claude-opus-4-6-20260201": OPUS_4_6_PRICING,
    "claude-opus-4-5-20250414": OPUS_4_5_PRICING,
    "claude-opus-4-1-20250501": OPUS_4_1_PRICING,
    "claude-opus-4-20250514": OPUS_4_PRICING,
    # Sonnet
    "claude-sonnet-4-6-20260201": SONNET_4_6_PRICING,
    "claude-sonnet-4-5-20250929": SONNET_PRICING,
    "claude-sonnet-4-20250514": SONNET_PRICING,
    "claude-sonnet-3-7-20250219": SONNET_PRICING,
    # Haiku
    "claude-haiku-4-5-20251001": HAIKU_4_5_PRICING,
    "claude-haiku-3-5-20241022": HAIKU_3_5_PRICING,
    # -------------------------------------------------------------------------
    # OpenAI
    # -------------------------------------------------------------------------
    # GPT-5 family
    "gpt-5.3-codex": GPT_5_2_PRICING,
    "gpt-5.2": GPT_5_2_PRICING,
    "gpt-5.2-codex": GPT_5_2_PRICING,
    "gpt-5.2-pro": GPT_5_2_PRO_PRICING,
    "gpt-5.2-chat-latest": GPT_5_2_PRICING,
    "gpt-5.1": GPT_5_1_PRICING,
    "gpt-5.1-codex": GPT_5_1_PRICING,
    "gpt-5.1-codex-max": GPT_5_1_PRICING,
    "gpt-5.1-codex-mini": GPT_5_MINI_PRICING,
    "gpt-5.1-chat-latest": GPT_5_1_PRICING,
    "gpt-5": GPT_5_PRICING,
    "gpt-5-codex": GPT_5_PRICING,
    "gpt-5-pro": GPT_5_PRO_PRICING,
    "gpt-5-chat-latest": GPT_5_PRICING,
    "gpt-5-mini": GPT_5_MINI_PRICING,
    "gpt-5-nano": GPT_5_NANO_PRICING,
    # GPT-4.1 family
    "gpt-4.1": GPT_4_1_PRICING,
    "gpt-4.1-mini": GPT_4_1_MINI_PRICING,
    "gpt-4.1-nano": GPT_4_1_NANO_PRICING,
    # GPT-4o family
    "gpt-4o": GPT_4O_PRICING,
    "gpt-4o-mini": GPT_4O_MINI_PRICING,
    # o-series reasoning
    "o3": O3_PRICING,
    "o3-pro": O3_PRO_PRICING,
    "o4-mini": O4_MINI_PRICING,
    "o1": O1_PRICING,
    # Azure aliases
    "azure/gpt-5.2": GPT_5_2_PRICING,
    "azure/gpt-5.2-codex": GPT_5_2_PRICING,
    "azure/gpt-5.1": GPT_5_1_PRICING,
    "azure/gpt-5.1-codex": GPT_5_1_PRICING,
    "azure/gpt-5.1-codex-max": GPT_5_1_PRICING,
    "azure/gpt-5.1-codex-mini": GPT_5_MINI_PRICING,
    "azure/gpt-5": GPT_5_PRICING,
    "azure/gpt-5-codex": GPT_5_PRICING,
    "azure/gpt-5-pro": GPT_5_PRO_PRICING,
    "azure/gpt-5-mini": GPT_5_MINI_PRICING,
    # -------------------------------------------------------------------------
    # Google Gemini
    # -------------------------------------------------------------------------
    "gemini-3.1-pro-preview": GEMINI_3_1_PRO_PRICING,
    "gemini-3-pro-preview": GEMINI_3_PRO_PRICING,
    "gemini-3.0-pro": GEMINI_3_PRO_PRICING,
    "gemini-3.0-pro-preview": GEMINI_3_PRO_PRICING,
    "gemini-3-flash-preview": GEMINI_3_FLASH_PRICING,
    "gemini-3-flash": GEMINI_3_FLASH_PRICING,
    "gemini-3.0-flash": GEMINI_3_FLASH_PRICING,
    "gemini-2.5-pro": GEMINI_2_5_PRO_PRICING,
    "gemini-2.5-flash": GEMINI_2_5_FLASH_PRICING,
    "gemini-2.5-flash-lite": GEMINI_2_5_FLASH_LITE_PRICING,
    "gemini-2.0-flash": GEMINI_2_0_FLASH_PRICING,
    "gemini-2.0-flash-lite": GEMINI_2_0_FLASH_LITE_PRICING,
    # -------------------------------------------------------------------------
    # DeepSeek
    # -------------------------------------------------------------------------
    "deepseek-chat": DEEPSEEK_V3_2_PRICING,
    "deepseek-reasoner": DEEPSEEK_V3_2_PRICING,
    # -------------------------------------------------------------------------
    # Kimi (Moonshot)
    # -------------------------------------------------------------------------
    "kimi-k2-thinking": KIMI_K2_PRICING,
    "kimi-k2-thinking-turbo": KIMI_K2_TURBO_PRICING,
    "kimi-k2-turbo-preview": KIMI_K2_TURBO_PRICING,
    "kimi-k2.5": KIMI_K2_5_PRICING,
    "kimi/kimi-k2.5": KIMI_K2_5_PRICING,
    # -------------------------------------------------------------------------
    # Groq
    # -------------------------------------------------------------------------
    "groq/moonshotai/kimi-k2-instruct-0905": GROQ_KIMI_K2_PRICING,
    # -------------------------------------------------------------------------
    # GLM (Zhipu)
    # -------------------------------------------------------------------------
    "glm-4.5": GLM_4_5_PRICING,
    "glm-4.5-cn": GLM_4_5_PRICING,
    "glm-4.5v": GLM_4_5V_PRICING,
    "glm-4.5v-cn": GLM_4_5V_PRICING,
    "glm-4.6": GLM_4_6_PRICING,
    "glm-4.6-cn": GLM_4_6_PRICING,
    "glm-4.6v": GLM_4_6V_PRICING,
    "glm-4.7": GLM_4_6_PRICING,
    # -------------------------------------------------------------------------
    # MiniMax
    # -------------------------------------------------------------------------
    "MiniMax-M2": MINIMAX_M2_PRICING,
    "MiniMax-M2-Stable": MINIMAX_M2_PRICING,
    "MiniMax-M2.1": MINIMAX_M2_PRICING,
    "MiniMax-M2.1-Stable": MINIMAX_M2_PRICING,
    # -------------------------------------------------------------------------
    # Doubao (ByteDance)
    # -------------------------------------------------------------------------
    "doubao-seed-code-preview-251028": DOUBAO_SEED_CODE_PRICING,
    # -------------------------------------------------------------------------
    # Qwen (Alibaba)
    # -------------------------------------------------------------------------
    "qwen3": QWEN_3_PRICING,
}


def calc_price(usage: RequestUsage | None, model_id: str) -> tuple[Usage | None, Price | None]:
    """Calculate pricing for the given usage and model.

    Args:
        usage: Token usage from the model response.
        model_id: The model identifier (as reported by pydantic-ai).

    Returns:
        Tuple of (usage_details, cost_details).  Both are None if usage is None.
        cost_details is None if model_id is not in REGISTERED_MODELS.
    """
    if usage is None:
        return None, None

    usage_dict: Usage = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": usage.cache_read_tokens or usage.details.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": usage.cache_write_tokens or usage.details.get("cache_creation_input_tokens", 0),
        "reasoning_tokens": usage.details.get("reasoning_tokens", 0),
        "total": usage.total_tokens,
    }

    pricing_model = REGISTERED_MODELS.get(model_id)
    if pricing_model is not None:
        return usage_dict, pricing_model.calculate(usage_dict)
    return usage_dict, None
