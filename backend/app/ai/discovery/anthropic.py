"""Anthropic (Claude) model discovery adapter.

Fetches available models from Anthropic's /v1/models endpoint.
"""

import datetime
import logging
from typing import Any

import httpx

from app.ai.discovery.base import BaseDiscoveryAdapter
from app.models.discovered_model import DiscoveredModel

logger = logging.getLogger(__name__)

_NON_CHAT_TERMS = frozenset(
    {
        "embedding",
        "embed",
    }
)


class AnthropicDiscoveryAdapter(BaseDiscoveryAdapter):
    ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

    @property
    def provider_slug(self) -> str:
        return "anthropic"

    async def fetch_models(self, api_key: str) -> list[DiscoveredModel]:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.ANTHROPIC_MODELS_URL, headers=headers, timeout=15.0
            )
            response.raise_for_status()
            data = response.json()

        models: list[dict[str, Any]] = data.get("data", [])
        discovered: list[DiscoveredModel] = []
        now = datetime.datetime.now(datetime.UTC)

        for m in models:
            model_id: str = m.get("id", "")
            if not model_id:
                continue

            name_lower = model_id.lower()
            if any(term in name_lower for term in _NON_CHAT_TERMS):
                logger.debug(f"Skipping non-chat Anthropic model: {model_id}")
                continue

            context_window = m.get("context_window") or m.get("max_context")
            if context_window is not None:
                try:
                    context_window = int(context_window)
                except (ValueError, TypeError):
                    context_window = None

            display_name = m.get("display_name") or model_id

            discovered.append(
                DiscoveredModel(
                    provider_slug=self.provider_slug,
                    model_id=model_id,
                    display_name=display_name,
                    context_window=context_window,
                    is_free=False,
                    description=f"Anthropic {display_name} chat model.",
                    raw_metadata=m,
                    last_synced_at=now,
                )
            )

        logger.info(
            f"Discovered {len(discovered)} Anthropic chat models "
            f"(filtered from {len(models)} total)"
        )
        return discovered