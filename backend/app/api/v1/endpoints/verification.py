from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List, Optional
import uuid
import os
import shutil

from app.schemas.verification import VerificationRequest, VerificationFindingSchema, VerificationMetricsSchema
from app.verification.engine import verification_engine
from app.verification.cache import verification_cache
from app.ai.git_utils import GitService
from app.core.deps import get_current_user
from app.models.user import User

from app.db.session import AsyncSessionLocal
from app.models.verification import VerificationMetricModel, HallucinationReportModel
from sqlalchemy import select, func

router = APIRouter()

@router.post("/review", response_model=Dict[str, Any])
async def verify_review(
    request: VerificationRequest,
    current_user: User = Depends(get_current_user)
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
        repo_path = await GitService.clone_repository(request.repository_url, getattr(request, 'token', ''))
        
        result = await verification_engine.verify(
            ai_response=request.ai_response_text,
            repo_path=repo_path,
            changed_files=request.changed_files,
            context={"review_id": str(request.review_id)}
        )
        
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")
    finally:
        if repo_path and os.path.exists(repo_path):
            try:
                await GitService.cleanup_repository(repo_path)
            except Exception:
                pass

@router.get("/metrics", response_model=Dict[str, Any])
async def get_global_metrics(
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves global verification metrics aggregated across all reviews.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    func.sum(VerificationMetricModel.total_findings).label('total'),
                    func.sum(VerificationMetricModel.verified_findings).label('verified'),
                    func.sum(VerificationMetricModel.rejected_findings).label('rejected'),
                    func.avg(VerificationMetricModel.avg_confidence).label('avg_confidence')
                )
            )
            row = result.first()
            return {
                "total_findings": int(row.total) if row and row.total else 0,
                "verified_count": int(row.verified) if row and row.verified else 0,
                "rejected_count": int(row.rejected) if row and row.rejected else 0,
                "avg_confidence": float(row.avg_confidence) if row and row.avg_confidence else 0.0
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch global metrics: {str(e)}")

@router.get("/hallucinations", response_model=List[Dict[str, Any]])
async def get_global_hallucinations(
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves a global list of recent hallucination reports.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(HallucinationReportModel).order_by(HallucinationReportModel.id.desc()).limit(limit)
            )
            reports = result.scalars().all()
            return [
                {
                    "id": str(r.id),
                    "finding_id": str(r.verification_result_id),
                    "type": r.hallucination_type,
                    "details": r.details
                }
                for r in reports
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch global hallucinations: {str(e)}")


@router.get("/{id}", response_model=Dict[str, Any])
async def get_verification_result(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves the verification result for a given review ID.
    """
    result = await verification_cache.get_verification_result(str(id))
    if not result:
        # DB query would go here if cache miss
        raise HTTPException(status_code=404, detail="Verification result not found")
    return result

@router.get("/{id}/metrics", response_model=Dict[str, Any])
async def get_verification_metrics(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves the verification metrics for a given review ID.
    """
    result = await verification_cache.get_verification_result(str(id))
    if not result:
        raise HTTPException(status_code=404, detail="Metrics not found")
        
    return {
        "total_findings": result.get("total_findings", 0),
        "verified_count": result.get("verified_count", 0),
        "rejected_count": result.get("rejected_count", 0),
        "avg_confidence": result.get("avg_confidence", 0.0)
    }

@router.get("/{id}/confidence", response_model=Dict[str, Any])
async def get_verification_confidence(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves confidence details.
    """
    result = await verification_cache.get_verification_result(str(id))
    if not result:
        raise HTTPException(status_code=404, detail="Confidence data not found")
    return {"avg_confidence": result.get("avg_confidence", 0.0)}

@router.get("/{id}/hallucinations", response_model=List[Dict[str, Any]])
async def get_verification_hallucinations(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves hallucination reports.
    """
    result = await verification_cache.get_verification_result(str(id))
    if not result:
        raise HTTPException(status_code=404, detail="Hallucination data not found")
    return result.get("hallucination_reports", [])
