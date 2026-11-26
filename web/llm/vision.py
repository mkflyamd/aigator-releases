"""Picking a vision-capable model when the active one cannot receive tool images."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
# Cheapest first: a short screenshot description does not need a flagship model.
_COST_ORDER = ("haiku", "mini", "flash", "nano", "sonnet")


def is_vision_model(model_id: str) -> bool:
    from llm import registry

    return registry.model_supports_vision(model_id)


def active_receives_tool_images() -> bool:
    """False when the active model's provider drops tool-result images (e.g. OpenAI-compatible)."""
    from llm import registry

    model = registry.get_active_model()
    if not model or model not in registry.MODEL_REGISTRY:
        return True
    return bool(registry.get_provider(model).receives_tool_images)


def pick_vision_model() -> str | None:
    """Cheapest vision-capable model in the active profile, or None."""
    from llm import registry

    candidates = [m for m in registry.available_models() if is_vision_model(m)]
    if not candidates:
        return None

    def rank(m: str) -> tuple[int, int]:
        lower = m.lower()
        tier = next((i for i, k in enumerate(_COST_ORDER) if k in lower), len(_COST_ORDER))
        return (tier, 1 if "opus" in lower else 0)

    return sorted(candidates, key=rank)[0]


def describe_image(image: bytes, prompt: str) -> tuple[str, str] | None:
    """Describe a PNG with a vision-capable model. Returns (description, model_id) or None."""
    from llm import registry

    model = pick_vision_model()
    if not model:
        return None
    provider = registry.get_provider(model)
    try:
        text = provider.describe_image(image, prompt, model)
    except Exception as e:
        # Class and HTTP status only: the message can carry request details.
        logger.warning(
            "vision: describe_image failed model=%s error=%s status=%s",
            model, type(e).__name__, getattr(e, "status_code", None),
        )
        return None
    text = (text or "").strip()
    return (text, model) if text else None
