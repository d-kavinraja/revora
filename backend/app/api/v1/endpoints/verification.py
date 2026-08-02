import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.ai.git_utils import GitService
from app.api.v1.endpoints.reviews import _ensure_review_ownership
from app.core.deps import get_current_user
from app.db.session import AsyncSessionLocal
from app.models.review import Review
from app.models.user import User
from app.models.verification import HallucinationReportModel, VerificationMetricModel
from app.schemas.verification import VerificationRequest
from app.verification.cache import verification_cache
from app.verification.engine import verification_engine

router = APIRouter()


@router.post("/review", response_model=dict[str, Any])
async def verify_review(
    request: VerificationRequest, current_user: User = Depends(get_current_user)
):
    """
    Verifies an AI-generated review against the repository.
    """
    repo_path = None
    try:
        # Clone the repository dynamically using GitService instead of hardcoding
        # The request schema should ideally have clone_url and token, but we assume
        # repository_url works for public repos if token is not provided.
        # Fallback to empty if not provided.
        # SSRF Protection: strictly allow only github.com HTTPS URLs
        if not request.repository_url or not request.repository_url.startswith(
            "https://github.com/"
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid repository URL. Only https://github.com/ URLs are allowed.",
            )

        try:
            repo_path = await GitService.clone_repository(
                request.repository_url, getattr(request, "token", "")
            )
        except Exception:
            # Do not reflect exception details which could expose internal network probing info
            raise HTTPException(
                status_code=400,
                detail="Failed to clone repository. Please check the URL and your access token.",
            )

        result = await verification_engine.verify(
            ai_response=request.ai_response_text,
            repo_path=repo_path,
            changed_files=request.changed_files,
            context={"review_id": str(request.review_id)},
        )

        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e!s}")
    finally:
        if repo_path and os.path.exists(repo_path):
            try:
                await GitService.cleanup_repository(repo_path)
            except Exception:
                pass


@router.get("/metrics", response_model=dict[str, Any])
async def get_global_metrics(current_user: User = Depends(get_current_user)):
    """
    Retrieves global verification metrics aggregated across all reviews.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    func.sum(VerificationMetricModel.total_findings).label("total"),
                    func.sum(VerificationMetricModel.verified_findings).label(
                        "verified"
                    ),
                    func.sum(VerificationMetricModel.rejected_findings).label(
                        "rejected"
                    ),
                    func.avg(VerificationMetricModel.avg_confidence).label(
                        "avg_confidence"
                    ),
                )
            )
            row = result.first()
            return {
                "total_findings": int(row.total) if row and row.total else 0,
                "verified_count": int(row.verified) if row and row.verified else 0,
                "rejected_count": int(row.rejected) if row and row.rejected else 0,
                "avg_confidence": (
                    float(row.avg_confidence) if row and row.avg_confidence else 0.0
                ),
            }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch global metrics: {e!s}"
        )


@router.get("/hallucinations", response_model=list[dict[str, Any]])
async def get_global_hallucinations(
    limit: int = 50, current_user: User = Depends(get_current_user)
):
    """
    Retrieves a global list of recent hallucination reports.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(HallucinationReportModel)
                .order_by(HallucinationReportModel.id.desc())
                .limit(limit)
            )
            reports = result.scalars().all()
            return [
                {
                    "id": str(r.id),
                    "finding_id": str(r.verification_result_id),
                    "type": r.hallucination_type,
                    "details": r.details,
                }
                for r in reports
            ]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch global hallucinations: {e!s}"
        )


@router.get("/{id}", response_model=dict[str, Any])
async def get_verification_result(
    id: uuid.UUID, current_user: User = Depends(get_current_user)
):
    """
    Retrieves the verification result for a given review ID.
    """
    async with AsyncSessionLocal() as db:
        review_result = await db.execute(select(Review).where(Review.id == id))
        review = review_result.scalars().first()
        if not review:
            raise HTTPException(status_code=404, detail="Verification result not found")
        await _ensure_review_ownership(db, review, current_user.id)

    result = await verification_cache.get_verification_result(str(id))
    if not result:
        # DB query would go here if cache miss
        raise HTTPException(status_code=404, detail="Verification result not found")
    return result


@router.get("/{id}/metrics", response_model=dict[str, Any])
async def get_verification_metrics(
    id: uuid.UUID, current_user: User = Depends(get_current_user)
):
    """
    Retrieves the verification metrics for a given review ID.
    """
    async with AsyncSessionLocal() as db:
        review_result = await db.execute(select(Review).where(Review.id == id))
        review = review_result.scalars().first()
        if not review:
            raise HTTPException(status_code=404, detail="Metrics not found")
        await _ensure_review_ownership(db, review, current_user.id)

    result = await verification_cache.get_verification_result(str(id))
    if not result:
        raise HTTPException(status_code=404, detail="Metrics not found")

    return {
        "total_findings": result.get("total_findings", 0),
        "verified_count": result.get("verified_count", 0),
        "rejected_count": result.get("rejected_count", 0),
        "avg_confidence": result.get("avg_confidence", 0.0),
    }


@router.get("/{id}/confidence", response_model=dict[str, Any])
async def get_verification_confidence(
    id: uuid.UUID, current_user: User = Depends(get_current_user)
):
    """
    Retrieves confidence details.
    """
    async with AsyncSessionLocal() as db:
        review_result = await db.execute(select(Review).where(Review.id == id))
        review = review_result.scalars().first()
        if not review:
            raise HTTPException(status_code=404, detail="Confidence data not found")
        await _ensure_review_ownership(db, review, current_user.id)

    result = await verification_cache.get_verification_result(str(id))
    if not result:
        raise HTTPException(status_code=404, detail="Confidence data not found")
    return {"avg_confidence": result.get("avg_confidence", 0.0)}


@router.get("/{id}/hallucinations", response_model=list[dict[str, Any]])
async def get_verification_hallucinations(
    id: uuid.UUID, current_user: User = Depends(get_current_user)
):
    """
    Retrieves hallucination reports.
    """
    async with AsyncSessionLocal() as db:
        review_result = await db.execute(select(Review).where(Review.id == id))
        review = review_result.scalars().first()
        if not review:
            raise HTTPException(status_code=404, detail="Hallucination data not found")
        await _ensure_review_ownership(db, review, current_user.id)

    result = await verification_cache.get_verification_result(str(id))
    if not result:
        raise HTTPException(status_code=404, detail="Hallucination data not found")
    return result.get("hallucination_reports", [])
