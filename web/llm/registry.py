"""Model registry and provider lifecycle management."""
from __future__ import annotations
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class ModelEntry:
    model_id: str
    provider: str
    context_window: int
    display_name: str
    supports_thinking: bool = False
    # Self-hosted/on-prem models (vLLM-style deployments) have a much lower
    # concurrency ceiling than cloud-autoscaled ones - confirmed directly:
    # GLM-5.2-FP8 (fingerprint vllm-0.24.0-tp8) returned 403 under 2+
    # concurrent requests, with a ~15s cooldown penalty, while cloud models
    # on the same key at the same instant were unaffected. See
    # docs/internal/OpenCodeIntegrationPlan.md §3. The real fix for
    # OpenCode's coding-agent (pinning its explore subagent to a reliable
    # cloud model regardless of the main model) doesn't depend on this flag -
    # it's applied unconditionally, every project. This flag is purely
    # informational: it lets a UI surface a note for other multi-request
    # patterns this doesn't cover, without blocking model selection.
    low_concurrency: bool = False


# Runtime state — populated by load_profile()
_lock: threading.RLock = threading.RLock()
MODEL_REGISTRY: dict[str, ModelEntry] = {}
_active_model: str = ""
_active_profile: dict = {}
_provider_cache: dict[str, "LLMProvider"] = {}

# Name-pattern heuristic for self-hosted/on-prem models - there's no reliable
# way to ask the gateway "is this model self-hosted" today. Explicitly a
# heuristic, not a guarantee (see ModelEntry.low_concurrency docstring):
# - "GLM-" — confirmed directly (GLM-5.2-FP8, vllm-0.24.0-tp8 fingerprint)
# - "-Distill-" — distilled models are virtually always smaller, locally-
#   servable deployments, not full cloud-hosted APIs
# - "Llama-4-", "Qwen" — commonly self-hosted via vLLM in enterprise gateways
_LOW_CONCURRENCY_PATTERNS = ("glm-", "-distill-", "llama-4-", "qwen")


def _is_low_concurrency_model(model_id: str) -> bool:
    lower = model_id.lower()
    return any(pattern in lower for pattern in _LOW_CONCURRENCY_PATTERNS)


def get_active_model() -> str:
    with _lock:
        return _active_model


def get_active_profile() -> dict:
    with _lock:
        return dict(_active_profile)


def set_active_model(model_id: str) -> None:
    global _active_model
    with _lock:
        if model_id not in MODEL_REGISTRY:
            raise ValueError(f"Unknown model: {model_id}. Available: {', '.join(MODEL_REGISTRY)}")
        _active_model = model_id


def available_models() -> list[str]:
    with _lock:
        return list(MODEL_REGISTRY.keys())


def context_window(model_id: str) -> int:
    with _lock:
        entry = MODEL_REGISTRY.get(model_id)
    return entry.context_window if entry else 200000


def model_supports_thinking(model_id: str) -> bool:
    with _lock:
        entry = MODEL_REGISTRY.get(model_id)
    return entry.supports_thinking if entry else False


def is_low_concurrency_model(model_id: str) -> bool:
    with _lock:
        entry = MODEL_REGISTRY.get(model_id)
    return entry.low_concurrency if entry else False


def load_profile(profile: dict) -> None:
    """Switch the active LLM profile. Rebuilds MODEL_REGISTRY and evicts provider cache."""
    global _active_model, _active_profile
    with _lock:
        _active_profile = dict(profile)
        _provider_cache.clear()

        base_provider = "anthropic" if profile.get("type") == "anthropic" else "openai"
        anthropic_url = profile.get("anthropic_url", "")
        MODEL_REGISTRY.clear()
        for mid in profile.get("models", []):
            # Route Claude models through AnthropicProvider when anthropic_url is set
            if anthropic_url and mid.lower().startswith("claude"):
                prov = "anthropic"
            else:
                prov = base_provider
            MODEL_REGISTRY[mid] = ModelEntry(
                model_id=mid,
                provider=prov,
                context_window=200000,
                display_name=mid,
                supports_thinking=False,
                low_concurrency=_is_low_concurrency_model(mid),
            )

        active = profile.get("active_model", "")
        if active:
            if active not in MODEL_REGISTRY:
                # Auto-register the active model even if not in the models list —
                # new models appear frequently and the gateway decides validity.
                prov = "anthropic" if (anthropic_url and active.lower().startswith("claude")) else base_provider
                MODEL_REGISTRY[active] = ModelEntry(
                    model_id=active,
                    provider=prov,
                    context_window=200000,
                    display_name=active,
                    supports_thinking=False,
                    low_concurrency=_is_low_concurrency_model(active),
                )
            _active_model = active
        elif MODEL_REGISTRY:
            _active_model = next(iter(MODEL_REGISTRY))
        else:
            _active_model = ""


def get_provider(model_id: str | None = None) -> "LLMProvider":
    """Get the LLM provider for a model. Caches one singleton per provider name."""
    with _lock:
        mid = model_id or _active_model
        entry = MODEL_REGISTRY.get(mid)
        provider_name = entry.provider if entry else ("anthropic" if _active_profile.get("type") == "anthropic" else "openai")
        profile_snapshot = dict(_active_profile)

        if provider_name not in _provider_cache:
            if provider_name == "anthropic":
                from .anthropic_provider import AnthropicProvider
                _provider_cache[provider_name] = AnthropicProvider()
            else:
                from .openai_provider import OpenAIProvider
                _provider_cache[provider_name] = OpenAIProvider(profile_snapshot)

        return _provider_cache[provider_name]


def reset_provider(provider_name: str) -> None:
    """Evict cached provider singleton."""
    with _lock:
        _provider_cache.pop(provider_name, None)
