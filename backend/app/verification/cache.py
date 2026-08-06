from typing import Any

from app.cache.redis_cache import redis_cache

VERIFICATION_RESULT_TTL = 86400  # 24 hours
CONFIDENCE_SCORE_TTL = 86400
REPO_METADATA_TTL = 3600  # 1 hour

class VerificationCache:
    
    @staticmethod
    async def get_verification_result(review_id: str) -> dict[str, Any] | None:
        return await redis_cache.get(f"verification:result:{review_id}")
    
    @staticmethod
    async def set_verification_result(review_id: str, result: dict[str, Any]) -> None:
        await redis_cache.set(f"verification:result:{review_id}", result, VERIFICATION_RESULT_TTL)

    @staticmethod
    async def get_confidence_scores(review_id: str) -> list[dict[str, Any]] | None:
        return await redis_cache.get(f"verification:confidence:{review_id}")
    
    @staticmethod
    async def set_confidence_scores(review_id: str, scores: list[dict[str, Any]]) -> None:
        await redis_cache.set(f"verification:confidence:{review_id}", scores, CONFIDENCE_SCORE_TTL)

    @staticmethod
    async def get_repository_metadata(repo_url: str) -> dict[str, Any] | None:
        return await redis_cache.get(f"verification:repo:{repo_url}")
    
    @staticmethod
    async def set_repository_metadata(repo_url: str, metadata: dict[str, Any]) -> None:
        await redis_cache.set(f"verification:repo:{repo_url}", metadata, REPO_METADATA_TTL)

verification_cache = VerificationCache()
