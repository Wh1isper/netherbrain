"""GET /api/model-presets -- model settings discovery endpoint.

Returns the list of available SDK ModelSettings and ModelConfig presets.
This is a pure read endpoint that reflects the SDK's built-in preset
registry; no database access is required.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import APIRouter

from netherbrain.agent_runtime.models.api import (
    ModelConfigPresetInfo,
    ModelPresetsResponse,
    ModelSettingsPresetInfo,
)

router = APIRouter(prefix="/model-presets", tags=["model-presets"])


def _serialize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Serialize a ModelConfig preset dict for JSON output.

    Handles special types like sets (capabilities) and enums.
    """
    result: dict[str, Any] = {}
    for key, value in config.items():
        if isinstance(value, set):
            # Convert set of enums to sorted list of strings.
            result[key] = sorted(v.value if isinstance(v, StrEnum) else str(v) for v in value)
        elif isinstance(value, StrEnum):
            result[key] = value.value
        else:
            result[key] = value
    return result


def _build_response() -> ModelPresetsResponse:
    from ya_agent_sdk.presets import (
        _MODEL_CFG_ALIASES,
        _MODEL_CFG_REGISTRY,
        _PRESET_ALIASES,
        _PRESET_REGISTRY,
    )

    settings_presets = [
        ModelSettingsPresetInfo(name=name, settings=dict(settings))
        for name, settings in sorted(_PRESET_REGISTRY.items())
    ]

    config_presets = [
        ModelConfigPresetInfo(name=name, config=_serialize_config(config))
        for name, config in sorted(_MODEL_CFG_REGISTRY.items())
    ]

    return ModelPresetsResponse(
        model_settings_presets=settings_presets,
        model_settings_aliases=dict(sorted(_PRESET_ALIASES.items())),
        model_config_presets=config_presets,
        model_config_aliases=dict(sorted(_MODEL_CFG_ALIASES.items())),
    )


# Pre-build at import time (registry is static after startup).
_RESPONSE: ModelPresetsResponse = _build_response()


@router.get("", response_model=ModelPresetsResponse)
async def handle_list_model_presets() -> ModelPresetsResponse:
    """Return all available SDK model settings and config presets."""
    return _RESPONSE
