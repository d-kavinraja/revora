import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class CanonicalModel(BaseModel):
    """
    Unified Source of Truth for an LLM Model across the entire platform.
    """
    provider: str
    provider_model_name: str
    canonical_model_name: str
    litellm_model_name: str
    model_name: str  # alias for canonical_model_name for backward compatibility
    
    accessible: bool = True
    deprecated: bool = False
    preview: bool = False
    experimental: bool = False
    enterprise_only: bool = False
    region_supported: bool = True
    
    context_window: Optional[int] = None
    input_cost: float = 0.0
    output_cost: float = 0.0
    
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    
    status: str = "available"
    validation_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class CanonicalModelRegistry:
    """
    In-memory singleton registry to store and resolve models.
    Provides standard O(1) lookups by provider/canonical_name.
    """
    def __init__(self):
        # Nested dictionary mapping: dict[provider][canonical_model_name] -> CanonicalModel
        self._registry: Dict[str, Dict[str, CanonicalModel]] = {}

    def register(self, model: CanonicalModel) -> None:
        """Register a normalized model into the registry."""
        provider = model.provider.lower()
        if provider not in self._registry:
            self._registry[provider] = {}
        
        self._registry[provider][model.canonical_model_name] = model

    def resolve(self, provider: str, model_name: str) -> Optional[CanonicalModel]:
        """
        Resolve a model name to its CanonicalModel.
        Tries canonical name first, then litellm name, then provider name.
        """
        provider = provider.lower()
        if provider not in self._registry:
            return None
        
        provider_models = self._registry[provider]
        
        # 1. Exact match on canonical name
        if model_name in provider_models:
            return provider_models[model_name]
            
        # 2. Match by litellm_model_name or provider_model_name
        for canonical_name, m in provider_models.items():
            if m.litellm_model_name == model_name or m.provider_model_name == model_name:
                return m
                
        # 3. Handle prefix stripping explicitly (e.g. if the user assigned gemini/gemini-2.5-flash)
        stripped_name = model_name
        if stripped_name.startswith(f"{provider}/"):
            stripped_name = stripped_name[len(f"{provider}/"):]
            if stripped_name in provider_models:
                return provider_models[stripped_name]
                
        return None
        
    def get_all_for_provider(self, provider: str) -> List[CanonicalModel]:
        """Return all models currently registered for a given provider."""
        provider = provider.lower()
        if provider not in self._registry:
            return []
        return list(self._registry[provider].values())

    def clear(self):
        """Clear the registry."""
        self._registry.clear()

    def discover_models(self):
        """Automatically discover and register models from LiteLLM's model cost dictionary."""
        import litellm
        
        if not hasattr(litellm, "model_cost"):
            logger.warning("litellm.model_cost not found. Cannot auto-discover models.")
            return
            
        logger.info(f"Discovering models from litellm (found {len(litellm.model_cost)} entries)...")
        discovered_count = 0
        
        for model_key, metadata in litellm.model_cost.items():
            if not isinstance(metadata, dict):
                continue
                
            provider = metadata.get("litellm_provider", "")
            if not provider:
                if "/" in model_key:
                    provider = model_key.split("/")[0]
                else:
                    if model_key.startswith("gemini"):
                        provider = "gemini"
                    elif model_key.startswith("gpt"):
                        provider = "openai"
                    elif model_key.startswith("claude"):
                        provider = "anthropic"
                    else:
                        continue
                        
            provider = provider.lower()
            
            canonical_name = model_key
            if canonical_name.startswith(f"{provider}/"):
                canonical_name = canonical_name[len(f"{provider}/"):]
                
            input_cost = metadata.get("input_cost_per_token", 0.0)
            output_cost = metadata.get("output_cost_per_token", 0.0)
            context_window = metadata.get("max_tokens", None)
            if context_window is not None:
                try:
                    context_window = int(context_window)
                except (ValueError, TypeError):
                    context_window = None
            
            c_model = CanonicalModel(
                provider=provider,
                provider_model_name=canonical_name,
                canonical_model_name=canonical_name,
                litellm_model_name=model_key,
                model_name=canonical_name,
                context_window=context_window,
                input_cost=input_cost * 1000,
                output_cost=output_cost * 1000,
                status="available",
                accessible=True
            )
            self.register(c_model)
            discovered_count += 1
            
        logger.info(f"Successfully auto-discovered and registered {discovered_count} models.")

# Global Singleton
canonical_registry = CanonicalModelRegistry()
