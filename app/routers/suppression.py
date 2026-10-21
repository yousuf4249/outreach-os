"""Suppression List API routes."""
from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SuppressionList
from app.schemas import SuppressionCreate, SuppressionResponse

log = logging.getLogger("weblinx.suppression")
router = APIRouter(prefix="/api/suppression", tags=["suppression"])


async def is_email_or_domain_suppressed(db: AsyncSession, email: str) -> bool:
    """Return True if email address or its domain is on the global suppression list."""
    if not email or "@" not in email:
        return False
    norm_email = email.strip().lower()
    domain = norm_email.split("@")[-1]

    stmt = select(SuppressionList.id).where(
        SuppressionList.email_or_domain.in_([norm_email, domain, f"@{domain}"])
    ).limit(1)
    res = await db.execute(stmt)
    return res.scalar_one_or_none() is not None


@router.get("", response_model=List[SuppressionResponse])
async def list_suppressions(
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List entries on the global suppression list."""
    stmt = select(SuppressionList).order_by(desc(SuppressionList.created_at))
    if search:
        search_term = f"%{search.strip().lower()}%"
        stmt = stmt.where(SuppressionList.email_or_domain.ilike(search_term))
    stmt = stmt.offset(offset).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("", response_model=SuppressionResponse, status_code=status.HTTP_201_CREATED)
async def add_suppression(
    data: SuppressionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add an email address or entire domain (e.g. competitor.com) to the suppression list."""
    target = data.email_or_domain.strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail="Target email or domain cannot be empty")

    existing = await db.execute(
        select(SuppressionList).where(SuppressionList.email_or_domain == target)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"'{target}' is already on the suppression list")

    entry = SuppressionList(
        email_or_domain=target,
        reason=data.reason.strip() or "manual",
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
async def remove_suppression(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove an entry from the suppression list."""
    res = await db.execute(select(SuppressionList).where(SuppressionList.id == entry_id))
    entry = res.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Suppression entry not found")

    await db.delete(entry)
    await db.flush()
    return {"ok": True, "deleted": entry_id}
