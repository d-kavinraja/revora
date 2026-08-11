"""Ollama Cloud discovery adapter.

Fetches available models from Ollama Cloud's /api/tags endpoint.
Models on Ollama Cloud are available to Free-tier accounts subject to
account-level GPU-time quotas — there is no per-model free/paid distinction
in the API response.
"""

import datetime
import logging
from typing import Any

import httpx

from app.ai.discovery.base import BaseDiscoveryAdapter
from app.models.discovered_model import DiscoveredModel

logger = logging.getLogger(__name__)

# Non-chat model families to exclude from discovery
_NON_CHAT_TERMS = frozenset({
    "embed", "embedding", "rerank", "clip", "bge-",
    "vision-only", "diffusion", "tts", "whisper",
})


class OllamaCloudDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discover models available on Ollama Cloud via the /api/tags endpoint.

    Authentication: Bearer token in Authorization header.
    Base URL: https://ollama.com/api/tags

    The response contains a ``models`` list, each with:
      - name: model identifier (e.g. "qwen3:32b")
      - size: size in bytes
      - details.parameter_size: human-readable param count (e.g. "32B")
      - details.family: model family
      - details.quantization_level: quantization info

    Free-tier handling:
      Ollama Cloud's free plan provides access to all cloud-catalog models
      with account-level usage limits (GPU-time quotas).  The API does NOT
      expose a per-model ``free`` field, so we mark all discovered models
      as ``is_free=True`` with a description clarifying the account-based
      limitation.
    """

    OLLAMA_CLOUD_API_URL = "https://ollama.com/v1/models"

    @property
    def provider_slug(self) -> str:
        return "ollama_cloud"

    async def fetch_models(self, api_key: str) -> list[DiscoveredModel]:
        """Fetch models from the Ollama Cloud /v1/models endpoint."""
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.OLLAMA_CLOUD_API_URL,
                headers=headers,
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()

        models: list[dict[str, Any]] = data.get("data", [])
        discovered: list[DiscoveredModel] = []
        now = datetime.datetime.now(datetime.UTC)

        for m in models:
            model_name: str = m.get("id", "")
            if not model_name:
                continue

            # Skip non-chat models
            name_lower = model_name.lower()
            if any(term in name_lower for term in _NON_CHAT_TERMS):
                logger.debug(f"Skipping non-chat Ollama Cloud model: {model_name}")
                continue

            # Build a human-readable display name
            display_name = model_name

            description = "Available on Ollama Free Plan (subject to usage limits)."

            discovered.append(
                DiscoveredModel(
                    provider_slug=self.provider_slug,
                    model_id=model_name,
                    display_name=display_name,
                    context_window=None,  # /api/tags does not provide context length
                    is_free=True,  # Available on free plan (account-level limits)
                    description=description,
                    raw_metadata=m,
                    last_synced_at=now,
                )
            )

        logger.info(
            f"Discovered {len(discovered)} Ollama Cloud models "
            f"(filtered from {len(models)} total)"
        )
        return discovered
