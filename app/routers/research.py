"""Weblinx Outreach OS - Prospect Research API Router

Provides REST endpoints for:
1. Research Dashboard statistics
2. Background Research Job management (Create, List, Details, Pause, Resume, Cancel)
3. Research Results exploration, searching, and filtering
4. Review operations (Approve, Reject, Notes)
5. Promotion to Active Prospects Database (Phase 8 Single & Bulk Add)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Lead,
    ResearchActivityLog,
    ResearchCompany,
    ResearchContact,
    ResearchJob,
    User,
)
from app.services.research_service import ProspectResearchService
from app.time import utcnow

logger = logging.getLogger("weblinx.research.router")

router = APIRouter(prefix="/api/research", tags=["prospect-research"])
research_service = ProspectResearchService()


# ── Pydantic Request & Response Schemas ──────────────────────────────────────────

class ResearchJobCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    country: str = Field("United States", max_length=128)
    state: Optional[str] = Field("Texas", max_length=128)
    city: Optional[str] = Field("Austin", max_length=128)
    industry: Optional[str] = Field("Web Design Agencies", max_length=128)
    keywords: Optional[List[str]] = Field(default_factory=list)
    target_count: int = Field(50, ge=5, le=5000)
    assigned_to: Optional[str] = Field("admin", max_length=128)
    enable_seed_fallback: bool = Field(True, description="Whether to allow curated seed fallback")


class ResearchJobResponse(BaseModel):
    id: int
    name: str
    query_params: Dict[str, Any]
    status: str
    total_discovered: int
    unique_companies: int
    emails_found: int
    verified_valid: int
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class PromoteContactRequest(BaseModel):
    contact_id: int


class BulkPromoteRequest(BaseModel):
    contact_ids: List[int] = Field(..., min_items=1)


class ReviewStatusUpdate(BaseModel):
    review_status: str = Field(..., pattern="^(pending|approved|rejected)$")


class BulkReviewStatusUpdate(BaseModel):
    company_ids: List[int] = Field(..., min_items=1)
    review_status: str = Field(..., pattern="^(pending|approved|rejected)$")


# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_research_stats(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Retrieve high-level summary metrics for the Research Dashboard."""
    # Count jobs
    jobs_cnt = await db.scalar(select(func.count(ResearchJob.id))) or 0
    running_jobs = await db.scalar(
        select(func.count(ResearchJob.id)).where(ResearchJob.status == "running")
    ) or 0

    # Count companies
    companies_cnt = await db.scalar(select(func.count(ResearchCompany.id))) or 0
    approved_cnt = await db.scalar(
        select(func.count(ResearchCompany.id)).where(ResearchCompany.review_status == "approved")
    ) or 0
    imported_cnt = await db.scalar(
        select(func.count(ResearchCompany.id)).where(ResearchCompany.promoted_to_lead_id.is_not(None))
    ) or 0

    # Count contacts & verification breakdown
    contacts_cnt = await db.scalar(select(func.count(ResearchContact.id))) or 0
    emails_cnt = await db.scalar(
        select(func.count(ResearchContact.id)).where(
            ResearchContact.email.is_not(None),
            ResearchContact.email != "",
        )
    ) or 0
    verified_valid_cnt = await db.scalar(
        select(func.count(ResearchContact.id)).where(
            ResearchContact.email_verification_status.in_(["valid", "domain_validated"])
        )
    ) or 0

    return {
        "total_jobs": jobs_cnt,
        "running_jobs": running_jobs,
        "total_companies": companies_cnt,
        "total_contacts": contacts_cnt,
        "emails_discovered": emails_cnt,
        "verified_valid": verified_valid_cnt,
        "approved_companies": approved_cnt,
        "imported_to_crm": imported_cnt,
    }


@router.post("/jobs", response_model=ResearchJobResponse, status_code=201)
async def create_research_job_endpoint(
    req: ResearchJobCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Configure and start an asynchronous prospect discovery and research job."""
    query_params = {
        "country": req.country,
        "state": req.state,
        "city": req.city,
        "industry": req.industry,
        "keywords": req.keywords,
        "target_count": req.target_count,
        "assigned_to": req.assigned_to or user.email,
        "enable_seed_fallback": req.enable_seed_fallback,
    }

    job = await research_service.create_job(
        db=db,
        name=req.name,
        query_params=query_params,
        user=user,
    )

    return ResearchJobResponse(
        id=job.id,
        name=job.name,
        query_params=job.query_params or {},
        status=job.status,
        total_discovered=job.total_discovered,
        unique_companies=job.unique_companies,
        emails_found=job.emails_found,
        verified_valid=job.verified_valid,
        error_message=job.error_message,
        created_at=job.created_at.isoformat() if job.created_at else "",
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.get("/jobs")
async def list_research_jobs(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List all research jobs ordered by recency."""
    res = await db.execute(select(ResearchJob).order_by(ResearchJob.id.desc()))
    jobs = res.scalars().all()
    return [
        {
            "id": j.id,
            "name": j.name,
            "query_params": j.query_params or {},
            "status": j.status,
            "total_discovered": j.total_discovered,
            "unique_companies": j.unique_companies,
            "emails_found": j.emails_found,
            "verified_valid": j.verified_valid,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat() if j.created_at else "",
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]


@router.get("/jobs/{job_id}")
async def get_research_job_details(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get single research job status and activity log."""
    job = await db.get(ResearchJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")

    logs_res = await db.execute(
        select(ResearchActivityLog)
        .where(ResearchActivityLog.job_id == job_id)
        .order_by(ResearchActivityLog.id.desc())
        .limit(50)
    )
    logs = logs_res.scalars().all()

    return {
        "job": {
            "id": job.id,
            "name": job.name,
            "query_params": job.query_params or {},
            "status": job.status,
            "total_discovered": job.total_discovered,
            "unique_companies": job.unique_companies,
            "emails_found": job.emails_found,
            "verified_valid": job.verified_valid,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else "",
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        },
        "activity_logs": [
            {
                "id": l.id,
                "event_type": l.event_type,
                "message": l.message,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
    }


@router.post("/jobs/{job_id}/pause")
async def pause_research_job_endpoint(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Pause an active background research job."""
    ok = await research_service.pause_job(db, job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job could not be paused or is not running")
    return {"ok": True, "message": f"Job #{job_id} paused"}


@router.post("/jobs/{job_id}/resume")
async def resume_research_job_endpoint(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Resume a paused research job."""
    ok = await research_service.resume_job(db, job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job could not be resumed or is not paused")
    return {"ok": True, "message": f"Job #{job_id} resumed"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_research_job_endpoint(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Cancel and terminate a research job."""
    ok = await research_service.cancel_job(db, job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job could not be cancelled")
    return {"ok": True, "message": f"Job #{job_id} cancelled"}


@router.get("/results")
async def list_research_results(
    search: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    city: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
    verification_status: Optional[str] = Query(None),
    has_email: Optional[bool] = Query(None),
    min_icp: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Paginated, searchable, filterable list of staged research results."""
    q = (
        select(ResearchCompany)
        .options(selectinload(ResearchCompany.contacts))
        .order_by(ResearchCompany.icp_score.desc(), ResearchCompany.id.desc())
    )

    if job_id:
        q = q.where(ResearchCompany.job_id == job_id)
    if city:
        q = q.where(func.lower(ResearchCompany.city) == city.strip().lower())
    if industry:
        q = q.where(func.lower(ResearchCompany.category).contains(industry.strip().lower()))
    if review_status:
        q = q.where(ResearchCompany.review_status == review_status.strip().lower())
    if min_icp is not None:
        q = q.where(ResearchCompany.icp_score >= min_icp)
    if search:
        s = f"%{search.strip().lower()}%"
        q = q.where(
            or_(
                func.lower(ResearchCompany.name).like(s),
                func.lower(ResearchCompany.domain).like(s),
                func.lower(ResearchCompany.city).like(s),
                func.lower(ResearchCompany.description).like(s),
            )
        )

    # Execute total count
    count_q = select(func.count(ResearchCompany.id))
    if job_id:
        count_q = count_q.where(ResearchCompany.job_id == job_id)
    if review_status:
        count_q = count_q.where(ResearchCompany.review_status == review_status.strip().lower())
    total_count = await db.scalar(count_q) or 0

    # Paginate
    offset = (page - 1) * limit
    q = q.offset(offset).limit(limit)
    res = await db.execute(q)
    companies = res.scalars().all()

    items = []
    for c in companies:
        # Determine primary contact
        primary_contact = None
        if c.contacts:
            # Prefer contact with email
            contacts_with_email = [ct for ct in c.contacts if ct.email]
            primary_contact = contacts_with_email[0] if contacts_with_email else c.contacts[0]

        # Apply contact-level filters if requested
        if has_email is True and (not primary_contact or not primary_contact.email):
            continue
        if verification_status and primary_contact:
            if primary_contact.email_verification_status != verification_status:
                continue

        items.append({
            "id": c.id,
            "job_id": c.job_id,
            "name": c.name,
            "domain": c.domain,
            "website": c.website,
            "phone": c.phone,
            "address": c.address,
            "city": c.city,
            "state": c.state,
            "country": c.country,
            "category": c.category,
            "description": c.description,
            "socials": c.socials or {},
            "source": c.source,
            "source_id": c.source_id,
            "icp_score": c.icp_score,
            "icp_reasons": c.icp_reasons or [],
            "review_status": c.review_status,
            "assigned_to": c.assigned_to,
            "existing_lead_id": c.existing_lead_id,
            "promoted_to_lead_id": c.promoted_to_lead_id,
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "primary_contact": {
                "id": primary_contact.id,
                "name": primary_contact.name,
                "role": primary_contact.role,
                "email": primary_contact.email,
                "phone": primary_contact.phone,
                "linkedin_url": primary_contact.linkedin_url,
                "email_verification_status": primary_contact.email_verification_status,
                "email_verification_details": primary_contact.email_verification_details or {},
                "confidence_score": primary_contact.confidence_score,
                "field_provenance": primary_contact.field_provenance or {},
            } if primary_contact else None,
            "contacts_count": len(c.contacts),
        })

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "results": items,
    }


@router.get("/results/{company_id}")
async def get_company_details(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Retrieve full company information with all contacts and provenance logs."""
    res = await db.execute(
        select(ResearchCompany)
        .options(selectinload(ResearchCompany.contacts))
        .where(ResearchCompany.id == company_id)
    )
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    logs_res = await db.execute(
        select(ResearchActivityLog)
        .where(ResearchActivityLog.company_id == company_id)
        .order_by(ResearchActivityLog.id.desc())
    )
    logs = logs_res.scalars().all()

    return {
        "company": {
            "id": company.id,
            "job_id": company.job_id,
            "name": company.name,
            "domain": company.domain,
            "website": company.website,
            "phone": company.phone,
            "address": company.address,
            "city": company.city,
            "state": company.state,
            "country": company.country,
            "category": company.category,
            "description": company.description,
            "socials": company.socials or {},
            "source": company.source,
            "source_id": company.source_id,
            "icp_score": company.icp_score,
            "icp_reasons": company.icp_reasons or [],
            "review_status": company.review_status,
            "assigned_to": company.assigned_to,
            "existing_lead_id": company.existing_lead_id,
            "promoted_to_lead_id": company.promoted_to_lead_id,
            "created_at": company.created_at.isoformat() if company.created_at else "",
            "contacts": [
                {
                    "id": ct.id,
                    "name": ct.name,
                    "first_name": ct.first_name,
                    "last_name": ct.last_name,
                    "role": ct.role,
                    "email": ct.email,
                    "phone": ct.phone,
                    "linkedin_url": ct.linkedin_url,
                    "email_verification_status": ct.email_verification_status,
                    "email_verification_details": ct.email_verification_details or {},
                    "confidence_score": ct.confidence_score,
                    "field_provenance": ct.field_provenance or {},
                }
                for ct in company.contacts
            ],
        },
        "activity_logs": [
            {
                "id": l.id,
                "event_type": l.event_type,
                "message": l.message,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
    }


@router.patch("/results/{company_id}/status")
async def update_company_status(
    company_id: int,
    body: ReviewStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a research company as approved or rejected."""
    company = await db.get(ResearchCompany, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    old_status = company.review_status
    company.review_status = body.review_status
    company.updated_at = utcnow()

    log = ResearchActivityLog(
        job_id=company.job_id,
        company_id=company.id,
        event_type="status_change",
        message=f"Review status changed from '{old_status}' to '{body.review_status}' by {user.email}",
        created_at=utcnow(),
    )
    db.add(log)
    await db.commit()

    return {"ok": True, "id": company.id, "review_status": company.review_status}


@router.post("/results/bulk-status")
async def bulk_update_status(
    body: BulkReviewStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk update review status for selected companies."""
    await db.execute(
        update(ResearchCompany)
        .where(ResearchCompany.id.in_(body.company_ids))
        .values(review_status=body.review_status, updated_at=utcnow())
    )
    await db.commit()
    return {"ok": True, "updated_count": len(body.company_ids), "review_status": body.review_status}


@router.post("/results/{contact_id}/promote")
async def promote_contact_endpoint(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Promote a single approved research contact into the active CRM Prospect Database (Phase 8)."""
    res = await research_service.promote_contact_to_lead(db, contact_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to promote contact"))
    return res


@router.post("/results/bulk-promote")
async def bulk_promote_contacts_endpoint(
    body: BulkPromoteRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Bulk promote selected contacts into the active CRM Prospect Database (Phase 8)."""
    summary = await research_service.bulk_promote_contacts(db, body.contact_ids)
    return summary
