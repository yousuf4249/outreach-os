"""Shared email tracking side effects (open, click, unsubscribe).

Used by the public tracking router and the Beacon ingest endpoint.
"""
from __future__ import annotations

# // BEACON SYNC: This file handles tracking logic that Beacon mirrors.
# // Any changes to tracking behavior, event types, metadata collected, or URL structure
# // must also be reflected in the Beacon service (/beacon or the separate Beacon repo).
# // If you are an AI agent, add a TODO at the end of your response listing what needs to be updated in Beacon.

import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import time as time_provider
from app.models import (
    CampaignLead,
    EmailClick,
    EmailLog,
    EmailOpen,
    KnownIP,
    Lead,
    LeadUnsubscribeToken,
    QueueSlot,
    TrackedLink,
)
from app.webhooks import fire_webhook_event

if TYPE_CHECKING:
    pass

log = logging.getLogger("quickly.tracking_events")

_UNSUBSCRIBE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Unsubscribed</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; background: #f9fafb; }
    .card { background: #fff; border-radius: 12px; padding: 48px 40px;
            box-shadow: 0 4px 24px rgba(0,0,0,.08); text-align: center; max-width: 420px; }
    .icon { font-size: 48px; margin-bottom: 16px; }
    h1 { margin: 0 0 8px; font-size: 24px; color: #111; }
    p  { color: #555; margin: 0; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✓</div>
    <h1>You've been unsubscribed</h1>
    <p>You will no longer receive emails from us.<br>
       If this was a mistake please contact the sender directly.</p>
  </div>
</body>
</html>"""

ALREADY_UNSUBSCRIBED_HTML = _UNSUBSCRIBE_HTML.replace(
    "You've been unsubscribed",
    "Already unsubscribed",
).replace(
    "You will no longer receive emails from us.<br>If this was a mistake please contact the sender directly.",
    "You are already unsubscribed and will not receive any more emails from us.",
)

INVALID_UNSUBSCRIBE_HTML = "<p>Invalid or expired unsubscribe link.</p>"


async def is_known_ip(db: AsyncSession, ip: str | None) -> bool:
    if not ip:
        return False
    now = time_provider.utcnow()
    result = await db.execute(
        select(KnownIP).where(
            KnownIP.ip_address == ip,
            (KnownIP.permanent == True) | (KnownIP.expires_at > now),  # noqa: E712
        )
    )
    return result.scalar_one_or_none() is not None


async def resolve_email_log_for_open(db: AsyncSession, token: str) -> EmailLog | None:
    result = await db.execute(select(EmailLog).where(EmailLog.open_token == token))
    email_log = result.scalar_one_or_none()
    if email_log is None:
        try:
            log_id = int(token)
            result = await db.execute(select(EmailLog).where(EmailLog.id == log_id))
            email_log = result.scalar_one_or_none()
        except (ValueError, TypeError):
            pass
    return email_log


async def record_email_open(db: AsyncSession, token: str, ip: str | None) -> bool:
    """Persist open event if applicable. Returns True if an open was recorded."""
    from app.unibox import unibox_events
    now = time_provider.utcnow()

    email_log = await resolve_email_log_for_open(db, token)
    if not email_log:
        from app.models import DirectEmail
        de_res = await db.execute(select(DirectEmail).where(DirectEmail.open_token == token))
        direct_email = de_res.scalar_one_or_none()
        if not direct_email:
            return False
        if await is_known_ip(db, ip):
            log.debug("open: skipping known IP %s for direct_email_id=%s", ip, direct_email.id)
            return False
        direct_email.opened = True
        if not direct_email.opened_at:
            direct_email.opened_at = now
        direct_email.last_opened_at = now
        direct_email.open_count = (direct_email.open_count or 0) + 1
        
        # Keep open history entries
        history = list(direct_email.open_history or [])
        history.append({
            "opened_at": now.isoformat() + "Z",
            "ip_address": ip or None,
        })
        direct_email.open_history = history
        await db.commit()
        log.info("direct_email open recorded: id=%s to=%s (count=%s)", direct_email.id, direct_email.to_email, direct_email.open_count)

        # Notify via SSE
        try:
            await unibox_events.publish({
                "type": "unibox.tracking.event",
                "event": "open",
                "channel": "direct_email",
                "direct_email_id": direct_email.id,
                "thread_id": direct_email.thread_id,
                "inbox_id": direct_email.inbox_id,
                "lead_id": direct_email.lead_id,
                "open_count": direct_email.open_count,
                "timestamp": now.isoformat() + "Z",
            })
            if direct_email.thread_id and direct_email.inbox_id:
                await unibox_events.publish({
                    "type": "unibox.thread.updated",
                    "reason": "tracking_open",
                    "inbox_id": direct_email.inbox_id,
                    "thread_id": direct_email.thread_id,
                    "timestamp": now.isoformat() + "Z",
                })
        except Exception as sse_err:
            log.debug("SSE tracking event broadcast exception: %s", sse_err)
        return True

    if await is_known_ip(db, ip):
        log.debug("open: skipping known IP %s for log_id=%s", ip, email_log.id)
        return False
    if not email_log.opened:
        email_log.opened = True
    db.add(
        EmailOpen(
            email_log_id=email_log.id,
            ip_address=ip,
            opened_at=now,
        )
    )
    await db.commit()

    # Query total opens count for this email_log
    from sqlalchemy import func
    cnt_res = await db.execute(select(func.count(EmailOpen.id)).where(EmailOpen.email_log_id == email_log.id))
    tot_opens = cnt_res.scalar() or 1

    # Notify via SSE
    try:
        await unibox_events.publish({
            "type": "unibox.tracking.event",
            "event": "open",
            "channel": "campaign_email",
            "email_log_id": email_log.id,
            "thread_id": email_log.thread_id,
            "inbox_id": email_log.inbox_id,
            "lead_id": email_log.lead_id,
            "open_count": tot_opens,
            "timestamp": now.isoformat() + "Z",
        })
        if email_log.thread_id and email_log.inbox_id:
            await unibox_events.publish({
                "type": "unibox.thread.updated",
                "reason": "tracking_open",
                "inbox_id": email_log.inbox_id,
                "thread_id": email_log.thread_id,
                "timestamp": now.isoformat() + "Z",
            })
    except Exception as sse_err:
        log.debug("SSE tracking event broadcast exception: %s", sse_err)

    await fire_webhook_event(
        db,
        "email.opened",
        {
            "email_log_id": email_log.id,
            "lead_id": email_log.lead_id,
            "campaign_id": email_log.campaign_id,
            "ip_address": ip,
            "timestamp": now.isoformat() + "Z",
        },
    )
    return True


async def resolve_click_redirect_url(db: AsyncSession, token: str) -> str | None:
    result = await db.execute(select(TrackedLink).where(TrackedLink.token == token))
    tracked = result.scalar_one_or_none()
    if not tracked:
        return None
    return tracked.original_url


async def record_email_click(db: AsyncSession, token: str, ip: str | None) -> bool:
    """Record click when TrackedLink exists and rules allow. Returns True if recorded."""
    result = await db.execute(select(TrackedLink).where(TrackedLink.token == token))
    tracked = result.scalar_one_or_none()
    if not tracked:
        return False
    email_log_result = await db.execute(select(EmailLog).where(EmailLog.id == tracked.email_log_id))
    email_log = email_log_result.scalar_one_or_none()
    if not email_log:
        return False
    if await is_known_ip(db, ip):
        log.debug("click: skipping known IP %s for log_id=%s", ip, email_log.id)
        return False
    if not email_log.clicked:
        email_log.clicked = True
    now = time_provider.utcnow()
    db.add(
        EmailClick(
            email_log_id=tracked.email_log_id,
            ip_address=ip,
            clicked_at=now,
        )
    )
    await db.commit()

    from app.unibox import unibox_events
    try:
        await unibox_events.publish({
            "type": "unibox.tracking.event",
            "event": "click",
            "channel": "campaign_email",
            "email_log_id": email_log.id,
            "thread_id": email_log.thread_id,
            "inbox_id": email_log.inbox_id,
            "lead_id": email_log.lead_id,
            "url": tracked.original_url,
            "timestamp": now.isoformat() + "Z",
        })
        if email_log.thread_id and email_log.inbox_id:
            await unibox_events.publish({
                "type": "unibox.thread.updated",
                "reason": "tracking_click",
                "inbox_id": email_log.inbox_id,
                "thread_id": email_log.thread_id,
                "timestamp": now.isoformat() + "Z",
            })
    except Exception as sse_err:
        log.debug("SSE tracking click broadcast exception: %s", sse_err)
    await fire_webhook_event(
        db,
        "email.clicked",
        {
            "email_log_id": tracked.email_log_id,
            "lead_id": email_log.lead_id,
            "campaign_id": email_log.campaign_id,
            "original_url": tracked.original_url,
            "ip_address": ip,
            "timestamp": time_provider.utcnow().isoformat() + "Z",
        },
    )
    return True


async def process_unsubscribe(db: AsyncSession, token: str) -> tuple[str, int]:
    """Run unsubscribe flow; return (html_body, http_status)."""
    result = await db.execute(select(LeadUnsubscribeToken).where(LeadUnsubscribeToken.token == token))
    row = result.scalar_one_or_none()
    if not row:
        return INVALID_UNSUBSCRIBE_HTML, 404

    lead_res = await db.execute(select(Lead).where(Lead.id == row.lead_id))
    lead = lead_res.scalar_one_or_none()

    already_done = False
    cl_res = await db.execute(
        select(CampaignLead).where(
            CampaignLead.lead_id == row.lead_id,
            CampaignLead.campaign_id == row.campaign_id,
        )
    )
    cl = cl_res.scalar_one_or_none()
    if not cl:
        already_done = True
    else:
        if cl.enrollment_status == "unsubscribed":
            already_done = True
        else:
            cl.enrollment_status = "unsubscribed"
            cl.interest_status = None
            log.info(
                "Unsubscribed lead_id=%s via campaign_id=%s token=%s",
                row.lead_id,
                row.campaign_id,
                token,
            )
        await db.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id == cl.id))

    await db.commit()

    if not already_done and lead and cl:
        await fire_webhook_event(
            db,
            "lead.unsubscribed",
            {
                "lead_id": row.lead_id,
                "lead_email": lead.email if lead else "",
                "campaign_id": row.campaign_id,
                "timestamp": time_provider.utcnow().isoformat() + "Z",
            },
        )
        await fire_webhook_event(
            db,
            "lead.status_changed",
            {
                "lead_id": row.lead_id,
                "lead_email": lead.email if lead else "",
                "campaign_id": row.campaign_id,
                "old_enrollment_status": "active",
                "new_enrollment_status": "unsubscribed",
                "timestamp": time_provider.utcnow().isoformat() + "Z",
            },
        )

    html = ALREADY_UNSUBSCRIBED_HTML if already_done else _UNSUBSCRIBE_HTML
    return html, 200
