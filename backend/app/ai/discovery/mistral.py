"""Mistral model discovery adapter.

Fetches available chat models from Mistral's /v1/models endpoint.
Filters out non-chat models (embeddings, moderation) and returns
only models compatible with Revora's code-review workflow.
"""

import datetime
import logging
from typing import Any

import httpx

from app.ai.discovery.base import BaseDiscoveryAdapter
from app.models.discovered_model import DiscoveredModel

logger = logging.getLogger(__name__)

# Model ID prefixes/terms that indicate non-chat models
_NON_CHAT_TERMS = frozenset(
    {
        "embed",
        "embedding",
        "moderation",
    }
)

# Default context window for Mistral models when the API omits max_context
_DEFAULT_MISTRAL_CONTEXT = 128000


class MistralDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discover models available via the Mistral API.

    Authentication: Bearer token in Authorization header.
    Endpoint: GET https://api.mistral.ai/v1/models

    The response contains a ``data`` list, each with:
      - id: model identifier (e.g. "mistral-small-latest")
      - name: human-readable model name
      - max_context: max context window (may be absent)
      - capabilities: model capabilities object

    Only chat-compatible models are returned; embed and moderation
    models are excluded as Revora's code-review pipeline requires
    chat completion capabilities.
    """

    MISTRAL_MODELS_URL = "https://api.mistral.ai/v1/models"

    @property
    def provider_slug(self) -> str:
        return "mistral"

    async def fetch_models(self, api_key: str) -> list[DiscoveredModel]:
        """Fetch chat-compatible models from the Mistral API."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.MISTRAL_MODELS_URL,
                headers=headers,
                timeout=15.0,
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

            # Skip non-chat models by ID pattern
            if any(term in name_lower for term in _NON_CHAT_TERMS):
                logger.debug(f"Skipping non-chat Mistral model: {model_id}")
                continue

            # Also skip by name pattern (safety net)
            model_name: str = m.get("name", "")
            if model_name:
                if any(term in model_name.lower() for term in _NON_CHAT_TERMS):
                    logger.debug(
                        f"Skipping non-chat Mistral model (name filter): {model_id}"
                    )
                    continue

            # Extract context window; fall back to 128000 for Mistral models
            context_window = m.get("max_context")
            if context_window is not None:
                try:
                    context_window = int(context_window)
                except (ValueError, TypeError):
                    context_window = _DEFAULT_MISTRAL_CONTEXT
            else:
                context_window = _DEFAULT_MISTRAL_CONTEXT

            display_name = model_name or model_id

            description = (
                f"Mistral {display_name} — "
                f"{'context: ' + str(context_window) + ' tokens' if context_window else 'chat model'}."
            )

            discovered.append(
                DiscoveredModel(
                    provider_slug=self.provider_slug,
                    model_id=model_id,
                    display_name=display_name,
                    context_window=context_window,
                    is_free=False,
                    description=description,
                    raw_metadata=m,
                    last_synced_at=now,
                )
            )

        logger.info(
            f"Discovered {len(discovered)} Mistral chat models "
            f"(filtered from {len(models)} total)"
        )
        return discovered
