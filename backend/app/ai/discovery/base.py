from abc import ABC, abstractmethod

from app.models.discovered_model import DiscoveredModel


class BaseDiscoveryAdapter(ABC):
    @property
    @abstractmethod
    def provider_slug(self) -> str:
        """The slug of the provider this adapter belongs to (e.g. openrouter, nvidia)."""
        pass

    @abstractmethod
    async def fetch_models(self, api_key: str) -> list[DiscoveredModel]:
        """
        Fetches the models from the provider API using the supplied key.
        Returns a list of DiscoveredModel objects, without persisting them to DB yet.
        """
        pass
