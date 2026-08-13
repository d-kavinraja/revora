"""Cohere model discovery adapter.

Fetches available chat models from Cohere's /v2/models endpoint.
Filters out non-chat models (embed, rerank, classify) and returns
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
_NON_CHAT_TERMS = frozenset({
    "embed", "rerank", "classify", "representation",
})

# Cohere model endpoint types that are NOT chat-compatible
_NON_CHAT_ENDPOINTS = frozenset({
    "embed", "rerank", "classify",
})


class CohereDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discover models available via the Cohere API.

    Authentication: Bearer token in Authorization header.
    Endpoint: GET https://api.cohere.com/v2/models

    The response contains a ``models`` list, each with:
      - name: model identifier (e.g. "command-a-03-2025")
      - endpoints: list of supported endpoints (e.g. ["chat", "summarize"])
      - context_length: max context window
      - finetuned: whether it's a fine-tuned model

    Only models with the "chat" endpoint are returned, as Revora's
    code-review pipeline requires chat completion capabilities.
    """

    COHERE_MODELS_URL = "https://api.cohere.com/v2/models"

    @property
    def provider_slug(self) -> str:
        return "cohere"

    async def fetch_models(self, api_key: str) -> list[DiscoveredModel]:
        """Fetch chat-compatible models from the Cohere API."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.COHERE_MODELS_URL,
                headers=headers,
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()

        models: list[dict[str, Any]] = data.get("models", [])
        discovered: list[DiscoveredModel] = []
        now = datetime.datetime.now(datetime.UTC)

        for m in models:
            model_name: str = m.get("name", "")
            if not model_name:
                continue

            # Skip non-chat models by checking endpoints
            endpoints = m.get("endpoints", [])
            if isinstance(endpoints, list) and endpoints:
                if "chat" not in endpoints:
                    logger.debug(f"Skipping non-chat Cohere model: {model_name}")
                    continue

            # Also skip by name patterns (safety net)
            name_lower = model_name.lower()
            if any(term in name_lower for term in _NON_CHAT_TERMS):
                logger.debug(f"Skipping non-chat Cohere model (name filter): {model_name}")
                continue

            # Skip fine-tuned models (user-specific, not universally available)
            if m.get("finetuned", False):
                logger.debug(f"Skipping fine-tuned Cohere model: {model_name}")
                continue

            # Extract context window
            context_window = m.get("context_length")
            if context_window is not None:
                try:
                    context_window = int(context_window)
                except (ValueError, TypeError):
                    context_window = None

            # Build display name
            display_name = model_name

            # Cohere models are available on paid plans; no guaranteed free tier
            description = (
                f"Cohere {model_name} — "
                f"{'context: ' + str(context_window) + ' tokens' if context_window else 'chat model'}."
            )

            discovered.append(
                DiscoveredModel(
                    provider_slug=self.provider_slug,
                    model_id=model_name,
                    display_name=display_name,
                    context_window=context_window,
                    is_free=False,
                    description=description,
                    raw_metadata=m,
                    last_synced_at=now,
                )
            )

        logger.info(
            f"Discovered {len(discovered)} Cohere chat models "
            f"(filtered from {len(models)} total)"
        )
        return discovered
