"""Analytics endpoints — aggregated daily statistics, no row limit."""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, Date, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, CampaignLead, EmailClick, EmailLog, EmailOpen, Lead, LeadReply, Inbox, QueueSlot
from app.schemas import DashboardSummaryResponse

log = logging.getLogger("quickly.analytics")
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/daily")
async def daily_analytics(
    start_date: str = Query(..., description="Inclusive start date YYYY-MM-DD"),
    end_date: str = Query(..., description="Inclusive end date YYYY-MM-DD"),
    campaign_id: Optional[List[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return per-day, per-campaign aggregated stats for the requested range.

    No row limit — result size is bounded by (days × campaigns).
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date and end_date must be YYYY-MM-DD")

    # campaign name lookup
    camp_stmt = select(Campaign.id, Campaign.name)
    if campaign_id:
        camp_stmt = camp_stmt.where(Campaign.id.in_(campaign_id))
    camp_rows = (await db.execute(camp_stmt)).all()
    campaign_names = {cid: name for cid, name in camp_rows}

    # sent per day per campaign
    sent_stmt = (
        select(
            cast(EmailLog.sent_at, Date).label("day"),
            EmailLog.campaign_id,
            func.count().label("sent"),
        )
        .where(EmailLog.sent_at >= start, EmailLog.sent_at < end)
        .group_by(cast(EmailLog.sent_at, Date), EmailLog.campaign_id)
    )
    if campaign_id:
        sent_stmt = sent_stmt.where(EmailLog.campaign_id.in_(campaign_id))

    # opens per day per campaign
    opens_stmt = (
        select(
            cast(EmailOpen.opened_at, Date).label("day"),
            EmailLog.campaign_id,
            func.count().label("total_opens"),
            func.count(func.distinct(EmailOpen.ip_address)).label("unique_opens"),
        )
        .join(EmailLog, EmailOpen.email_log_id == EmailLog.id)
        .where(EmailOpen.opened_at >= start, EmailOpen.opened_at < end)
        .group_by(cast(EmailOpen.opened_at, Date), EmailLog.campaign_id)
    )
    if campaign_id:
        opens_stmt = opens_stmt.where(EmailLog.campaign_id.in_(campaign_id))

    # clicks per day per campaign
    clicks_stmt = (
        select(
            cast(EmailClick.clicked_at, Date).label("day"),
            EmailLog.campaign_id,
            func.count().label("total_clicks"),
            func.count(func.distinct(EmailClick.ip_address)).label("unique_clicks"),
        )
        .join(EmailLog, EmailClick.email_log_id == EmailLog.id)
        .where(EmailClick.clicked_at >= start, EmailClick.clicked_at < end)
        .group_by(cast(EmailClick.clicked_at, Date), EmailLog.campaign_id)
    )
    if campaign_id:
        clicks_stmt = clicks_stmt.where(EmailLog.campaign_id.in_(campaign_id))

    # replies per day per campaign (excluding OOO and auto-reply)
    replies_stmt = (
        select(
            cast(LeadReply.replied_at, Date).label("day"),
            LeadReply.campaign_id,
            func.count().label("total_replies"),
        )
        .join(
            CampaignLead,
            (LeadReply.lead_id == CampaignLead.lead_id)
            & (LeadReply.campaign_id == CampaignLead.campaign_id),
        )
        .where(
            LeadReply.replied_at >= start,
            LeadReply.replied_at < end,
            or_(
                CampaignLead.interest_status.is_(None),
                CampaignLead.interest_status.notin_(["out_of_office", "auto_reply"]),
            ),
        )
        .group_by(cast(LeadReply.replied_at, Date), LeadReply.campaign_id)
    )
    if campaign_id:
        replies_stmt = replies_stmt.where(LeadReply.campaign_id.in_(campaign_id))

    sent_rows    = (await db.execute(sent_stmt)).all()
    opens_rows   = (await db.execute(opens_stmt)).all()
    clicks_rows  = (await db.execute(clicks_stmt)).all()
    replies_rows = (await db.execute(replies_stmt)).all()

    result: dict[tuple, dict] = {}

    def _day_str(day) -> str:
        return day.isoformat() if hasattr(day, "isoformat") else str(day)

    def _ensure(day, cid: int) -> dict:
        k = (_day_str(day), int(cid))
        if k not in result:
            result[k] = {
                "date": k[0],
                "campaign_id": k[1],
                "campaign_name": campaign_names.get(k[1], ""),
                "sent": 0,
                "total_opens": 0,
                "unique_opens": 0,
                "total_clicks": 0,
                "unique_clicks": 0,
                "total_replies": 0,
            }
        return result[k]

    for row in sent_rows:
        _ensure(row.day, row.campaign_id)["sent"] = row.sent
    for row in opens_rows:
        entry = _ensure(row.day, row.campaign_id)
        entry["total_opens"] = row.total_opens
        entry["unique_opens"] = row.unique_opens
    for row in clicks_rows:
        entry = _ensure(row.day, row.campaign_id)
        entry["total_clicks"] = row.total_clicks
        entry["unique_clicks"] = row.unique_clicks
    for row in replies_rows:
        _ensure(row.day, row.campaign_id)["total_replies"] = row.total_replies

    return sorted(result.values(), key=lambda x: (x["date"], x["campaign_id"]))


@router.get("/dashboard", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """Central Executive Dashboard: returns real aggregated statistics across the platform."""
    # Total prospects
    prospects_res = await db.execute(select(func.count(Lead.id)))
    total_prospects = prospects_res.scalar() or 0

    # Total inboxes
    inboxes_res = await db.execute(select(func.count(Inbox.id)))
    total_inboxes = inboxes_res.scalar() or 0

    # Active campaigns (not paused)
    active_camps_res = await db.execute(select(func.count(Campaign.id)).where(Campaign.paused == False))  # noqa: E712
    active_campaigns = active_camps_res.scalar() or 0

    # Scheduled slots in queue
    sched_res = await db.execute(select(func.count(QueueSlot.id)))
    emails_scheduled = sched_res.scalar() or 0

    # Total emails sent
    sent_res = await db.execute(select(func.count(EmailLog.id)))
    emails_sent = sent_res.scalar() or 0

    # Detected open signals (estimated)
    opens_res = await db.execute(select(func.count(EmailLog.id)).where(EmailLog.opened == True))  # noqa: E712
    detected_opens = opens_res.scalar() or 0

    # Link clicks
    clicks_res = await db.execute(select(func.count(EmailLog.id)).where(EmailLog.clicked == True))  # noqa: E712
    link_clicks = clicks_res.scalar() or 0

    # Total replies received
    replies_res = await db.execute(select(func.count(LeadReply.id)))
    replies_received = replies_res.scalar() or 0

    # Interested prospects (from CampaignLead or Lead pipeline)
    interested_res = await db.execute(
        select(func.count(Lead.id)).where(
            or_(
                Lead.pipeline_status == "interested",
                select(1).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.interest_status == "interested",
                ).exists()
            )
        )
    )
    interested_prospects = interested_res.scalar() or 0

    # Bounced emails
    bounced_res = await db.execute(
        select(func.count(Lead.id)).where(
            or_(
                Lead.status == "bounced",
                select(1).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.enrollment_status == "bounced",
                ).exists()
            )
        )
    )
    bounced_emails = bounced_res.scalar() or 0

    # Unsubscribed prospects
    unsub_res = await db.execute(
        select(func.count(Lead.id)).where(
            or_(
                Lead.status == "unsubscribed",
                select(1).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.enrollment_status == "unsubscribed",
                ).exists()
            )
        )
    )
    unsubscribed_prospects = unsub_res.scalar() or 0

    # Meetings booked (when manually recorded via pipeline_status == 'meeting_scheduled')
    meetings_res = await db.execute(
        select(func.count(Lead.id)).where(Lead.pipeline_status == "meeting_scheduled")
    )
    meetings_booked = meetings_res.scalar() or 0

    # Calculate rates
    reply_rate = round((replies_received / emails_sent * 100), 2) if emails_sent > 0 else 0.0
    open_signal_rate = round((detected_opens / emails_sent * 100), 2) if emails_sent > 0 else 0.0
    click_rate = round((link_clicks / emails_sent * 100), 2) if emails_sent > 0 else 0.0
    bounce_rate = round((bounced_emails / emails_sent * 100), 2) if emails_sent > 0 else 0.0

    # Recent activity feed (most recent 15 send/reply events)
    recent_activity: list[dict] = []

    # Recent sent
    recent_logs = await db.execute(
        select(EmailLog, Lead.email, Campaign.name)
        .join(Lead, EmailLog.lead_id == Lead.id)
        .join(Campaign, EmailLog.campaign_id == Campaign.id)
        .order_by(desc(EmailLog.sent_at))
        .limit(10)
    )
    for log_row, lead_email, camp_name in recent_logs.all():
        recent_activity.append({
            "type": "sent",
            "title": f"Sent email to {lead_email}",
            "campaign": camp_name,
            "timestamp": log_row.sent_at.isoformat() if log_row.sent_at else None,
            "details": f"Sequence step #{log_row.sequence_index + 1}",
        })

    # Recent replies
    recent_replies = await db.execute(
        select(LeadReply, Lead.email, Campaign.name)
        .join(Lead, LeadReply.lead_id == Lead.id)
        .join(Campaign, LeadReply.campaign_id == Campaign.id)
        .order_by(desc(LeadReply.replied_at))
        .limit(10)
    )
    for reply_row, lead_email, camp_name in recent_replies.all():
        recent_activity.append({
            "type": "reply",
            "title": f"Reply received from {lead_email}",
            "campaign": camp_name,
            "timestamp": reply_row.replied_at.isoformat() if reply_row.replied_at else None,
            "details": "Inbound reply",
        })

    # Sort combined activity by timestamp descending
    recent_activity.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    recent_activity = recent_activity[:15]

    # Per-campaign performance table
    camps_res = await db.execute(select(Campaign).order_by(Campaign.name))
    campaigns = camps_res.scalars().all()
    campaign_performance = []

    for camp in campaigns:
        # Leads count
        c_leads_res = await db.execute(select(func.count(CampaignLead.id)).where(CampaignLead.campaign_id == camp.id))
        c_leads = c_leads_res.scalar() or 0

        # Sent count
        c_sent_res = await db.execute(select(func.count(EmailLog.id)).where(EmailLog.campaign_id == camp.id))
        c_sent = c_sent_res.scalar() or 0

        # Opens count
        c_opens_res = await db.execute(select(func.count(EmailLog.id)).where(EmailLog.campaign_id == camp.id, EmailLog.opened == True))  # noqa: E712
        c_opens = c_opens_res.scalar() or 0

        # Clicks count
        c_clicks_res = await db.execute(select(func.count(EmailLog.id)).where(EmailLog.campaign_id == camp.id, EmailLog.clicked == True))  # noqa: E712
        c_clicks = c_clicks_res.scalar() or 0

        # Replies count
        c_replies_res = await db.execute(select(func.count(LeadReply.id)).where(LeadReply.campaign_id == camp.id))
        c_replies = c_replies_res.scalar() or 0

        c_reply_rate = round((c_replies / c_sent * 100), 2) if c_sent > 0 else 0.0
        c_open_rate = round((c_opens / c_sent * 100), 2) if c_sent > 0 else 0.0
        c_click_rate = round((c_clicks / c_sent * 100), 2) if c_sent > 0 else 0.0

        campaign_performance.append({
            "id": camp.id,
            "name": camp.name,
            "paused": bool(camp.paused),
            "total_leads": c_leads,
            "emails_sent": c_sent,
            "detected_opens": c_opens,
            "open_rate": c_open_rate,
            "clicks": c_clicks,
            "click_rate": c_click_rate,
            "replies": c_replies,
            "reply_rate": c_reply_rate,
        })

    return {
        "total_prospects": total_prospects,
        "total_inboxes": total_inboxes,
        "active_campaigns": active_campaigns,
        "emails_scheduled": emails_scheduled,
        "emails_sent": emails_sent,
        "detected_opens": detected_opens,
        "link_clicks": link_clicks,
        "replies_received": replies_received,
        "interested_prospects": interested_prospects,
        "bounced_emails": bounced_emails,
        "unsubscribed_prospects": unsubscribed_prospects,
        "meetings_booked": meetings_booked,
        "reply_rate": reply_rate,
        "open_signal_rate": open_signal_rate,
        "click_rate": click_rate,
        "bounce_rate": bounce_rate,
        "estimated_opens": detected_opens,
        "open_rate": open_signal_rate,
        "recent_activity": recent_activity,
        "campaign_performance": campaign_performance,
    }

