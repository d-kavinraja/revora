import datetime
from typing import Any

import httpx

from app.ai.discovery.base import BaseDiscoveryAdapter
from app.models.discovered_model import DiscoveredModel


class OpenRouterDiscoveryAdapter(BaseDiscoveryAdapter):
    @property
    def provider_slug(self) -> str:
        return "openrouter"

    async def fetch_models(self, api_key: str) -> list[DiscoveredModel]:
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models", headers=headers, timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            
        models = data.get("data", [])
        discovered = []
        now = datetime.datetime.now(datetime.UTC)
        
        for m in models:
            model_id = m.get("id", "")
            
            # Pricing logic: determine if model is strictly free
            pricing = m.get("pricing", {})
            prompt_cost = pricing.get("prompt", "1")
            completion_cost = pricing.get("completion", "1")
            
            # Either explicit zero cost OR ends with :free
            is_free = (prompt_cost == "0" and completion_cost == "0") or model_id.endswith(":free")
            
            # The STRICT requirement is to ONLY return FREE models
            if not is_free:
                continue
                
            display_name = m.get("name", model_id)
            context_length = m.get("context_length")
            description = m.get("description")
            
            discovered.append(
                DiscoveredModel(
                    provider_slug=self.provider_slug,
                    model_id=model_id,
                    display_name=display_name,
                    context_window=context_length,
                    is_free=True,
                    description=description,
                    raw_metadata=m,
                    last_synced_at=now,
                )
            )
            
        return discovered
