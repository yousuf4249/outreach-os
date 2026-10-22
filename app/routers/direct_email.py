"""Direct Email / Compose Email router.

Allows sending and scheduling individual emails manually outside of campaigns,
supporting templates, personalization variables, open tracking, and conversation history.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import AsyncSessionLocal, get_db
from app.email_html import normalize_email_html
from app.models import (
    DirectEmail,
    EmailTemplate,
    GmailAccount,
    Inbox,
    Lead,
    Office365Account,
    SmtpAccount,
)
from app.sender import (
    RenderContext,
    SendFailure,
    SendResult,
    get_lead_data,
    render_body,
    send_email,
)
from app.settings_manager import settings
from app.time import utcnow
from app.unibox import (
    unibox_events,
    upsert_sent_message,
    upsert_sent_o365_message,
    upsert_sent_smtp_message,
)

log = logging.getLogger("weblinx.direct_email")

router = APIRouter(prefix="/api/direct-emails", tags=["direct-email"])


class DirectEmailCreate(BaseModel):
    inbox_id: int = Field(..., gt=0)
    to_email: str = Field(..., min_length=3, max_length=320)
    recipient_name: Optional[str] = ""
    lead_id: Optional[int] = None
    template_id: Optional[int] = None
    subject: str = Field(..., max_length=998)
    body: str = Field(...)
    is_html: bool = True
    scheduled_at: Optional[datetime] = None
    enable_follow_up: bool = False
    track_opens: bool = True


class DirectEmailResponse(BaseModel):
    id: int
    inbox_id: int
    inbox_email: Optional[str] = ""
    to_email: str
    recipient_name: Optional[str] = ""
    lead_id: Optional[int] = None
    template_id: Optional[int] = None
    subject: str
    body: str
    is_html: bool
    status: str
    scheduled_at: Optional[str] = None
    sent_at: Optional[str] = None
    error_message: Optional[str] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    opened: bool = False
    opened_at: Optional[str] = None
    open_count: int = 0
    replied: bool = False
    replied_at: Optional[str] = None
    enable_follow_up: bool = False
    created_at: str

    class Config:
        from_attributes = True


def _to_response(de: DirectEmail, inbox_email: str = "") -> dict:
    return {
        "id": de.id,
        "inbox_id": de.inbox_id,
        "inbox_email": inbox_email or (de.inbox.email if de.inbox else ""),
        "to_email": de.to_email,
        "recipient_name": de.recipient_name or "",
        "lead_id": de.lead_id,
        "template_id": de.template_id,
        "subject": de.subject,
        "body": de.body,
        "is_html": bool(de.is_html),
        "status": de.status,
        "scheduled_at": de.scheduled_at.isoformat() if de.scheduled_at else None,
        "sent_at": de.sent_at.isoformat() if de.sent_at else None,
        "error_message": de.error_message or None,
        "message_id": de.message_id or None,
        "thread_id": de.thread_id or None,
        "opened": bool(de.opened),
        "opened_at": de.opened_at.isoformat() if de.opened_at else None,
        "open_count": de.open_count or 0,
        "replied": bool(de.replied),
        "replied_at": de.replied_at.isoformat() if de.replied_at else None,
        "enable_follow_up": bool(de.enable_follow_up),
        "created_at": de.created_at.isoformat() if de.created_at else "",
    }


async def execute_send_direct_email(db: AsyncSession, direct_email: DirectEmail) -> bool:
    """Send one direct email immediately via the inbox's configured provider."""
    inbox_res = await db.execute(select(Inbox).where(Inbox.id == direct_email.inbox_id))
    inbox = inbox_res.scalar_one_or_none()
    if not inbox:
        direct_email.status = "failed"
        direct_email.error_message = f"Inbox with ID {direct_email.inbox_id} not found"
        await db.commit()
        return False

    provider = inbox.provider or "gmail"
    gmail_account = None
    o365_account = None
    smtp_account = None
    o365_client_id = o365_client_secret = o365_tenant_id = ""

    if provider == "smtp":
        smtp_res = await db.execute(select(SmtpAccount).where(SmtpAccount.inbox_id == inbox.id))
        smtp_account = smtp_res.scalar_one_or_none()
        if not smtp_account:
            direct_email.status = "failed"
            direct_email.error_message = "SMTP account credentials are not configured for this inbox"
            await db.commit()
            return False
    elif provider == "office365":
        from app.app_settings import get_office365_oauth_credentials
        from app.routers.office365_oauth import refresh_access_token as _refresh_o365

        o365_res = await db.execute(select(Office365Account).where(Office365Account.inbox_id == inbox.id))
        o365_account = o365_res.scalar_one_or_none()
        if not o365_account:
            direct_email.status = "failed"
            direct_email.error_message = "Office 365 account is not connected for this inbox"
            await db.commit()
            return False
        o365_client_id, o365_client_secret, o365_tenant_id = await get_office365_oauth_credentials(db)
        if not _refresh_o365(o365_account, o365_client_id, o365_client_secret, o365_tenant_id):
            direct_email.status = "failed"
            direct_email.error_message = "Could not refresh Office 365 access token"
            await db.commit()
            return False
    else:
        g_res = await db.execute(select(GmailAccount).where(GmailAccount.inbox_id == inbox.id))
        gmail_account = g_res.scalar_one_or_none()
        if not gmail_account:
            direct_email.status = "failed"
            direct_email.error_message = "Gmail account is not connected for this inbox"
            await db.commit()
            return False

    # Compile lead data for personalization variables
    lead = None
    if direct_email.lead_id:
        l_res = await db.execute(select(Lead).where(Lead.id == direct_email.lead_id))
        lead = l_res.scalar_one_or_none()
    if not lead:
        l_res = await db.execute(select(Lead).where(func.lower(Lead.email) == direct_email.to_email.lower()))
        lead = l_res.scalar_one_or_none()
        if lead and not direct_email.lead_id:
            direct_email.lead_id = lead.id

    lead_data: Dict[str, Any] = {}
    if lead:
        lead_data = get_lead_data(lead)
    else:
        # Fallback dictionary from recipient email and name
        recip_name = (direct_email.recipient_name or "").strip()
        parts = recip_name.split() if recip_name else direct_email.to_email.split("@")[0].split(".")
        first_name = parts[0].capitalize() if parts else ""
        last_name = " ".join(parts[1:]).capitalize() if len(parts) > 1 else ""
        lead_data = {
            "email": direct_email.to_email,
            "name": recip_name or first_name,
            "first_name": first_name,
            "last_name": last_name,
            "company": "",
            "company_name": "",
            "website": "",
            "city": "",
            "industry": "",
        }

    # Render subject and body with variables and spintax
    ctx = RenderContext()
    rendered_subject = render_body(direct_email.subject, lead_data, ctx)
    rendered_body = render_body(direct_email.body, lead_data, ctx)

    if direct_email.is_html:
        rendered_body = normalize_email_html(rendered_body)

        # Append open tracking pixel if open token exists
        if direct_email.open_token:
            tracking_base = (settings.base_url or "http://localhost:8000").rstrip("/")
            pixel_url = f"{tracking_base}/o/{direct_email.open_token}"
            pixel_img = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none;" />'
            lower_body = rendered_body.lower()
            if "</body>" in lower_body:
                idx = lower_body.rfind("</body>")
                rendered_body = rendered_body[:idx] + pixel_img + "\n" + rendered_body[idx:]
            else:
                rendered_body += f"\n{pixel_img}"

    # Perform send
    try:
        send_result = await asyncio.to_thread(
            send_email,
            to_email=direct_email.to_email,
            subject=rendered_subject,
            body=rendered_body,
            from_email=inbox.email,
            from_name=inbox.display_name or "",
            is_html=direct_email.is_html,
            provider=provider,
            gmail_account=gmail_account,
            office365_account=o365_account,
            office365_client_id=o365_client_id,
            office365_client_secret=o365_client_secret,
            office365_tenant_id=o365_tenant_id,
            smtp_account=smtp_account,
        )
    except Exception as exc:
        direct_email.status = "failed"
        direct_email.error_message = str(exc)[:500]
        await db.commit()
        log.warning("Direct send exception to %s: %s", direct_email.to_email, exc)
        return False

    if not send_result or not isinstance(send_result, SendResult):
        err_msg = send_result.message if isinstance(send_result, SendFailure) else "Send failed"
        direct_email.status = "failed"
        direct_email.error_message = err_msg[:500]
        await db.commit()
        log.warning("Direct send rejected to %s: %s", direct_email.to_email, err_msg)
        return False

    # Mark as sent
    now_dt = utcnow()
    direct_email.status = "sent"
    direct_email.sent_at = now_dt
    direct_email.message_id = send_result.message_id
    thread_id = send_result.thread_id or direct_email.thread_id or send_result.message_id
    direct_email.thread_id = thread_id
    direct_email.error_message = None

    # Mirror into conversation history
    try:
        if provider == "smtp":
            await upsert_sent_smtp_message(
                db,
                inbox_id=inbox.id,
                thread_key=thread_id,
                internet_message_id=send_result.message_id,
                subject=rendered_subject,
                to_email=direct_email.to_email,
                from_email=inbox.email,
                body=rendered_body,
                is_html=direct_email.is_html,
            )
        elif provider == "office365":
            await upsert_sent_o365_message(
                db,
                inbox_id=inbox.id,
                conversation_id=thread_id,
                internet_message_id=send_result.message_id,
                subject=rendered_subject,
                to_email=direct_email.to_email,
                from_email=inbox.email,
                body=rendered_body,
                is_html=direct_email.is_html,
            )
        else:
            await upsert_sent_message(
                db,
                inbox_id=inbox.id,
                thread_id=thread_id,
                gmail_message_id=send_result.gmail_message_id,
                rfc_message_id=send_result.message_id,
                subject=rendered_subject,
                to_email=direct_email.to_email,
                from_email=inbox.email,
                body=rendered_body,
                is_html=direct_email.is_html,
            )
    except Exception as exc:
        log.warning("Could not mirror sent direct email to unibox: %s", exc)

    await db.commit()

    # Emit real-time unibox update
    try:
        await unibox_events.publish(
            {
                "type": "unibox.thread.updated",
                "reason": "direct_send",
                "inbox_id": inbox.id,
                "thread_id": thread_id,
                "timestamp": now_dt.isoformat() + "Z",
            }
        )
    except Exception:
        pass

    log.info("Direct email sent successfully: id=%s to=%s message_id=%s", direct_email.id, direct_email.to_email, send_result.message_id)
    return True


@router.post("", response_model=DirectEmailResponse)
async def create_and_send_direct_email(
    data: DirectEmailCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Compose and send immediately or schedule an individual email."""
    # Verify inbox exists
    inbox_res = await db.execute(select(Inbox).where(Inbox.id == data.inbox_id))
    inbox = inbox_res.scalar_one_or_none()
    if not inbox:
        raise HTTPException(status_code=404, detail="Selected inbox not found")

    to_addr = data.to_email.strip().lower()
    if "@" not in to_addr or "." not in to_addr:
        raise HTTPException(status_code=400, detail="Invalid recipient email address")

    # Match or auto-link Lead
    lead_id = data.lead_id
    if not lead_id:
        l_res = await db.execute(select(Lead).where(func.lower(Lead.email) == to_addr))
        matched_lead = l_res.scalar_one_or_none()
        if matched_lead:
            lead_id = matched_lead.id

    sched_dt = data.scheduled_at
    if sched_dt is not None and getattr(sched_dt, 'tzinfo', None) is not None:
        sched_dt = sched_dt.astimezone(timezone.utc).replace(tzinfo=None)
    is_scheduled = sched_dt is not None and sched_dt > utcnow()

    direct_email = DirectEmail(
        inbox_id=data.inbox_id,
        to_email=to_addr,
        recipient_name=(data.recipient_name or "").strip(),
        lead_id=lead_id,
        template_id=data.template_id,
        subject=data.subject.strip(),
        body=data.body,
        is_html=data.is_html,
        status="scheduled" if is_scheduled else "sending",
        scheduled_at=sched_dt,
        enable_follow_up=data.enable_follow_up,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(direct_email)
    await db.flush()

    if is_scheduled:
        await db.commit()
        return _to_response(direct_email, inbox.email)

    # Send immediately
    success = await execute_send_direct_email(db, direct_email)
    if not success and direct_email.status == "failed":
        raise HTTPException(status_code=502, detail=direct_email.error_message or "Email delivery failed")

    return _to_response(direct_email, inbox.email)


@router.get("", response_model=List[DirectEmailResponse])
async def list_direct_emails(
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
    inbox_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List composed / direct emails with optional filters."""
    query = select(DirectEmail, Inbox.email).join(Inbox, DirectEmail.inbox_id == Inbox.id)

    if status:
        query = query.where(DirectEmail.status == status)
    if lead_id:
        query = query.where(DirectEmail.lead_id == lead_id)
    if inbox_id:
        query = query.where(DirectEmail.inbox_id == inbox_id)

    query = query.order_by(DirectEmail.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(query)).all()

    return [_to_response(de, inbox_email) for de, inbox_email in rows]


@router.get("/{id}", response_model=DirectEmailResponse)
async def get_direct_email(
    id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get single direct email details."""
    res = await db.execute(
        select(DirectEmail, Inbox.email).join(Inbox, DirectEmail.inbox_id == Inbox.id).where(DirectEmail.id == id)
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Direct email not found")
    de, inbox_email = row
    return _to_response(de, inbox_email)


@router.delete("/{id}")
async def cancel_or_delete_direct_email(
    id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Delete a draft or cancel a scheduled email."""
    res = await db.execute(select(DirectEmail).where(DirectEmail.id == id))
    de = res.scalar_one_or_none()
    if not de:
        raise HTTPException(status_code=404, detail="Direct email not found")

    await db.delete(de)
    await db.commit()
    return {"ok": True, "deleted_id": id}


@router.post("/{id}/send-now", response_model=DirectEmailResponse)
async def send_scheduled_now(
    id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Immediately deliver a scheduled email."""
    res = await db.execute(
        select(DirectEmail, Inbox.email).join(Inbox, DirectEmail.inbox_id == Inbox.id).where(DirectEmail.id == id)
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Direct email not found")
    de, inbox_email = row

    if de.status == "sent":
        raise HTTPException(status_code=400, detail="Email has already been sent")

    de.status = "sending"
    await db.commit()

    success = await execute_send_direct_email(db, de)
    if not success:
        raise HTTPException(status_code=502, detail=de.error_message or "Failed to deliver email")

    return _to_response(de, inbox_email)


async def run_direct_email_scheduler_job():
    """Background worker job to deliver scheduled direct emails when due."""
    try:
        async with AsyncSessionLocal() as db:
            now_dt = utcnow()
            res = await db.execute(
                select(DirectEmail).where(
                    DirectEmail.status == "scheduled",
                    DirectEmail.scheduled_at <= now_dt,
                )
            )
            due_emails = res.scalars().all()
            for de in due_emails:
                log.info("Sending due scheduled direct email id=%s to=%s", de.id, de.to_email)
                de.status = "sending"
                await db.commit()
                await execute_send_direct_email(db, de)
    except Exception as exc:
        log.exception("Error in direct email scheduler job: %s", exc)
