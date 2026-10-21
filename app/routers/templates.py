"""Email Templates API routes."""
from __future__ import annotations

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EmailTemplate, Inbox
from app.schemas import (
    TemplateCreate,
    TemplateUpdate,
    TemplateResponse,
)
from app.sender import render_body, RenderContext, send_email, SendResult
from app.time import utcnow

log = logging.getLogger("weblinx.templates")
router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplatePreviewRequest(BaseModel):
    subject: str = ""
    body: str = ""
    sample_data: dict = Field(default_factory=dict)


class TemplateTestSendRequest(BaseModel):
    inbox_id: int
    to_email: str
    subject: str = ""
    body: str = ""
    is_html: bool = False
    preview_text: Optional[str] = None


@router.get("", response_model=List[TemplateResponse])
async def list_templates(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all saved reusable templates."""
    stmt = select(EmailTemplate).order_by(desc(EmailTemplate.updated_at))
    if category:
        stmt = stmt.where(EmailTemplate.category == category)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new reusable email template."""
    tmpl = EmailTemplate(
        name=data.name.strip(),
        subject=data.subject.strip(),
        body=data.body,
        is_html=data.is_html,
        preview_text=data.preview_text,
        category=data.category.strip() or "Cold Outreach",
    )
    db.add(tmpl)
    await db.flush()
    await db.refresh(tmpl)
    return tmpl


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get single email template by ID."""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing email template."""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if data.name is not None:
        tmpl.name = data.name.strip()
    if data.subject is not None:
        tmpl.subject = data.subject.strip()
    if data.body is not None:
        tmpl.body = data.body
    if data.is_html is not None:
        tmpl.is_html = data.is_html
    if data.preview_text is not None:
        tmpl.preview_text = data.preview_text
    if data.category is not None:
        tmpl.category = data.category.strip()
    tmpl.updated_at = utcnow()

    await db.flush()
    await db.refresh(tmpl)
    return tmpl


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an email template."""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tmpl)
    await db.flush()
    return {"ok": True, "deleted": template_id}


@router.post("/{template_id}/duplicate", response_model=TemplateResponse)
async def duplicate_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Duplicate an existing template."""
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.id == template_id))
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    new_tmpl = EmailTemplate(
        name=f"{tmpl.name} (Copy)",
        subject=tmpl.subject,
        body=tmpl.body,
        is_html=tmpl.is_html,
        preview_text=tmpl.preview_text,
        category=tmpl.category,
    )
    db.add(new_tmpl)
    await db.flush()
    await db.refresh(new_tmpl)
    return new_tmpl


@router.post("/preview")
async def preview_template(data: TemplatePreviewRequest):
    """Render live preview of subject and body with provided or default lead variables."""
    default_sample = {
        "name": "Sarah Connor",
        "first_name": "Sarah",
        "last_name": "Connor",
        "email": "sarah@cyberdyne.com",
        "company": "Cyberdyne Systems",
        "company_name": "Cyberdyne Systems",
        "business_name": "Cyberdyne Systems",
        "website": "https://cyberdyne.com",
        "industry": "Robotics & AI",
        "city": "Los Angeles",
        "country": "United States",
        "phone": "+1 (555) 019-2834",
        "lead_source": "Outbound",
        "notes": "Interested in AI automation",
    }
    sample = {**default_sample, **data.sample_data}
    ctx = RenderContext()
    rendered_subject = render_body(data.subject, sample, ctx)
    rendered_body = render_body(data.body, sample, ctx)

    return {
        "rendered_subject": rendered_subject,
        "rendered_body": rendered_body,
        "sample_data": sample,
    }


@router.post("/test-send")
async def send_test_email(
    data: TemplateTestSendRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a real test email using a connected inbox to verify template rendering and delivery."""
    result = await db.execute(select(Inbox).where(Inbox.id == data.inbox_id))
    inbox = result.scalar_one_or_none()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    sample = {
        "name": "Test Recipient",
        "first_name": "Test",
        "last_name": "Recipient",
        "email": data.to_email,
        "company": "Weblinx Solution Test",
        "company_name": "Weblinx Solution Test",
        "business_name": "Weblinx Solution Test",
        "website": "https://weblinxsolution.com",
        "industry": "Sales Automation",
        "city": "New York",
        "country": "USA",
    }
    ctx = RenderContext()
    subject = render_body(data.subject, sample, ctx)
    body = render_body(data.body, sample, ctx)

    send_res = await send_email(
        db=db,
        inbox=inbox,
        to_email=data.to_email,
        subject=f"[TEST] {subject}",
        body=body,
        is_html=data.is_html,
        preview_text=data.preview_text,
    )

    if not send_res:
        error_msg = getattr(send_res, "message", "Sending failed")
        raise HTTPException(status_code=502, detail=f"Failed to send test email: {error_msg}")

    return {
        "ok": True,
        "message": f"Test email sent successfully to {data.to_email}",
        "message_id": getattr(send_res, "message_id", None),
    }
