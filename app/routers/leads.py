from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.auth import get_current_user
from app.verification_engine import (
    verify_single_email,
    validate_syntax_and_normalize,
    STATUS_VALID,
    STATUS_DOMAIN_VALIDATED,
    STATUS_INVALID,
    STATUS_RISKY,
    STATUS_CATCH_ALL,
    STATUS_UNKNOWN,
    STATUS_NOT_VERIFIED,
)
from app.verification_data import is_disposable_domain, check_role_account, check_typo_suggestion

"""Leads API routes."""
import asyncio
import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, exists, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.campaign_lead_status import LEAD_INTERESTS, normalize_enrollment_status, normalize_interest
from app.database import get_db
from app.lead_inbox_resolution import from_inbox_email_by_lead_campaign
from app.models import (
    Campaign,
    CampaignLead,
    DirectEmail,
    EmailLog,
    GmailMessage,
    ImportHistory,
    Inbox,
    Lead,
    LeadReply,
    Office365Message,
    QueueSlot,
    SmtpMessage,
)
from app.schemas import (
    BulkAssignSummary,
    LeadBulkAssignCampaignRequest,
    LeadBulkAssignResponse,
    LeadBulkDeleteRequest,
    LeadBulkPipelineStatusRequest,
    LeadBulkRecoverItem,
    LeadBulkRecoverRequest,
    LeadBulkStatusRequest,
    LeadCreate,
    LeadExportRequest,
    LeadRecoverRequest,
    LeadResponse,
    LeadUpdate,
    LeadCampaignInfo,
    MarkReplied,
)

log = logging.getLogger("quickly.routes")

router = APIRouter(prefix="/api/leads", tags=["leads"])


async def _engagement_pair_sets(
    db: AsyncSession, lead_ids: list[int]
) -> tuple[set[tuple[int, int]], set[tuple[int, int]], set[tuple[int, int]]]:
    """(lead_id, campaign_id) sets for opened, clicked, replied."""
    if not lead_ids:
        return set(), set(), set()
    o_res = await db.execute(
        select(EmailLog.lead_id, EmailLog.campaign_id)
        .where(EmailLog.lead_id.in_(lead_ids), EmailLog.opened == True)  # noqa: E712
        .distinct()
    )
    opened = {(r[0], r[1]) for r in o_res.all()}
    c_res = await db.execute(
        select(EmailLog.lead_id, EmailLog.campaign_id)
        .where(EmailLog.lead_id.in_(lead_ids), EmailLog.clicked == True)  # noqa: E712
        .distinct()
    )
    clicked = {(r[0], r[1]) for r in c_res.all()}
    r_res = await db.execute(
        select(LeadReply.lead_id, LeadReply.campaign_id)
        .where(LeadReply.lead_id.in_(lead_ids))
        .distinct()
    )
    replied = {(r[0], r[1]) for r in r_res.all()}
    return opened, clicked, replied


def _lead_to_response(
    lead: Lead,
    opened: set[tuple[int, int]],
    clicked: set[tuple[int, int]],
    replied: set[tuple[int, int]],
    *,
    interactions: list[dict] | None = None,
    inbox_by_pair: dict[tuple[int, int], str] | None = None,
) -> LeadResponse:
    camps = []
    ib = inbox_by_pair or {}
    cls = lead.__dict__.get('campaign_leads') or []
    for cl in cls:
        c = cl.__dict__.get('campaign')
        pair = (lead.id, cl.campaign_id)
        camps.append(
            LeadCampaignInfo(
                campaign_id=cl.campaign_id,
                campaign_public_id=c.public_id if c else "",
                campaign_name=c.name if c else "",
                campaign_paused=bool(c.paused) if c else False,
                enrolled_at=cl.enrolled_at,
                status=getattr(cl, "enrollment_status", None) or "active",
                interest=cl.interest_status,
                opened=pair in opened,
                clicked=pair in clicked,
                replied=pair in replied,
                sending_paused=cl.sending_paused,
                from_inbox_email=ib.get(pair),
            )
        )
    return LeadResponse(
        id=lead.id,
        email=lead.email,
        name=lead.name or "",
        company=getattr(lead, "company", "") or "",
        phone=getattr(lead, "phone", "") or "",
        website=getattr(lead, "website", "") or "",
        industry=getattr(lead, "industry", "") or "",
        city=getattr(lead, "city", "") or "",
        country=getattr(lead, "country", "") or "",
        lead_source=getattr(lead, "lead_source", "") or "",
        notes=getattr(lead, "notes", "") or "",
        pipeline_status=getattr(lead, "pipeline_status", "new") or "new",
        tags=lead.tags if isinstance(getattr(lead, "tags", None), list) else [],
        custom_data=lead.custom_data if isinstance(lead.custom_data, dict) else {},
        provider=lead.provider,
        email_verification_status=lead.email_verification_status,
        email_verification_result=lead.email_verification_result if isinstance(lead.email_verification_result, dict) else None,
        created_at=lead.created_at,
        campaigns=camps,
        interactions=interactions or [],
    )


def _lead_query_with_campaigns():
    return select(Lead).options(
        selectinload(Lead.campaign_leads).selectinload(CampaignLead.campaign),
    )


# Parsed interest query: None = no filter; "__unset__" = interest_status IS NULL; else a value in LEAD_INTERESTS.
_INTEREST_FILTER_UNSET = "__unset__"


def _parse_interest_filter_param(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip().lower()
    if not s or s in ("none", "null", "unset", "clear", "empty"):
        return _INTEREST_FILTER_UNSET
    if s in LEAD_INTERESTS:
        return s
    raise HTTPException(
        status_code=400,
        detail=f"Invalid interest filter {raw!r}; use one of: unset, {', '.join(sorted(LEAD_INTERESTS))}",
    )


def _campaign_lead_interest_predicate(parsed: str):
    if parsed == _INTEREST_FILTER_UNSET:
        return CampaignLead.interest_status.is_(None)
    return CampaignLead.interest_status == parsed


def _optional_interest_for_stmt(interest: str | None) -> str | None:
    """None = no interest filter. Empty string after strip = no filter."""
    if interest is None:
        return None
    s = interest.strip()
    if not s:
        return None
    return _parse_interest_filter_param(s)


def _build_leads_stmt(
    *,
    q: str | None = None,
    status: str | None = None,
    bad_only: bool = False,
    interest: str | None = None,
    country: str | None = None,
    state: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    tag: str | None = None,
    pipeline_status: str | None = None,
    email_verification_status: str | None = None,
    exclude_campaign_id: int | None = None,
    campaign_id: int | None = None,
):
    stmt = _lead_query_with_campaigns().order_by(Lead.id.desc())
    if bad_only:
        bounced_enrollment = exists(
            select(1).select_from(CampaignLead).where(
                CampaignLead.lead_id == Lead.id,
                CampaignLead.enrollment_status == "bounced",
            )
        )
        stmt = stmt.where(
            or_(
                Lead.email_verification_status.in_(("invalid", "risky")),
                Lead.status.in_(("invalid", "bounced")),
                bounced_enrollment,
            )
        )

    st = (status or "").strip().lower() or None
    intr = interest

    merged_enrollment_interest = False
    if st and st not in ("invalid", "replied") and intr is not None:
        stmt = stmt.where(
            exists(
                select(1).select_from(CampaignLead).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.enrollment_status == st,
                    _campaign_lead_interest_predicate(intr),
                )
            )
        )
        merged_enrollment_interest = True
    elif st == "invalid":
        stmt = stmt.where(
            or_(
                Lead.email_verification_status == "invalid",
                Lead.status == "invalid",
            )
        )
    elif st == "replied":
        stmt = stmt.where(
            exists(select(1).select_from(LeadReply).where(LeadReply.lead_id == Lead.id))
        )
    elif st and st != "all":
        stmt = stmt.where(
            exists(
                select(1).select_from(CampaignLead).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.enrollment_status == st,
                )
            )
        )

    if intr is not None and not merged_enrollment_interest:
        stmt = stmt.where(
            exists(
                select(1).select_from(CampaignLead).where(
                    CampaignLead.lead_id == Lead.id,
                    _campaign_lead_interest_predicate(intr),
                )
            )
        )

    if country and country.strip() and country.strip().lower() != "all":
        c_low = country.strip().lower()
        if c_low in ("united states", "usa", "us", "united state"):
            stmt = stmt.where(func.lower(Lead.country).in_(("united states", "united state", "usa", "us")))
        elif c_low in ("united kingdom", "uk", "great britain", "england"):
            stmt = stmt.where(func.lower(Lead.country).in_(("united kingdom", "uk", "great britain", "england")))
        elif c_low in ("canada", "ca"):
            stmt = stmt.where(func.lower(Lead.country).in_(("canada", "ca")))
        elif c_low in ("australia", "au"):
            stmt = stmt.where(func.lower(Lead.country).in_(("australia", "au")))
        else:
            stmt = stmt.where(func.lower(Lead.country) == c_low)

    if state and state.strip() and state.strip().lower() != "all":
        from app.database import engine
        state_expr = (
            func.json_extract_path_text(Lead.custom_data, "state")
            if engine.dialect.name == "postgresql"
            else func.json_extract(Lead.custom_data, "$.state")
        )
        stmt = stmt.where(func.lower(state_expr) == state.strip().lower())

    if city and city.strip() and city.strip().lower() != "all":
        stmt = stmt.where(func.lower(Lead.city) == city.strip().lower())

    if industry and industry.strip() and industry.strip().lower() != "all":
        ind_low = industry.strip().lower()
        if ind_low in ("web design & marketing agency", "web design and marketing agnacy"):
            stmt = stmt.where(func.lower(Lead.industry).in_(("web design & marketing agency", "web design and marketing agnacy")))
        else:
            stmt = stmt.where(func.lower(Lead.industry) == ind_low)

    if pipeline_status and pipeline_status.strip() and pipeline_status.strip().lower() != "all":
        stmt = stmt.where(func.lower(Lead.pipeline_status) == pipeline_status.strip().lower())

    if email_verification_status and email_verification_status.strip() and email_verification_status.strip().lower() != "all":
        ev_s = email_verification_status.strip().lower()
        if ev_s in ("unverified", "null", "none"):
            stmt = stmt.where(
                or_(
                    Lead.email_verification_status.is_(None),
                    Lead.email_verification_status == "",
                    Lead.email_verification_status == "not_verified",
                )
            )
        else:
            stmt = stmt.where(func.lower(Lead.email_verification_status) == ev_s)

    if tag and tag.strip() and tag.strip().lower() != "all":
        from sqlalchemy import String, cast
        stmt = stmt.where(cast(Lead.tags, String).ilike(f"%{tag.strip()}%"))

    if exclude_campaign_id:
        stmt = stmt.where(
            ~exists(
                select(1).select_from(CampaignLead).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.campaign_id == exclude_campaign_id,
                )
            )
        )

    if campaign_id:
        stmt = stmt.where(
            exists(
                select(1).select_from(CampaignLead).where(
                    CampaignLead.lead_id == Lead.id,
                    CampaignLead.campaign_id == campaign_id,
                )
            )
        )

    if q and q.strip():
        pat = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.email.ilike(pat),
                Lead.name.ilike(pat),
                Lead.company.ilike(pat),
                Lead.phone.ilike(pat),
            )
        )
    return stmt


async def _reset_all_enrollments_for_lead(db: AsyncSession, lead_id: int) -> None:
    res = await db.execute(select(CampaignLead).where(CampaignLead.lead_id == lead_id))
    for cl in res.scalars().all():
        cl.enrollment_status = "active"
        cl.interest_status = None
        cl.sending_paused = False


async def _fetch_lead_interactions(db: AsyncSession, lead_id: int) -> list[dict]:
    """Merge outbound EmailLog rows with inbound mirrored messages (Gmail / O365) and direct emails."""
    from app.sender import get_lead_data, render_body, RenderContext

    res = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = res.scalar_one_or_none()
    if not lead:
        return []

    lead_data_ctx = get_lead_data(lead)
    render_ctx = RenderContext()
    events: list[dict] = []

    log_rows = await db.execute(
        select(EmailLog, Campaign.name, Campaign.public_id, Inbox.email)
        .join(Campaign, EmailLog.campaign_id == Campaign.id)
        .outerjoin(Inbox, EmailLog.inbox_id == Inbox.id)
        .where(EmailLog.lead_id == lead_id)
        .order_by(EmailLog.sent_at.asc())
    )
    for el, cname, pub, from_inbox_email in log_rows.all():
        display_subj = render_body(el.subject or "", lead_data_ctx, render_ctx) if "{{" in (el.subject or "") else (el.subject or "")
        display_bdy = render_body(el.body or "", lead_data_ctx, render_ctx) if "{{" in (el.body or "") else (el.body or "")
        events.append(
            {
                "id": el.id,
                "direction": "outbound",
                "kind": "campaign_email",
                "channel": "campaign",
                "at": el.sent_at.isoformat() if el.sent_at else None,
                "campaign_id": el.campaign_id,
                "campaign_name": cname,
                "campaign_public_id": pub,
                "from_email": from_inbox_email or "",
                "to_email": lead.email,
                "recipient_name": lead.name or "",
                "subject": display_subj,
                "status": "sent",
                "sequence_index": el.sequence_index,
                "snippet": display_bdy[:500],
                "body": display_bdy,
            }
        )

    th_rows = await db.execute(
        select(EmailLog.thread_id)
        .where(
            EmailLog.lead_id == lead_id,
            EmailLog.thread_id.isnot(None),
            EmailLog.thread_id != "",
        )
        .distinct()
    )
    thread_ids = [r[0] for r in th_rows.all()]
    lead_em = (lead.email or "").strip().lower()

    if thread_ids and lead_em:
        from app.unibox import _extract_email_only, _header_value

        gm_res = await db.execute(
            select(GmailMessage).where(GmailMessage.thread_id.in_(thread_ids))
        )
        for msg in gm_res.scalars().all():
            try:
                from_a = _extract_email_only(_header_value(msg.headers_json or "[]", "From"))
            except Exception:
                from_a = ""
            if (from_a or "").strip().lower() != lead_em:
                continue
            subj = _header_value(msg.headers_json or "[]", "Subject") or ""
            ts = None
            if msg.internal_date is not None:
                ts = datetime.utcfromtimestamp(int(msg.internal_date) / 1000.0).isoformat() + "Z"
            events.append(
                {
                    "direction": "inbound",
                    "kind": "received",
                    "channel": "gmail",
                    "at": ts or (msg.updated_at.isoformat() if msg.updated_at else None),
                    "thread_id": msg.thread_id,
                    "from_email": from_a or lead.email,
                    "to_email": "",
                    "subject": subj,
                    "status": "received",
                    "snippet": (msg.snippet or "")[:500],
                    "body": msg.snippet or "",
                }
            )

        o365_res = await db.execute(
            select(Office365Message).where(Office365Message.conversation_id.in_(thread_ids))
        )
        for msg in o365_res.scalars().all():
            if (msg.from_address or "").strip().lower() != lead_em:
                continue
            bdy = msg.body_plain or msg.body_html or ""
            events.append(
                {
                    "direction": "inbound",
                    "kind": "received",
                    "channel": "office365",
                    "at": msg.received_at.isoformat() if msg.received_at else None,
                    "thread_id": msg.conversation_id,
                    "from_email": msg.from_address,
                    "to_email": lead.email,
                    "subject": msg.subject or "",
                    "status": "received",
                    "snippet": bdy[:500],
                    "body": bdy,
                }
            )

        smtp_res = await db.execute(
            select(SmtpMessage).where(SmtpMessage.thread_key.in_(thread_ids))
        )
        for msg in smtp_res.scalars().all():
            if (msg.from_address or "").strip().lower() != lead_em:
                continue
            bdy = msg.body_plain or msg.body_html or ""
            events.append(
                {
                    "direction": "inbound",
                    "kind": "received",
                    "channel": "smtp",
                    "at": msg.received_at.isoformat() if msg.received_at else None,
                    "thread_id": msg.thread_key,
                    "from_email": msg.from_address,
                    "to_email": lead.email,
                    "subject": msg.subject or "",
                    "status": "received",
                    "snippet": bdy[:500],
                    "body": bdy,
                }
            )

    lr_rows = await db.execute(
        select(LeadReply, Campaign.name, Campaign.public_id)
        .join(Campaign, LeadReply.campaign_id == Campaign.id)
        .where(LeadReply.lead_id == lead_id)
        .order_by(LeadReply.replied_at.asc())
    )
    for lr, cname, pub in lr_rows.all():
        events.append(
            {
                "direction": "inbound",
                "kind": "reply_marker",
                "channel": "campaign",
                "at": lr.replied_at.isoformat(),
                "campaign_id": lr.campaign_id,
                "campaign_name": cname,
                "campaign_public_id": pub,
                "from_email": lead.email,
                "to_email": "",
                "subject": "Reply received",
                "status": "replied",
                "snippet": "Lead replied to campaign outreach",
                "body": "Lead replied to campaign outreach",
            }
        )

    # Direct / Compose emails associated with this lead
    from app.models import DirectEmail
    de_rows = await db.execute(
        select(DirectEmail, Inbox.email)
        .outerjoin(Inbox, DirectEmail.inbox_id == Inbox.id)
        .where(
            (DirectEmail.lead_id == lead_id) | (func.lower(DirectEmail.to_email) == lead_em)
        ).order_by(DirectEmail.created_at.asc())
    )
    for de, from_inbox_email in de_rows.all():
        display_subj = render_body(de.subject or "", lead_data_ctx, render_ctx) if "{{" in (de.subject or "") else (de.subject or "")
        display_bdy = render_body(de.body or "", lead_data_ctx, render_ctx) if "{{" in (de.body or "") else (de.body or "")
        events.append(
            {
                "id": de.id,
                "direction": "outbound",
                "kind": "direct_email",
                "channel": "direct_email",
                "at": (de.sent_at or de.created_at).isoformat() if (de.sent_at or de.created_at) else None,
                "from_email": from_inbox_email or "",
                "to_email": de.to_email,
                "recipient_name": de.recipient_name or lead.name or "",
                "subject": display_subj,
                "status": de.status or "sent",
                "opened": de.opened,
                "error_message": de.error_message,
                "snippet": display_bdy[:500],
                "body": display_bdy,
            }
        )

    events.sort(key=lambda e: (e.get("at") or "", e.get("direction", "")))
    from app.unibox_tracking import enrich_lead_interactions_with_tracking
    await enrich_lead_interactions_with_tracking(db, events, lead_id)
    return events


async def _fetch_lead_interactions_batch(
    db: AsyncSession, lead_ids: list[int]
) -> dict[int, list[dict]]:
    """Batch equivalent of _fetch_lead_interactions; returns dict[lead_id, events]."""
    if not lead_ids:
        return {}

    res = await db.execute(select(Lead).where(Lead.id.in_(lead_ids)))
    leads = {l.id: l for l in res.scalars().all()}
    email_map = {lid: (lead.email or "").strip().lower() for lid, lead in leads.items()}

    events_map: dict[int, list[dict]] = {lid: [] for lid in lead_ids}

    log_rows = await db.execute(
        select(EmailLog, Campaign.name, Campaign.public_id)
        .join(Campaign, EmailLog.campaign_id == Campaign.id)
        .where(EmailLog.lead_id.in_(lead_ids))
        .order_by(EmailLog.sent_at.asc())
    )
    for el, cname, pub in log_rows.all():
        events_map[el.lead_id].append(
            {
                "direction": "outbound",
                "kind": "sent",
                "at": el.sent_at.isoformat(),
                "campaign_id": el.campaign_id,
                "campaign_name": cname,
                "campaign_public_id": pub,
                "subject": el.subject or "",
                "sequence_index": el.sequence_index,
            }
        )

    th_res = await db.execute(
        select(EmailLog.lead_id, EmailLog.thread_id)
        .where(
            EmailLog.lead_id.in_(lead_ids),
            EmailLog.thread_id.isnot(None),
            EmailLog.thread_id != "",
        )
        .distinct()
    )
    tid_to_leads: dict[str, list[int]] = {}
    for lid, tid in th_res.all():
        tid_to_leads.setdefault(tid, []).append(lid)
    all_thread_ids = list(tid_to_leads.keys())

    if all_thread_ids:
        from app.unibox import _extract_email_only, _header_value

        gm_res = await db.execute(
            select(GmailMessage).where(GmailMessage.thread_id.in_(all_thread_ids))
        )
        for msg in gm_res.scalars().all():
            try:
                from_a = _extract_email_only(_header_value(msg.headers_json or "[]", "From"))
            except Exception:
                from_a = ""
            from_a = (from_a or "").strip().lower()
            for lid in tid_to_leads.get(msg.thread_id, []):
                if from_a == email_map.get(lid, ""):
                    subj = _header_value(msg.headers_json or "[]", "Subject") or ""
                    ts = None
                    if msg.internal_date is not None:
                        ts = datetime.utcfromtimestamp(int(msg.internal_date) / 1000.0).isoformat() + "Z"
                    events_map[lid].append(
                        {
                            "direction": "inbound",
                            "kind": "received",
                            "channel": "gmail",
                            "at": ts or (msg.updated_at.isoformat() if msg.updated_at else None),
                            "thread_id": msg.thread_id,
                            "subject": subj,
                            "snippet": (msg.snippet or "")[:500],
                        }
                    )
                    break

        o365_res = await db.execute(
            select(Office365Message).where(Office365Message.conversation_id.in_(all_thread_ids))
        )
        for msg in o365_res.scalars().all():
            for lid in tid_to_leads.get(msg.conversation_id, []):
                if (msg.from_address or "").strip().lower() == email_map.get(lid, ""):
                    events_map[lid].append(
                        {
                            "direction": "inbound",
                            "kind": "received",
                            "channel": "office365",
                            "at": msg.received_at.isoformat() if msg.received_at else None,
                            "thread_id": msg.conversation_id,
                            "subject": msg.subject or "",
                            "snippet": (msg.body_plain or msg.body_html or "")[:500],
                        }
                    )
                    break

    lr_rows = await db.execute(
        select(LeadReply, Campaign.name, Campaign.public_id)
        .join(Campaign, LeadReply.campaign_id == Campaign.id)
        .where(LeadReply.lead_id.in_(lead_ids))
        .order_by(LeadReply.replied_at.asc())
    )
    for lr, cname, pub in lr_rows.all():
        events_map[lr.lead_id].append(
            {
                "direction": "inbound",
                "kind": "reply_marker",
                "at": lr.replied_at.isoformat(),
                "campaign_id": lr.campaign_id,
                "campaign_name": cname,
                "campaign_public_id": pub,
            }
        )

    # Direct / Compose emails associated with these leads
    lead_emails = [e for e in email_map.values() if e]
    if lead_ids or lead_emails:
        de_conds = []
        if lead_ids:
            de_conds.append(DirectEmail.lead_id.in_(lead_ids))
        if lead_emails:
            de_conds.append(func.lower(DirectEmail.to_email).in_(lead_emails))
        if de_conds:
            from sqlalchemy import or_
            de_rows = await db.execute(select(DirectEmail).where(or_(*de_conds)).order_by(DirectEmail.created_at.asc()))
            for de in de_rows.scalars().all():
                target_lid = de.lead_id
                if not target_lid or target_lid not in events_map:
                    for lid, em in email_map.items():
                        if em == (de.to_email or "").strip().lower():
                            target_lid = lid
                            break
                if target_lid and target_lid in events_map:
                    events_map[target_lid].append(
                        {
                            "direction": "outbound",
                            "kind": f"direct_email ({de.status})",
                            "at": (de.sent_at or de.created_at).isoformat() if (de.sent_at or de.created_at) else None,
                            "subject": de.subject or "",
                            "status": de.status,
                            "opened": de.opened,
                            "snippet": (de.body or "")[:500],
                        }
                    )

    for lid in lead_ids:
        events_map[lid].sort(key=lambda e: (e.get("at") or "", e.get("direction", "")))

    return events_map


def _enrolled_earliest_iso(lead: Lead) -> str:
    if not lead.campaign_leads:
        return ""
    dates = [cl.enrolled_at for cl in lead.campaign_leads if cl.enrolled_at]
    if not dates:
        return ""
    earliest = min(dates)
    if isinstance(earliest, datetime):
        return earliest.date().isoformat()
    return str(earliest)


async def _mutate_lead_recover(lead: Lead, norm: str, verify: bool) -> None:
    from app.email_verification import PENDING

    lead.email = norm
    lead.status = "active"
    lead.provider = None
    if verify:
        lead.email_verification_status = PENDING
    else:
        lead.email_verification_status = None


async def _after_lead_recovered(db: AsyncSession, lead_id: int) -> None:
    await _reset_all_enrollments_for_lead(db, lead_id)


async def _finalize_lead_recovery(
    db: AsyncSession,
    lead_ids: list[int],
    verify: bool,
    background_tasks: BackgroundTasks,
) -> None:
    if not lead_ids:
        return
    if verify:
        from app.routers.campaigns import _run_background_verification

        asyncio.create_task(_run_background_verification(lead_ids))
    else:
        await db.commit()
        from app.routers.schedule import enqueue_global_recalculate

        enqueue_global_recalculate(background_tasks)


@router.get("", response_model=list[LeadResponse])
async def list_leads(
    status: str | None = Query(None),
    bad_only: bool = Query(
        False,
        description="If true, narrow to bounced/invalid-style leads; stacks with status and interest when those are set.",
    ),
    interest: str | None = Query(
        None,
        description="Filter by per-enrollment interest: interested, not_interested, out_of_office, auto_reply, or unset (cleared / null). Stacks with status and bad_only.",
    ),
    q: str | None = Query(None, description="Search email, name, or company (substring)"),
    country: str | None = Query(None),
    state: str | None = Query(None),
    city: str | None = Query(None),
    industry: str | None = Query(None),
    tag: str | None = Query(None),
    pipeline_status: str | None = Query(None),
    email_verification_status: str | None = Query(None),
    exclude_campaign_id: int | None = Query(None),
    campaign_id: int | None = Query(None),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    intr = _optional_interest_for_stmt(interest)
    stmt = _build_leads_stmt(
        q=q,
        status=status,
        bad_only=bad_only,
        interest=intr,
        country=country,
        state=state,
        city=city,
        industry=industry,
        tag=tag,
        pipeline_status=pipeline_status,
        email_verification_status=email_verification_status,
        exclude_campaign_id=exclude_campaign_id,
        campaign_id=campaign_id,
    )
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    leads = result.scalars().all()
    ids = [x.id for x in leads]
    opened, clicked, replied = await _engagement_pair_sets(db, ids)
    pairs: set[tuple[int, int]] = set()
    for x in leads:
        for cl in x.campaign_leads:
            pairs.add((x.id, cl.campaign_id))
    inbox_by_pair = await from_inbox_email_by_lead_campaign(db, pairs)
    interactions_map = await _fetch_lead_interactions_batch(db, ids) if ids else {}
    return [
        _lead_to_response(
            x, opened, clicked, replied,
            interactions=interactions_map.get(x.id, []),
            inbox_by_pair=inbox_by_pair,
        )
        for x in leads
    ]




@router.get("/facet-counts")
async def get_lead_facet_counts(
    q: str | None = Query(None),
    country: str | None = Query(None),
    state: str | None = Query(None),
    industry: str | None = Query(None),
    exclude_campaign_id: int | None = Query(None),
    campaign_id: int | None = Query(None),
    pipeline_status: str | None = Query(None),
    email_verification_status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return accurate, dynamic prospect facet counts for Country, State, and Industry dropdowns.
    Follows faceted navigation rules: each dropdown calculates against other active filters without
    improperly applying its own selection.
    """
    from app.database import engine
    state_expr = (
        func.json_extract_path_text(Lead.custom_data, "state")
        if engine.dialect.name == "postgresql"
        else func.json_extract(Lead.custom_data, "$.state")
    )

    def _build_clauses(skip_country: bool = False, skip_state: bool = False, skip_industry: bool = False):
        clauses = []
        if exclude_campaign_id:
            clauses.append(
                ~exists(
                    select(1).select_from(CampaignLead).where(
                        CampaignLead.lead_id == Lead.id,
                        CampaignLead.campaign_id == exclude_campaign_id,
                    )
                )
            )
        if campaign_id:
            clauses.append(
                exists(
                    select(1).select_from(CampaignLead).where(
                        CampaignLead.lead_id == Lead.id,
                        CampaignLead.campaign_id == campaign_id,
                    )
                )
            )
        if q and q.strip():
            term = f"%{q.strip().lower()}%"
            clauses.append(
                or_(
                    func.lower(Lead.email).ilike(term),
                    func.lower(Lead.name).ilike(term),
                    func.lower(Lead.company).ilike(term),
                )
            )
        if pipeline_status and pipeline_status.strip().lower() != "all":
            clauses.append(func.lower(Lead.pipeline_status) == pipeline_status.strip().lower())
        if email_verification_status and email_verification_status.strip().lower() != "all":
            ev_s = email_verification_status.strip().lower()
            if ev_s in ("unverified", "null", "none"):
                clauses.append(
                    or_(
                        Lead.email_verification_status.is_(None),
                        Lead.email_verification_status == "",
                        Lead.email_verification_status == "not_verified",
                    )
                )
            else:
                clauses.append(func.lower(Lead.email_verification_status) == ev_s)

        if not skip_country and country and country.strip().lower() != "all":
            c_low = country.strip().lower()
            if c_low in ("united states", "usa", "us", "united state"):
                clauses.append(func.lower(Lead.country).in_(("united states", "united state", "usa", "us")))
            elif c_low in ("united kingdom", "uk", "great britain", "england"):
                clauses.append(func.lower(Lead.country).in_(("united kingdom", "uk", "great britain", "england")))
            elif c_low in ("canada", "ca"):
                clauses.append(func.lower(Lead.country).in_(("canada", "ca")))
            elif c_low in ("australia", "au"):
                clauses.append(func.lower(Lead.country).in_(("australia", "au")))
            else:
                clauses.append(func.lower(Lead.country) == c_low)

        if not skip_state and state and state.strip().lower() != "all":
            clauses.append(func.lower(state_expr) == state.strip().lower())

        if not skip_industry and industry and industry.strip().lower() != "all":
            ind_low = industry.strip().lower()
            if ind_low in ("web design & marketing agency", "web design and marketing agnacy"):
                clauses.append(func.lower(Lead.industry).in_(("web design & marketing agency", "web design and marketing agnacy")))
            else:
                clauses.append(func.lower(Lead.industry) == ind_low)

        return clauses

    # 1. Total matching leads under ALL active filters
    all_clauses = _build_clauses()
    total_matching = await db.scalar(select(func.count(Lead.id)).where(*all_clauses)) or 0

    # 2. Country facet counts (skip country's own filter)
    country_clauses = _build_clauses(skip_country=True)
    c_stmt = (
        select(Lead.country, func.count(Lead.id))
        .where(*country_clauses, Lead.country.isnot(None), Lead.country != "")
        .group_by(Lead.country)
    )
    c_res = await db.execute(c_stmt)
    country_map: dict[str, int] = {}
    for c_val, cnt in c_res.all():
        if not c_val:
            continue
        c_clean = c_val.strip()
        c_low = c_clean.lower()
        if c_low in ("usa", "us", "united states", "united state"):
            norm = "United States"
        elif c_low in ("uk", "united kingdom", "great britain", "england"):
            norm = "United Kingdom"
        elif c_low in ("ca", "canada"):
            norm = "Canada"
        elif c_low in ("au", "australia"):
            norm = "Australia"
        else:
            norm = c_clean.title()
        country_map[norm] = country_map.get(norm, 0) + cnt

    countries_list = [
        {"name": k, "count": country_map[k]}
        for k in sorted(country_map.keys())
    ]
    all_countries_count = sum(country_map.values())

    # 3. State facet counts (skip state's own filter, but RESPECT country and industry!)
    state_clauses = _build_clauses(skip_state=True)
    s_stmt = (
        select(state_expr, func.count(Lead.id))
        .where(*state_clauses, state_expr.isnot(None), state_expr != "")
        .group_by(state_expr)
    )
    s_res = await db.execute(s_stmt)
    state_map: dict[str, int] = {}
    for s_val, cnt in s_res.all():
        if not s_val:
            continue
        s_clean = str(s_val).strip()
        state_map[s_clean] = state_map.get(s_clean, 0) + cnt

    states_list = [
        {"name": k, "count": state_map[k]}
        for k in sorted(state_map.keys())
    ]
    state_all_count = await db.scalar(
        select(func.count(Lead.id)).where(*state_clauses)
    ) or 0

    # 4. Industry facet counts (skip industry's own filter, but RESPECT country and state!)
    industry_clauses = _build_clauses(skip_industry=True)
    i_stmt = (
        select(Lead.industry, func.count(Lead.id))
        .where(*industry_clauses, Lead.industry.isnot(None), Lead.industry != "")
        .group_by(Lead.industry)
    )
    i_res = await db.execute(i_stmt)
    industry_map: dict[str, int] = {}
    for i_val, cnt in i_res.all():
        if not i_val:
            continue
        i_clean = str(i_val).strip()
        if i_clean.lower() == "web design and marketing agnacy":
            norm = "Web Design & Marketing Agency"
        else:
            norm = i_clean
        industry_map[norm] = industry_map.get(norm, 0) + cnt

    industries_list = [
        {"name": k, "count": industry_map[k]}
        for k in sorted(industry_map.keys())
    ]
    industry_all_count = await db.scalar(
        select(func.count(Lead.id)).where(*industry_clauses)
    ) or 0

    return {
        "total_matching": total_matching,
        "all_countries_count": all_countries_count,
        "state_all_count": state_all_count,
        "industry_all_count": industry_all_count,
        "countries": countries_list,
        "states": states_list,
        "industries": industries_list,
    }


@router.get("/filter-options")
async def get_filter_options(db: AsyncSession = Depends(get_db)):
    """Return distinct countries, cities, industries, tags, pipeline_statuses, and verification statuses."""
    country_res = await db.execute(select(Lead.country).distinct().where(Lead.country.isnot(None), Lead.country != ""))
    countries = sorted([r[0] for r in country_res.all() if r[0]])

    city_res = await db.execute(select(Lead.city).distinct().where(Lead.city.isnot(None), Lead.city != ""))
    cities = sorted([r[0] for r in city_res.all() if r[0]])

    ind_res = await db.execute(
        select(Lead.industry, func.count(Lead.id))
        .where(Lead.industry.isnot(None), Lead.industry != "")
        .group_by(Lead.industry)
    )
    industry_counts = {}
    for r in ind_res.all():
        if r[0] and str(r[0]).strip():
            industry_counts[str(r[0]).strip()] = r[1]
    industries = sorted(list(industry_counts.keys()))

    total_leads_res = await db.execute(select(func.count(Lead.id)))
    total_leads = total_leads_res.scalar() or 0

    cd_res = await db.execute(select(Lead.custom_data).where(Lead.custom_data.isnot(None)))
    state_set = set()
    for row in cd_res.scalars().all():
        if isinstance(row, dict) and row.get("state"):
            s_val = str(row["state"]).strip()
            if s_val:
                state_set.add(s_val)
    states = sorted(list(state_set))

    pipe_res = await db.execute(select(Lead.pipeline_status).distinct().where(Lead.pipeline_status.isnot(None), Lead.pipeline_status != ""))
    pipeline_statuses = sorted([r[0] for r in pipe_res.all() if r[0]])

    tags_res = await db.execute(select(Lead.tags).where(Lead.tags.isnot(None)))
    tag_set = set()
    for row in tags_res.scalars().all():
        if isinstance(row, list):
            for t in row:
                if t and isinstance(t, str):
                    tag_set.add(t.strip())
    tags = sorted(list(tag_set))

    verification_statuses = [
        "valid", "domain_validated", "risky", "unknown", "catch_all", "invalid", "pending", "unverified"
    ]

    return {
        "countries": countries,
        "states": states,
        "cities": cities,
        "industries": industries,
        "industry_counts": industry_counts,
        "total_leads": total_leads,
        "pipeline_statuses": pipeline_statuses,
        "tags": tags,
        "verification_statuses": verification_statuses,
    }


@router.get("/import-history")
async def list_import_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Return past prospect import history records."""
    res = await db.execute(
        select(ImportHistory).order_by(ImportHistory.created_at.desc()).limit(limit)
    )
    history = res.scalars().all()
    return [
        {
            "id": h.id,
            "filename": h.filename,
            "total_rows": h.total_rows,
            "imported_count": h.imported_count,
            "duplicate_count": h.duplicate_count,
            "invalid_count": h.invalid_count,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in history
    ]


def _sanitize_csv_cell(val: Any) -> str:
    """Protect against CSV / Spreadsheet formula injection (CWE-1236).
    If a cell starts with '=', '+', '-', '@', tab, or carriage return,
    prefix with single quote so Excel/Sheets treats it as a literal string.
    This also prevents Excel arithmetic errors on leading + country phone numbers.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _generate_prospects_csv_text(leads: list[Lead]) -> str:
    """Generate clean, Excel/Google Sheets compatible CSV with UTF-8 BOM and proper escaping."""
    output = io.StringIO()
    # Write UTF-8 BOM for automatic Microsoft Excel & Google Sheets UTF-8 recognition
    output.write("\ufeff")
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Collect any dynamic custom keys across all leads
    custom_keys: set[str] = set()
    for lead in leads:
        cd = lead.custom_data
        if isinstance(cd, dict):
            custom_keys.update(cd.keys())
    sorted_custom = sorted(custom_keys)

    headers = [
        "Lead ID",
        "Company Name",
        "Contact Name",
        "Email Address",
        "Phone Number",
        "Website URL",
        "Email Verification Status",
        "Pipeline Status",
        "City",
        "Country",
        "Industry",
        "Lead Source",
        "Tags",
        "Campaigns",
        "Created At",
        "Notes",
        *sorted_custom,
    ]
    writer.writerow(headers)

    for lead in leads:
        # Formatted tags: clean comma-separated list
        tags_str = ""
        if isinstance(lead.tags, list):
            tags_str = ", ".join(str(t).strip() for t in lead.tags if t)
        elif lead.tags:
            tags_str = str(lead.tags).strip()

        # Formatted campaigns: clean comma-separated campaign names
        camps_str = ", ".join(
            cl.campaign.name
            for cl in (lead.campaign_leads or [])
            if cl.campaign and cl.campaign.name
        )

        # Formatted created_at timestamp
        created_str = ""
        if lead.created_at:
            if isinstance(lead.created_at, datetime):
                created_str = lead.created_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_str = str(lead.created_at)

        row = [
            str(lead.id),
            getattr(lead, "company", "") or "",
            getattr(lead, "name", "") or "",
            lead.email or "",
            getattr(lead, "phone", "") or "",
            getattr(lead, "website", "") or "",
            lead.email_verification_status or "unverified",
            getattr(lead, "pipeline_status", "new") or "new",
            getattr(lead, "city", "") or "",
            getattr(lead, "country", "") or "",
            getattr(lead, "industry", "") or "",
            getattr(lead, "lead_source", "") or "",
            tags_str,
            camps_str,
            created_str,
            getattr(lead, "notes", "") or "",
        ]

        cd = lead.custom_data if isinstance(lead.custom_data, dict) else {}
        for k in sorted_custom:
            val = cd.get(k, "")
            if val is None:
                row.append("")
            elif isinstance(val, (dict, list)):
                row.append(json.dumps(val, ensure_ascii=False))
            else:
                row.append(str(val))

        writer.writerow([_sanitize_csv_cell(c) for c in row])

    output.seek(0)
    return output.getvalue()


@router.post("/export")
async def export_leads_csv_post(
    req: LeadExportRequest,
    db: AsyncSession = Depends(get_db),
):
    """POST endpoint for exporting all, filtered, or selected prospects to CSV."""
    if req.scope == "selected" and req.lead_ids:
        stmt = _lead_query_with_campaigns().where(Lead.id.in_(req.lead_ids)).order_by(Lead.id.desc())
    elif req.scope == "all":
        stmt = _lead_query_with_campaigns().order_by(Lead.id.desc())
    else:  # filtered
        intr = _optional_interest_for_stmt(req.interest)
        stmt = _build_leads_stmt(
            q=req.q,
            status=req.status,
            bad_only=req.bad_only,
            interest=intr,
            country=req.country,
            city=req.city,
            industry=req.industry,
            tag=req.tag,
            pipeline_status=req.pipeline_status,
            email_verification_status=req.email_verification_status,
            campaign_id=req.campaign_id,
        )

    result = await db.execute(stmt)
    leads = list(result.scalars().all())
    csv_text = _generate_prospects_csv_text(leads)

    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"weblinx_prospects_{req.scope}_{len(leads)}_{today_str}.csv"

    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Count": str(len(leads)),
        },
    )


@router.get("/export")
async def export_leads_csv(
    scope: str = Query("all", description="'all' | 'filtered' | 'selected'"),
    lead_ids: str | None = Query(None, description="Comma-separated IDs for selected export"),
    status: str | None = Query(None),
    bad_only: bool = Query(False),
    interest: str | None = Query(None),
    q: str | None = Query(None),
    country: str | None = Query(None),
    city: str | None = Query(None),
    industry: str | None = Query(None),
    tag: str | None = Query(None),
    pipeline_status: str | None = Query(None),
    email_verification_status: str | None = Query(None),
    campaign_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """GET endpoint for exporting prospects to CSV with full filter and scope support."""
    parsed_ids = []
    if lead_ids:
        for part in lead_ids.split(","):
            part = part.strip()
            if part.isdigit():
                parsed_ids.append(int(part))

    if scope == "selected" and parsed_ids:
        stmt = _lead_query_with_campaigns().where(Lead.id.in_(parsed_ids)).order_by(Lead.id.desc())
    elif scope == "all":
        stmt = _lead_query_with_campaigns().order_by(Lead.id.desc())
    else:  # filtered
        intr = _optional_interest_for_stmt(interest)
        stmt = _build_leads_stmt(
            q=q,
            status=status,
            bad_only=bad_only,
            interest=intr,
            country=country,
            city=city,
            industry=industry,
            tag=tag,
            pipeline_status=pipeline_status,
            email_verification_status=email_verification_status,
            campaign_id=campaign_id,
        )

    result = await db.execute(stmt)
    leads = list(result.scalars().all())
    csv_text = _generate_prospects_csv_text(leads)

    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"weblinx_prospects_{scope}_{len(leads)}_{today_str}.csv"

    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Count": str(len(leads)),
        },
    )


@router.post("/bulk-delete")
async def bulk_delete_leads(
    body: LeadBulkDeleteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not body.lead_ids:
        return {"ok": True, "deleted": 0}
    all_campaign_ids: set[int] = set()
    deleted = 0
    for lead_id in body.lead_ids:
        res = await db.execute(select(Lead).where(Lead.id == lead_id))
        lead = res.scalar_one_or_none()
        if not lead:
            continue
        cl_res = await db.execute(
            select(CampaignLead.campaign_id).where(CampaignLead.lead_id == lead_id),
        )
        for (cid,) in cl_res.all():
            all_campaign_ids.add(cid)
        await db.execute(delete(EmailLog).where(EmailLog.lead_id == lead_id))
        await db.execute(delete(LeadReply).where(LeadReply.lead_id == lead_id))
        await db.delete(lead)
        deleted += 1

    if all_campaign_ids:
        log.info(
            "bulk_delete_leads: deleted %d lead(s); recalc (campaigns touched)",
            deleted,
        )
        await db.commit()
        from app.routers.schedule import enqueue_global_recalculate

        enqueue_global_recalculate(background_tasks)
    return {"ok": True, "deleted": deleted}


@router.post("/bulk-status")
async def bulk_update_lead_status(
    body: LeadBulkStatusRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not body.lead_ids:
        return {"ok": True, "updated": 0}
    target = normalize_enrollment_status(body.enrollment_status)
    changed = False
    updated = 0
    for lead_id in body.lead_ids:
        res = await db.execute(select(CampaignLead).where(CampaignLead.lead_id == lead_id))
        for cl in res.scalars().all():
            if cl.enrollment_status != target:
                cl.enrollment_status = target
                changed = True
                updated += 1
    await db.flush()
    if changed:
        await db.commit()
        from app.routers.schedule import enqueue_global_recalculate

        enqueue_global_recalculate(background_tasks)
    return {"ok": True, "updated": updated}


@router.post("/bulk-recover")
async def bulk_recover_leads(
    body: LeadBulkRecoverRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Recover many leads: one verification batch or one queue recalculation."""
    if not body.items:
        return {"recovered": 0, "errors": [], "recovered_ids": []}

    from app.app_settings import EMAIL_VERIFICATION_ENABLED, get_setting

    enabled = (await get_setting(db, EMAIL_VERIFICATION_ENABLED) or "false").lower() in (
        "true",
        "1",
        "yes",
    )
    verify = body.verify_email and enabled

    errors: list[dict] = []
    recovered_ids: list[int] = []

    for item in body.items:
        lead_id = item.lead_id
        res = await db.execute(
            _lead_query_with_campaigns().where(Lead.id == lead_id),
        )
        lead = res.scalar_one_or_none()
        if not lead:
            errors.append({"lead_id": lead_id, "detail": "not_found"})
            continue
        norm = item.email.strip().lower()
        if not norm:
            errors.append({"lead_id": lead_id, "detail": "empty_email"})
            continue
        dup = await db.execute(
            select(Lead.id).where(Lead.email == norm, Lead.id != lead_id),
        )
        if dup.scalar_one_or_none():
            errors.append({"lead_id": lead_id, "detail": "duplicate_email"})
            continue
        await _mutate_lead_recover(lead, norm, verify)
        await _after_lead_recovered(db, lead_id)
        recovered_ids.append(lead_id)

    await db.flush()
    await _finalize_lead_recovery(db, recovered_ids, verify, background_tasks)
    return {"recovered": len(recovered_ids), "errors": errors, "recovered_ids": recovered_ids}


@router.post("/recover-import")
async def import_recover_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    verify_emails: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """CSV with id + email columns (and optional extra columns). Uses same recovery rules as bulk-recover."""
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise HTTPException(400, "Empty CSV")

    header = [h.strip().lower() for h in rows[0]]
    id_idx = None
    email_idx = None
    if "id" in header or "lead_id" in header:
        try:
            id_idx = header.index("id") if "id" in header else header.index("lead_id")
        except ValueError:
            id_idx = None
        try:
            email_idx = header.index("email")
        except ValueError:
            email_idx = None
        data_rows = rows[1:]
    else:
        id_idx, email_idx = 0, 1
        data_rows = rows

    if id_idx is None or email_idx is None:
        raise HTTPException(400, "CSV must include id and email columns (header row or first two columns)")

    items: list[LeadBulkRecoverItem] = []
    for parts in data_rows:
        if len(parts) <= max(id_idx, email_idx):
            continue
        try:
            lid = int(str(parts[id_idx]).strip())
        except ValueError:
            continue
        em = str(parts[email_idx]).strip().strip('"')
        if lid and em:
            items.append(LeadBulkRecoverItem(lead_id=lid, email=em))

    if not items:
        raise HTTPException(400, "No valid id,email rows found")

    bulk_body = LeadBulkRecoverRequest(items=items, verify_email=verify_emails)
    return await bulk_recover_leads(bulk_body, background_tasks, db)


@router.post("", response_model=LeadResponse, status_code=201)
async def create_lead(data: LeadCreate, db: AsyncSession = Depends(get_db)):
    """Create a single prospect directly in the central prospect database with syntax validation."""
    raw_company = (data.company or "").strip()
    if not raw_company:
        raise HTTPException(status_code=400, detail="Company Name is required")

    raw_email = (data.email or "").strip()
    if not raw_email or "@" not in raw_email:
        raise HTTPException(status_code=400, detail="Valid email address is required")

    syntax_valid, normalized_email, local_part, domain, syntax_err = validate_syntax_and_normalize(raw_email)
    if not syntax_valid:
        raise HTTPException(status_code=400, detail=f"Invalid email syntax: {syntax_err}")

    existing = await db.execute(select(Lead).where(func.lower(Lead.email) == normalized_email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Prospect with email '{normalized_email}' already exists")

    # Fast offline dataset checks
    is_disp = is_disposable_domain(domain)
    is_role, role_cat = check_role_account(local_part)
    typo_suggest = check_typo_suggestion(domain)
    typo_info = {
        "has_typo_risk": bool(typo_suggest),
        "suggestion": typo_suggest,
    }
    role_info = {
        "is_role_account": is_role,
        "role_category": role_cat,
        "affects_deliverability": False,
    }

    if typo_info["has_typo_risk"]:
        initial_status = STATUS_RISKY
        reason = f"Possible domain typo for {typo_info['suggestion']}"
        confidence = "medium"
    elif is_disp:
        initial_status = STATUS_INVALID
        reason = f"Known disposable/temporary email domain ({domain})"
        confidence = "high"
    else:
        initial_status = STATUS_NOT_VERIFIED
        reason = "Prospect created; DNS & SMTP mailbox checks not yet performed"
        confidence = "none"

    verification_result = {
        "status": initial_status,
        "reason": reason,
        "confidence": confidence,
        "syntax": {
            "valid": True,
            "normalized": normalized_email,
            "normalized_email": normalized_email,
            "local_part": local_part,
            "domain": domain,
            "error": None,
        },
        "domain": {
            "name": domain,
            "dns_checked": False,
        },
        "disposable": {
            "is_disposable": is_disp,
            "provider": "offline_dataset" if is_disp else None,
        },
        "role_based": role_info,
        "typo": typo_info,
        "smtp": {
            "checked": False,
        },
        "verified_at": datetime.utcnow().isoformat(),
        "approved": False,
    }

    lead = Lead(
        email=normalized_email,
        name=data.name.strip(),
        company=data.company.strip(),
        phone=data.phone.strip(),
        website=data.website.strip(),
        industry=data.industry.strip(),
        city=data.city.strip(),
        country=data.country.strip(),
        lead_source=data.lead_source.strip(),
        notes=data.notes.strip(),
        pipeline_status=data.pipeline_status.strip() or "new",
        tags=data.tags or [],
        custom_data=data.custom_data or {},
        email_verification_status=initial_status,
        email_verification_result=verification_result,
    )
    try:
        db.add(lead)
        await db.commit()
        await db.refresh(lead)
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "uq_lead_email" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Prospect with email '{normalized_email}' already exists")
        raise
    return _lead_to_response(lead, set(), set(), set())


@router.post("/mark-replied")
async def mark_lead_replied(
    body: MarkReplied,
    db: AsyncSession = Depends(get_db),
):
    lead_id = body.lead_id
    campaign_id = body.campaign_id
    existing = await db.execute(
        select(LeadReply).where(
            LeadReply.lead_id == lead_id,
            LeadReply.campaign_id == campaign_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"ok": True}
    db.add(LeadReply(lead_id=lead_id, campaign_id=campaign_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Self-Hosted Email Verification & Prospect List Cleaning
# ---------------------------------------------------------------------------

class BulkVerificationManager:
    def __init__(self):
        self.is_running: bool = False
        self.cancel_requested: bool = False
        self.total: int = 0
        self.processed: int = 0
        self.valid: int = 0
        self.domain_validated: int = 0
        self.invalid: int = 0
        self.risky: int = 0
        self.catch_all: int = 0
        self.unknown: int = 0
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.current_email: Optional[str] = None
        self.lock = asyncio.Lock()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "total": self.total,
            "processed": self.processed,
            "valid": self.valid,
            "domain_validated": self.domain_validated,
            "invalid": self.invalid,
            "risky": self.risky,
            "catch_all": self.catch_all,
            "unknown": self.unknown,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "current_email": self.current_email,
        }

_bulk_verifier = BulkVerificationManager()


class LeadVerifySelectedRequest(BaseModel):
    lead_ids: List[int]
    check_smtp: bool = False


class LeadVerifyAllRequest(BaseModel):
    reverify: bool = False
    check_smtp: bool = False



class LeadApproveSelectedRequest(BaseModel):
    lead_ids: List[int]
    note: str = "Batch manual review approval"


@router.post("/approve-selected")
async def approve_selected_leads_endpoint(
    body: LeadApproveSelectedRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve selected contacts for campaign sending with audit tracking."""
    if not body.lead_ids:
        return {"ok": True, "approved_count": 0}

    leads_res = await db.execute(select(Lead).where(Lead.id.in_(body.lead_ids)))
    leads = leads_res.scalars().all()
    approved_count = 0
    for lead in leads:
        syntax_valid, _, _, _, _ = validate_syntax_and_normalize(lead.email or "")
        if not syntax_valid or lead.email_verification_status == "invalid":
            continue
        res_data = dict(lead.email_verification_result or {})
        res_data["approved"] = True
        res_data["approval_audit"] = {
            "approved_by": getattr(user, "email", "operator"),
            "approved_at": datetime.utcnow().isoformat(),
            "note": body.note,
        }
        lead.email_verification_result = res_data
        approved_count += 1

    await db.commit()
    return {"ok": True, "approved_count": approved_count}


class LeadManualOverrideRequest(BaseModel):
    status: str
    note: str = ""


async def _verify_lead_record(lead: Lead, check_smtp: bool = False) -> Dict[str, Any]:
    from app.verification_engine import verify_single_email
    res = await verify_single_email(lead.email, website=lead.website, check_smtp=check_smtp)
    lead.email_verification_status = res.status
    lead.email_verification_result = res.to_dict()
    if res.domain.get("detected_provider"):
        lead.provider = res.domain["detected_provider"]
    return res.to_dict()


async def _run_bulk_verification_background(lead_ids: List[int], check_smtp: bool = False):
    from app.database import AsyncSessionLocal
    global _bulk_verifier

    async with _bulk_verifier.lock:
        if _bulk_verifier.is_running:
            return
        _bulk_verifier.is_running = True
        _bulk_verifier.cancel_requested = False
        _bulk_verifier.total = len(lead_ids)
        _bulk_verifier.processed = 0
        _bulk_verifier.valid = 0
        _bulk_verifier.domain_validated = 0
        _bulk_verifier.invalid = 0
        _bulk_verifier.risky = 0
        _bulk_verifier.catch_all = 0
        _bulk_verifier.unknown = 0
        _bulk_verifier.started_at = datetime.utcnow().isoformat()
        _bulk_verifier.finished_at = None

    try:
        batch_size = 20
        for i in range(0, len(lead_ids), batch_size):
            if _bulk_verifier.cancel_requested:
                break
            batch = lead_ids[i:i + batch_size]
            async with AsyncSessionLocal() as session:
                leads_res = await session.execute(select(Lead).where(Lead.id.in_(batch)))
                leads = leads_res.scalars().all()
                for lead in leads:
                    if _bulk_verifier.cancel_requested:
                        break
                    _bulk_verifier.current_email = lead.email
                    res_dict = await _verify_lead_record(lead, check_smtp=check_smtp)
                    st = res_dict.get("status")
                    if st == "valid":
                        _bulk_verifier.valid += 1
                    elif st == "domain_validated":
                        _bulk_verifier.domain_validated += 1
                    elif st == "invalid":
                        _bulk_verifier.invalid += 1
                    elif st == "risky":
                        _bulk_verifier.risky += 1
                    elif st == "catch_all":
                        _bulk_verifier.catch_all += 1
                    else:
                        _bulk_verifier.unknown += 1
                    _bulk_verifier.processed += 1
                await session.commit()
            await asyncio.sleep(0.05)
    except Exception as e:
        log.error(f"Error in background bulk verification: {e}")
    finally:
        _bulk_verifier.is_running = False
        _bulk_verifier.finished_at = datetime.utcnow().isoformat()
        _bulk_verifier.current_email = None


@router.post("/{lead_id}/verify")
async def verify_single_lead_endpoint(
    lead_id: int,
    check_smtp: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Verify a single prospect email on-demand."""
    lead_res = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = lead_res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Prospect not found")

    result = await _verify_lead_record(lead, check_smtp=check_smtp)
    await db.commit()
    await db.refresh(lead)

    return {
        "ok": True,
        "lead_id": lead.id,
        "email": lead.email,
        "status": lead.email_verification_status,
        "result": result,
    }


@router.post("/verify-selected")
async def verify_selected_leads_endpoint(
    body: LeadVerifySelectedRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a specific batch of selected prospects."""
    if not body.lead_ids:
        return {"ok": True, "verified": 0, "counts": {}}

    leads_res = await db.execute(select(Lead).where(Lead.id.in_(body.lead_ids)))
    leads = leads_res.scalars().all()

    counts = {"valid": 0, "domain_validated": 0, "invalid": 0, "risky": 0, "catch_all": 0, "unknown": 0}
    for lead in leads:
        res = await _verify_lead_record(lead, check_smtp=body.check_smtp)
        st = res.get("status")
        counts[st] = counts.get(st, 0) + 1

    await db.commit()
    return {"ok": True, "total": len(leads), "counts": counts}


@router.post("/verify-all")
async def verify_all_leads_endpoint(
    body: Optional[LeadVerifyAllRequest] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Start background verification for all prospects (or all unverified prospects)."""
    global _bulk_verifier
    if _bulk_verifier.is_running:
        return {"ok": False, "message": "A verification job is already running", "job": _bulk_verifier.to_dict()}

    reverify = body.reverify if body else False
    check_smtp = body.check_smtp if body else False

    q = select(Lead.id)
    if not reverify:
        q = q.where(or_(Lead.email_verification_status.is_(None), Lead.email_verification_status == "not_verified"))

    res = await db.execute(q)
    target_ids = res.scalars().all()

    if not target_ids:
        return {"ok": True, "message": "No prospects need verification", "queued": 0}

    asyncio.create_task(_run_bulk_verification_background(target_ids, check_smtp=check_smtp))
    return {
        "ok": True,
        "message": f"Queued {len(target_ids)} prospects for verification in background",
        "queued": len(target_ids),
    }


@router.get("/verify-status")
async def get_verification_status_endpoint(db: AsyncSession = Depends(get_db)):
    """Return real-time verification job progress and overall database deliverability counts."""
    global _bulk_verifier

    counts_res = await db.execute(
        select(Lead.email_verification_status, func.count(Lead.id))
        .group_by(Lead.email_verification_status)
    )
    raw_counts = counts_res.all()

    status_breakdown = {
        "valid": 0,
        "domain_validated": 0,
        "invalid": 0,
        "risky": 0,
        "catch_all": 0,
        "unknown": 0,
        "unverified": 0,
    }
    total_leads = 0

    for st, cnt in raw_counts:
        total_leads += cnt
        if not st or st == "not_verified":
            status_breakdown["unverified"] += cnt
        elif st in status_breakdown:
            status_breakdown[st] += cnt
        else:
            status_breakdown["unknown"] += cnt

    return {
        "job": _bulk_verifier.to_dict(),
        "total_prospects": total_leads,
        "breakdown": status_breakdown,
    }


@router.post("/verify-cancel")
async def cancel_verification_endpoint():
    """Request cancellation of currently running bulk verification job."""
    global _bulk_verifier
    if _bulk_verifier.is_running:
        _bulk_verifier.cancel_requested = True
        return {"ok": True, "message": "Cancellation requested"}
    return {"ok": True, "message": "No verification job was running"}


@router.post("/{lead_id}/override-verification")
async def manual_override_verification_endpoint(
    lead_id: int,
    body: LeadManualOverrideRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually approve or override a lead's email verification status with an audit trail."""
    allowed_statuses = {"valid", "domain_validated", "invalid", "risky", "catch_all", "unknown", "not_verified"}
    target_status = body.status.strip().lower()
    if target_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(allowed_statuses)}")

    lead_res = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = lead_res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Prospect not found")

    old_status = lead.email_verification_status
    lead.email_verification_status = target_status

    res_data = dict(lead.email_verification_result or {})
    audit_entry = {
        "previous_status": old_status,
        "new_status": target_status,
        "note": body.note.strip(),
        "by_user": getattr(user, "email", "operator"),
        "overridden_at": datetime.utcnow().isoformat(),
    }
    res_data["override"] = audit_entry
    if target_status in ("valid", "domain_validated"):
        res_data["approved"] = True
    elif target_status == "invalid":
        res_data["approved"] = False

    lead.email_verification_result = res_data
    await db.commit()
    await db.refresh(lead)

    return {
        "ok": True,
        "lead_id": lead.id,
        "email": lead.email,
        "status": lead.email_verification_status,
        "override": audit_entry,
    }


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        _lead_query_with_campaigns().where(Lead.id == lead_id),
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    opened, clicked, replied = await _engagement_pair_sets(db, [lead_id])
    interactions = await _fetch_lead_interactions(db, lead_id)
    pairs = {(lead.id, cl.campaign_id) for cl in lead.campaign_leads}
    inbox_by_pair = await from_inbox_email_by_lead_campaign(db, pairs)
    return _lead_to_response(
        lead,
        opened,
        clicked,
        replied,
        interactions=interactions,
        inbox_by_pair=inbox_by_pair,
    )


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    if data.name is not None:
        lead.name = data.name.strip()
    if data.email is not None and data.email.strip():
        new_email = data.email.strip().lower()
        if new_email != (lead.email or "").lower():
            existing = await db.execute(select(Lead).where(Lead.email == new_email, Lead.id != lead_id))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"Prospect with email '{new_email}' already exists")
            lead.email = new_email
            lead.email_verification_status = None
            lead.email_verification_result = None
            lead.provider = None
            await _verify_lead_record(lead, check_smtp=False)
    if data.company is not None:
        lead.company = data.company.strip()
    if data.phone is not None:
        lead.phone = data.phone
    if data.website is not None:
        new_web = data.website.strip()
        if new_web != (lead.website or ""):
            lead.website = new_web
            if lead.email and lead.email_verification_status:
                await _verify_lead_record(lead, check_smtp=False)
    if data.industry is not None:
        lead.industry = data.industry
    if data.city is not None:
        lead.city = data.city
    if data.country is not None:
        lead.country = data.country
    if data.lead_source is not None:
        lead.lead_source = data.lead_source
    if data.notes is not None:
        lead.notes = data.notes
    if data.tags is not None:
        lead.tags = data.tags
    if data.custom_data is not None:
        lead.custom_data = data.custom_data
    enrollment_changed = False
    if data.pipeline_status is not None:
        lead.pipeline_status = data.pipeline_status.strip().lower()
        if lead.pipeline_status in ("interested", "meeting_scheduled", "proposal_sent", "won", "lost", "not_interested"):
            cl_res = await db.execute(select(CampaignLead).where(CampaignLead.lead_id == lead_id))
            for cl in cl_res.scalars().all():
                if lead.pipeline_status in ("interested", "not_interested"):
                    cl.interest_status = lead.pipeline_status
                await db.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id == cl.id))
            enrollment_changed = True
    if data.enrollment_status is not None:
        target = normalize_enrollment_status(data.enrollment_status)
        cl_res = await db.execute(select(CampaignLead).where(CampaignLead.lead_id == lead_id))
        for cl in cl_res.scalars().all():
            if cl.enrollment_status != target:
                cl.enrollment_status = target
                enrollment_changed = True
    await db.flush()

    if enrollment_changed:
        log.info(
            "Lead %s enrollment_status bulk-updated; triggering full recalculation",
            lead_id,
        )
        await db.commit()
        from app.routers.schedule import enqueue_global_recalculate

        enqueue_global_recalculate(background_tasks)

    result2 = await db.execute(
        _lead_query_with_campaigns().where(Lead.id == lead_id),
    )
    lead_loaded = result2.scalar_one()
    opened, clicked, replied = await _engagement_pair_sets(db, [lead_id])
    await db.flush()
    interactions = await _fetch_lead_interactions(db, lead_id)
    pairs = {(lead_loaded.id, cl.campaign_id) for cl in lead_loaded.campaign_leads}
    inbox_by_pair = await from_inbox_email_by_lead_campaign(db, pairs)
    return _lead_to_response(
        lead_loaded,
        opened,
        clicked,
        replied,
        interactions=interactions,
        inbox_by_pair=inbox_by_pair,
    )


@router.post("/{lead_id}/recover", response_model=LeadResponse)
async def recover_lead(
    lead_id: int,
    body: LeadRecoverRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        _lead_query_with_campaigns().where(Lead.id == lead_id),
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")

    norm = body.email.strip().lower()
    if not norm:
        raise HTTPException(400, "Email is required")

    dup = await db.execute(
        select(Lead.id).where(Lead.email == norm, Lead.id != lead_id),
    )
    if dup.scalar_one_or_none():
        raise HTTPException(409, "Another lead already uses this email address")

    from app.app_settings import EMAIL_VERIFICATION_ENABLED, get_setting

    enabled = (await get_setting(db, EMAIL_VERIFICATION_ENABLED) or "false").lower() in (
        "true",
        "1",
        "yes",
    )
    verify = body.verify_email and enabled

    await _mutate_lead_recover(lead, norm, verify)
    await _after_lead_recovered(db, lead_id)
    await db.flush()
    await _finalize_lead_recovery(db, [lead_id], verify, background_tasks)

    result3 = await db.execute(
        _lead_query_with_campaigns().where(Lead.id == lead_id),
    )
    lead_out = result3.scalar_one()
    opened, clicked, replied = await _engagement_pair_sets(db, [lead_id])
    interactions = await _fetch_lead_interactions(db, lead_id)
    await db.commit()
    pairs = {(lead_out.id, cl.campaign_id) for cl in lead_out.campaign_leads}
    inbox_by_pair = await from_inbox_email_by_lead_campaign(db, pairs)
    return _lead_to_response(
        lead_out, opened, clicked, replied,
        interactions=interactions,
        inbox_by_pair=inbox_by_pair,
    )


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    cl_res = await db.execute(
        select(CampaignLead.campaign_id).where(CampaignLead.lead_id == lead_id),
    )
    campaign_ids = [r[0] for r in cl_res.all()]
    await db.execute(delete(EmailLog).where(EmailLog.lead_id == lead_id))
    await db.execute(delete(LeadReply).where(LeadReply.lead_id == lead_id))
    await db.delete(lead)

    if campaign_ids:
        log.info(
            "Lead %s deleted (campaigns=%s); triggering full recalculation",
            lead_id,
            campaign_ids,
        )
        await db.commit()
        from app.routers.schedule import enqueue_global_recalculate

        enqueue_global_recalculate(background_tasks)
    return {"ok": True}


@router.get("/{lead_id}/history")
async def get_lead_history(lead_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmailLog, Campaign.name)
        .join(Campaign, EmailLog.campaign_id == Campaign.id)
        .where(EmailLog.lead_id == lead_id)
        .order_by(EmailLog.sent_at.desc()),
    )
    rows = result.all()
    return [
        {
            "campaign_id": log.campaign_id,
            "campaign_name": name,
            "sequence_index": log.sequence_index,
            "sent_at": log.sent_at.isoformat(),
            "subject": log.subject,
        }
        for log, name in rows
    ]


@router.get("/{lead_id}/replies")
async def get_lead_replies(lead_id: int, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(Lead.id).where(Lead.id == lead_id))
    if not exists.scalar_one_or_none():
        raise HTTPException(404, "Lead not found")
    result = await db.execute(
        select(LeadReply, Campaign.name)
        .join(Campaign, LeadReply.campaign_id == Campaign.id)
        .where(LeadReply.lead_id == lead_id)
        .order_by(LeadReply.replied_at.desc()),
    )
    return [
        {
            "campaign_id": lr.campaign_id,
            "campaign_name": name,
            "replied_at": lr.replied_at.isoformat(),
        }
        for lr, name in result.all()
    ]


IMPORT_ALIAS_MAP: dict[str, list[str]] = {
    "email": [
        "email", "email address", "work email", "e-mail", "mail", "contact email",
        "primary email", "email_address", "business email", "electronic mail"
    ],
    "company": [
        "company", "company name", "agency name", "agency", "business name",
        "business", "organization", "account", "account name", "firm", "studio",
        "company_name", "agency_name", "business_name", "shop"
    ],
    "name": [
        "name", "contact name", "contact", "founder", "full name", "owner",
        "decision maker", "person", "lead name", "principal", "ceo", "contact_name",
        "full_name", "lead_name", "prospect name", "agent"
    ],
    "first_name": ["first name", "firstname", "first", "given name", "first_name"],
    "last_name": ["last name", "lastname", "last", "surname", "family name", "last_name"],
    "phone": [
        "phone", "phone number", "direct phone", "office phone", "mobile",
        "telephone", "cell", "tel", "contact number", "phone_number", "mobile number",
        "direct number", "phone_no", "cell phone"
    ],
    "website": [
        "website", "site", "url", "domain", "web", "website url", "web address",
        "company website", "homepage", "website_url", "link"
    ],
    "city": ["city", "location", "town", "metro", "municipality", "market"],
    "state": ["state", "region", "province", "territory", "state / region", "state/province", "st"],
    "country": ["country", "nation", "country code", "geo"],
    "industry": [
        "industry", "sector", "vertical", "niche", "category", "business type",
        "specialty", "agency focus", "market vertical"
    ],
    "lead_source": [
        "source", "lead source", "channel", "origin", "campaign source",
        "acquisition channel", "lead_source", "source channel"
    ],
    "tags": ["tags", "tag", "keywords", "labels", "tag list", "segments"],
    "notes": ["notes", "note", "comment", "comments", "description", "bio", "details", "remarks"]
}


def _parse_uploaded_spreadsheet(content: bytes, filename: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse uploaded CSV or Excel file, ensuring proper encoding and rejecting empty/header-only files."""
    if not content or len(content.strip()) == 0:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty (0 bytes). Please upload a valid CSV or Excel spreadsheet."
        )

    ext = (filename or "upload.csv").lower().split(".")[-1]
    rows_data: list[dict[str, str]] = []
    headers: list[str] = []

    if ext in ("xlsx", "xls"):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            sheet = wb.active
            if sheet is None:
                raise HTTPException(status_code=400, detail="Excel workbook has no active sheet.")
            all_rows = list(sheet.iter_rows(values_only=True))
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=400, detail=f"Failed to parse Excel file: {str(e)}")

        if not all_rows:
            raise HTTPException(status_code=400, detail="Excel file is completely empty. Please upload a spreadsheet with headers and prospect records.")

        raw_header_row = [str(h or "").strip() for h in all_rows[0]]
        headers = [h for h in raw_header_row if h]
        if not headers:
            raise HTTPException(status_code=400, detail="Excel file has no valid column headers.")

        for row_vals in all_rows[1:]:
            row_dict = {}
            for col_idx, h in enumerate(raw_header_row):
                if not h:
                    continue
                v = row_vals[col_idx] if col_idx < len(row_vals) else None
                row_dict[h] = "" if v is None else str(v).strip()
            if any(row_dict.values()):
                rows_data.append(row_dict)
    else:
        # CSV parsing with encoding resilience
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Unable to decode CSV file: {str(e)}")

        reader = csv.reader(io.StringIO(text))
        all_rows = list(reader)
        if not all_rows:
            raise HTTPException(status_code=400, detail="CSV file is completely empty. Please upload a spreadsheet with headers and prospect records.")

        raw_header_row = [h.strip() for h in all_rows[0]]
        headers = [h for h in raw_header_row if h]
        if not headers:
            raise HTTPException(status_code=400, detail="CSV file has no valid column headers.")

        for row_vals in all_rows[1:]:
            row_dict = {}
            for col_idx, h in enumerate(raw_header_row):
                if not h:
                    continue
                v = row_vals[col_idx] if col_idx < len(row_vals) else ""
                row_dict[h] = str(v).strip()
            if any(row_dict.values()):
                rows_data.append(row_dict)

    if not rows_data:
        hdr_preview = ", ".join(headers[:5])
        raise HTTPException(
            status_code=400,
            detail=f"The file contains column headers ({hdr_preview}) but has no prospect records (0 data rows). Please upload a file containing at least 1 prospect record."
        )

    return headers, rows_data


def _detect_column_mappings(headers: list[str], user_mapping: Optional[dict[str, str]] = None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    user_mapping = user_mapping or {}

    for field, aliases in IMPORT_ALIAS_MAP.items():
        if user_mapping.get(field) and user_mapping[field] in headers:
            mapping[field] = user_mapping[field]
            continue
        matched = None
        for alias in aliases:
            for h in headers:
                if h.strip().lower() == alias:
                    matched = h
                    break
            if matched:
                break
        if not matched:
            for alias in aliases:
                for h in headers:
                    hl = h.strip().lower()
                    if alias in hl:
                        matched = h
                        break
                if matched:
                    break
        if matched:
            mapping[field] = matched

    return mapping


@router.post("/import-preview")
async def import_preview(
    file: UploadFile = File(...),
    column_mapping_json: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Analyze uploaded spreadsheet, auto-detect column mappings, validate rows, and provide a pre-import preview with data health statistics."""
    content = await file.read()
    filename = file.filename or "upload.csv"
    headers, rows_data = _parse_uploaded_spreadsheet(content, filename)

    user_mapping = {}
    if column_mapping_json:
        try:
            user_mapping = json.loads(column_mapping_json)
        except Exception:
            user_mapping = {}

    detected_mapping = _detect_column_mappings(headers, user_mapping)
    email_col = detected_mapping.get("email")

    # Scoped duplicate lookup instead of loading all leads from DB
    candidate_emails = set()
    for r in rows_data:
        em = (r.get(email_col) or "").strip() if email_col else ""
        if em and "@" in em:
            candidate_emails.add(em.lower())

    existing_emails = set()
    if candidate_emails:
        c_list = list(candidate_emails)
        for i in range(0, len(c_list), 500):
            chunk = c_list[i:i + 500]
            res = await db.execute(select(func.lower(Lead.email)).where(func.lower(Lead.email).in_(chunk)))
            for row in res.scalars().all():
                if row:
                    existing_emails.add(row.lower())

    seen_file_emails = set()
    duplicate_count = 0
    invalid_email_count = 0
    missing_email_count = 0
    valid_count = 0

    preview_rows = []
    for idx, r in enumerate(rows_data):
        raw_email = (r.get(email_col) or "").strip() if email_col else ""
        row_status = "ready"
        status_reason = "Ready to import"

        if not raw_email:
            missing_email_count += 1
            row_status = "missing_email"
            status_reason = "Missing email address"
        else:
            syntax_valid, norm_email, _, _, _ = validate_syntax_and_normalize(raw_email)
            if not syntax_valid:
                invalid_email_count += 1
                row_status = "invalid_format"
                status_reason = "Invalid email format"
            elif norm_email.lower() in existing_emails or norm_email.lower() in seen_file_emails:
                duplicate_count += 1
                row_status = "duplicate"
                status_reason = "Already in database or duplicate in file"
            else:
                valid_count += 1
                seen_file_emails.add(norm_email.lower())

        if idx < 10:
            name_val = ""
            if detected_mapping.get("name") and r.get(detected_mapping["name"]):
                name_val = r[detected_mapping["name"]]
            elif detected_mapping.get("first_name") and r.get(detected_mapping["first_name"]):
                fn = r[detected_mapping["first_name"]]
                ln = r.get(detected_mapping.get("last_name", ""), "") if detected_mapping.get("last_name") else ""
                name_val = f"{fn} {ln}".strip()

            preview_rows.append({
                "row_index": idx + 1,
                "email": raw_email,
                "name": name_val,
                "company": r.get(detected_mapping.get("company", ""), ""),
                "phone": r.get(detected_mapping.get("phone", ""), ""),
                "website": r.get(detected_mapping.get("website", ""), ""),
                "city": r.get(detected_mapping.get("city", ""), ""),
                "state": r.get(detected_mapping.get("state", ""), ""),
                "industry": r.get(detected_mapping.get("industry", ""), ""),
                "status": row_status,
                "status_reason": status_reason,
            })

    return {
        "ok": True,
        "filename": filename,
        "total_rows": len(rows_data),
        "headers": headers,
        "detected_mapping": detected_mapping,
        "valid_count": valid_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_email_count,
        "missing_email_count": missing_email_count,
        "estimated_import": valid_count,
        "preview_rows": preview_rows,
    }


@router.post("/import")
async def import_prospects(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    column_mapping_json: Optional[str] = Query(None),
    campaign_id: Optional[int] = Form(None),
    campaign_id_query: Optional[int] = Query(None, alias="campaign_id"),
    duplicate_action: str = Form("skip"),
    fill_missing: Optional[bool] = Form(None),
    tags: Optional[str] = Form(None),
    tags_json: Optional[str] = Query(None),
    auto_verify: bool = Query(True),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Import prospects from CSV or Excel (.xlsx) file with column mapping, duplicate detection, and optional auto-verification."""
    content = await file.read()
    filename = file.filename or "upload.csv"
    headers, rows_data = _parse_uploaded_spreadsheet(content, filename)

    mapping_raw = column_mapping or column_mapping_json or "{}"
    user_mapping = {}
    try:
        user_mapping = json.loads(mapping_raw)
    except Exception:
        user_mapping = {}

    mapping = _detect_column_mappings(headers, user_mapping)
    email_col = mapping.get("email")
    if not email_col:
        raise HTTPException(status_code=400, detail="Could not detect email column. Please provide a column mapping for 'email'.")

    # Resolve campaign_id
    effective_campaign_id = campaign_id if campaign_id is not None else campaign_id_query

    # Resolve tags
    applied_tags: list[str] = []
    tags_input = tags or tags_json or "[]"
    try:
        loaded = json.loads(tags_input)
        if isinstance(loaded, list):
            applied_tags = [str(t).strip() for t in loaded if t]
    except Exception:
        if tags_input and tags_input != "[]":
            applied_tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    # Collect candidate emails for scoped batch lookup (avoids loading entire DB into memory)
    candidate_emails = set()
    for r in rows_data:
        raw_em = (r.get(email_col) or "").strip().lower()
        if raw_em and "@" in raw_em:
            candidate_emails.add(raw_em)

    existing_leads_map: dict[str, Lead] = {}
    if candidate_emails:
        c_list = list(candidate_emails)
        for i in range(0, len(c_list), 500):
            chunk = c_list[i:i + 500]
            res = await db.execute(select(Lead).where(func.lower(Lead.email).in_(chunk)))
            for l in res.scalars().all():
                if l.email:
                    existing_leads_map[l.email.lower()] = l

    name_col = mapping.get("name")
    first_name_col = mapping.get("first_name")
    last_name_col = mapping.get("last_name")
    company_col = mapping.get("company")
    phone_col = mapping.get("phone")
    website_col = mapping.get("website")
    city_col = mapping.get("city")
    state_col = mapping.get("state")
    country_col = mapping.get("country")
    industry_col = mapping.get("industry")
    source_col = mapping.get("lead_source")
    tags_col = mapping.get("tags")
    notes_col = mapping.get("notes")

    total_rows = len(rows_data)
    added = 0
    skipped_duplicates = 0
    updated = 0
    invalid = 0
    failed = 0

    details: dict[str, list[dict[str, Any]]] = {
        "skipped": [],
        "updated": [],
        "conflicts": [],
        "invalid": [],
        "failed": [],
    }

    should_fill_missing = (fill_missing is True) or (duplicate_action == "update")
    seen_in_batch: set[str] = set()
    new_leads_to_add: list[Lead] = []
    existing_leads_to_enroll: list[Lead] = []

    for idx, r in enumerate(rows_data):
        row_num = idx + 1
        raw_email = (r.get(email_col) or "").strip()
        if not raw_email or "@" not in raw_email or "." not in raw_email.split("@")[-1]:
            invalid += 1
            details["invalid"].append({
                "row": row_num,
                "email": raw_email or "(blank)",
                "reason": "Missing or invalid email format",
            })
            continue

        syntax_valid, normalized_email, local_part, domain, syntax_err = validate_syntax_and_normalize(raw_email)
        if not syntax_valid:
            invalid += 1
            details["invalid"].append({
                "row": row_num,
                "email": raw_email,
                "reason": syntax_err or "Invalid email syntax",
            })
            continue

        # Extract values
        company_val = (r.get(company_col) or "").strip() if company_col else ""
        phone_val = (r.get(phone_col) or "").strip() if phone_col else ""
        website_val = (r.get(website_col) or "").strip() if website_col else ""
        city_val = (r.get(city_col) or "").strip() if city_col else ""
        state_val = (r.get(state_col) or "").strip() if state_col else ""
        country_val = (r.get(country_col) or "").strip() if country_col else ""
        industry_val = (r.get(industry_col) or "").strip() if industry_col else ""
        source_val = (r.get(source_col) or "").strip() if source_col else ""
        notes_val = (r.get(notes_col) or "").strip() if notes_col else ""

        full_name = ""
        if name_col and r.get(name_col):
            full_name = str(r[name_col]).strip()
        elif first_name_col and r.get(first_name_col):
            fn = str(r[first_name_col]).strip()
            ln = str(r.get(last_name_col) or "").strip() if last_name_col else ""
            full_name = f"{fn} {ln}".strip()

        # Combine tags
        row_tags = list(applied_tags)
        if tags_col and r.get(tags_col):
            raw_t = str(r[tags_col])
            for t in raw_t.replace(";", ",").split(","):
                ts = t.strip()
                if ts and ts not in row_tags:
                    row_tags.append(ts)

        # Extra custom data
        standard_cols = {
            email_col, name_col, first_name_col, last_name_col, company_col,
            phone_col, website_col, city_col, state_col, country_col,
            industry_col, source_col, tags_col, notes_col
        }
        custom_fields: dict[str, Any] = {}
        if state_val:
            custom_fields["state"] = state_val
        for k, v in r.items():
            if k not in standard_cols and v:
                custom_fields[k] = v

        norm_key = normalized_email.lower()

        # 1. Check duplicate within the same batch file
        if norm_key in seen_in_batch:
            skipped_duplicates += 1
            details["skipped"].append({
                "row": row_num,
                "email": normalized_email,
                "name": full_name,
                "company": company_val,
                "reason": "Duplicate row within spreadsheet",
            })
            continue

        seen_in_batch.add(norm_key)

        # 2. Check existing prospect in database
        if norm_key in existing_leads_map:
            existing_lead = existing_leads_map[norm_key]
            if should_fill_missing:
                filled_fields = []
                row_conflicts = []

                # Company: fill if missing, never overwrite existing!
                if company_val:
                    if not existing_lead.company:
                        existing_lead.company = company_val
                        filled_fields.append("company")
                    elif existing_lead.company.strip() != company_val.strip():
                        row_conflicts.append({
                            "field": "company",
                            "existing": existing_lead.company,
                            "imported": company_val,
                        })

                # Name: fill if missing, never overwrite existing!
                if full_name:
                    if not existing_lead.name:
                        existing_lead.name = full_name
                        filled_fields.append("name")
                    elif existing_lead.name.strip() != full_name.strip():
                        row_conflicts.append({
                            "field": "name",
                            "existing": existing_lead.name,
                            "imported": full_name,
                        })

                # Phone: fill if missing, never overwrite existing!
                if phone_val:
                    if not existing_lead.phone:
                        existing_lead.phone = phone_val
                        filled_fields.append("phone")
                    elif existing_lead.phone.strip() != phone_val.strip():
                        row_conflicts.append({
                            "field": "phone",
                            "existing": existing_lead.phone,
                            "imported": phone_val,
                        })

                # Website: fill if missing, never overwrite existing!
                if website_val:
                    if not existing_lead.website:
                        existing_lead.website = website_val
                        filled_fields.append("website")
                    elif existing_lead.website.strip() != website_val.strip():
                        row_conflicts.append({
                            "field": "website",
                            "existing": existing_lead.website,
                            "imported": website_val,
                        })

                if city_val and not existing_lead.city:
                    existing_lead.city = city_val
                    filled_fields.append("city")

                if country_val and not existing_lead.country:
                    existing_lead.country = country_val
                    filled_fields.append("country")

                if industry_val and not existing_lead.industry:
                    existing_lead.industry = industry_val
                    filled_fields.append("industry")

                if notes_val:
                    if not existing_lead.notes:
                        existing_lead.notes = notes_val
                        filled_fields.append("notes")
                    elif notes_val not in existing_lead.notes:
                        existing_lead.notes = f"{existing_lead.notes}\n{notes_val}"
                        filled_fields.append("notes (appended)")

                if row_tags:
                    curr_tags = list(existing_lead.tags or [])
                    new_t = [t for t in row_tags if t not in curr_tags]
                    if new_t:
                        existing_lead.tags = curr_tags + new_t
                        filled_fields.append("tags")

                if custom_fields:
                    curr_cd = dict(existing_lead.custom_data or {})
                    new_cd = {k: v for k, v in custom_fields.items() if k not in curr_cd}
                    if new_cd:
                        curr_cd.update(new_cd)
                        existing_lead.custom_data = curr_cd
                        filled_fields.append("custom_data")

                if row_conflicts:
                    for c in row_conflicts:
                        details["conflicts"].append({"row": row_num, "email": normalized_email, **c})

                if filled_fields:
                    updated += 1
                    details["updated"].append({
                        "row": row_num,
                        "email": normalized_email,
                        "name": existing_lead.name or full_name,
                        "company": existing_lead.company or company_val,
                        "fields_filled": filled_fields,
                    })
                else:
                    skipped_duplicates += 1
                    details["skipped"].append({
                        "row": row_num,
                        "email": normalized_email,
                        "name": existing_lead.name or full_name,
                        "company": existing_lead.company or company_val,
                        "reason": "Existing prospect already complete",
                    })
            else:
                # Default: skip existing
                skipped_duplicates += 1
                details["skipped"].append({
                    "row": row_num,
                    "email": normalized_email,
                    "name": existing_lead.name or full_name,
                    "company": existing_lead.company or company_val,
                    "reason": "Existing prospect skipped",
                })

            if effective_campaign_id:
                existing_leads_to_enroll.append(existing_lead)
            continue

        # 3. New prospect
        is_disp = is_disposable_domain(domain)
        is_role, role_cat = check_role_account(local_part)
        typo_suggest = check_typo_suggestion(domain)
        typo_info = {"has_typo_risk": bool(typo_suggest), "suggestion": typo_suggest}
        role_info = {"is_role_account": is_role, "role_category": role_cat, "affects_deliverability": False}

        if typo_info["has_typo_risk"]:
            initial_status = STATUS_RISKY
            reason = f"Possible domain typo for {typo_info['suggestion']}"
            confidence = "medium"
        elif is_disp:
            initial_status = STATUS_INVALID
            reason = f"Known disposable/temporary email domain ({domain})"
            confidence = "high"
        else:
            initial_status = STATUS_NOT_VERIFIED
            reason = "Imported; DNS & SMTP mailbox checks pending"
            confidence = "none"

        verification_result = {
            "status": initial_status,
            "reason": reason,
            "confidence": confidence,
            "syntax": {"valid": True, "normalized": normalized_email, "local_part": local_part, "domain": domain},
            "domain": {"name": domain, "dns_checked": False},
            "disposable": {"is_disposable": is_disp, "provider": "offline_dataset" if is_disp else None},
            "role_based": role_info,
            "typo": typo_info,
            "smtp": {"checked": False},
            "verified_at": datetime.utcnow().isoformat(),
            "approved": False,
        }

        lead = Lead(
            email=normalized_email,
            name=full_name,
            company=company_val,
            phone=phone_val,
            website=website_val,
            industry=industry_val,
            city=city_val,
            country=country_val,
            lead_source=source_val or "Cold Outreach",
            notes=notes_val,
            pipeline_status="new",
            tags=row_tags,
            custom_data=custom_fields,
            email_verification_status=initial_status,
            email_verification_result=verification_result,
        )
        new_leads_to_add.append(lead)
        existing_leads_map[norm_key] = lead
        added += 1

    # Database writes with atomic transaction safety
    if new_leads_to_add:
        try:
            db.add_all(new_leads_to_add)
            await db.flush()
        except Exception as exc:
            log.warning("Batch flush hit exception, saving individually to isolate errors: %s", exc)
            await db.rollback()
            added = 0
            for nl in new_leads_to_add:
                try:
                    db.add(nl)
                    await db.flush()
                    added += 1
                except Exception as inner_e:
                    log.error("Failed to insert lead %s: %s", nl.email, inner_e)
                    failed += 1
                    details["failed"].append({"email": nl.email, "error": str(inner_e)})

    # Campaign enrollment
    if effective_campaign_id:
        camp_row = await db.execute(select(Campaign).where(Campaign.id == effective_campaign_id))
        campaign = camp_row.scalar_one_or_none()
        if campaign:
            all_enroll_candidates = [nl for nl in new_leads_to_add if nl.id and nl.email_verification_status != STATUS_INVALID] + [el for el in existing_leads_to_enroll if el.id]
            if all_enroll_candidates:
                cand_ids = [l.id for l in all_enroll_candidates]
                existing_enr_res = await db.execute(
                    select(CampaignLead.lead_id).where(
                        CampaignLead.campaign_id == effective_campaign_id,
                        CampaignLead.lead_id.in_(cand_ids)
                    )
                )
                already_enrolled_lids = set(existing_enr_res.scalars().all())

                new_cls = []
                for l in all_enroll_candidates:
                    if l.id in already_enrolled_lids:
                        continue
                    if (l.status or "").lower() in ("bounced", "unsubscribed", "invalid"):
                        continue
                    cl = CampaignLead(
                        campaign_id=effective_campaign_id,
                        lead_id=l.id,
                        enrollment_status="active",
                    )
                    new_cls.append(cl)
                    already_enrolled_lids.add(l.id)

                if new_cls:
                    db.add_all(new_cls)
                    await db.flush()
                    from app.routers.schedule import enqueue_global_recalculate
                    enqueue_global_recalculate(background_tasks)

    if auto_verify:
        verify_targets = [nl.id for nl in new_leads_to_add if nl.id and nl.email_verification_status != STATUS_INVALID]
        if verify_targets:
            asyncio.create_task(_run_bulk_verification_background(verify_targets, check_smtp=False))

    # Record history
    history = ImportHistory(
        filename=filename,
        total_rows=total_rows,
        imported_count=added,
        duplicate_count=skipped_duplicates + updated,
        invalid_count=invalid,
    )
    db.add(history)
    await db.commit()

    return {
        "ok": True,
        "filename": filename,
        "total_rows": total_rows,
        "imported": added,
        "added": added,
        "skipped_duplicates": skipped_duplicates,
        "duplicates_skipped": skipped_duplicates,
        "updated": updated,
        "duplicates_updated": updated,
        "invalid": invalid,
        "failed": failed,
        "conflicts_count": len(details["conflicts"]),
        "details": {
            "skipped": details["skipped"][:200],
            "updated": details["updated"][:200],
            "conflicts": details["conflicts"][:200],
            "invalid": details["invalid"][:200],
            "failed": details["failed"][:200],
        },
        "auto_verify_queued": auto_verify and bool(new_leads_to_add),
    }


@router.post("/bulk-campaign-assign", response_model=LeadBulkAssignResponse)
@router.post("/bulk-assign-campaign", response_model=LeadBulkAssignResponse)
async def bulk_assign_to_campaign(
    body: LeadBulkAssignCampaignRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Assign selected prospects to a campaign with safeguards, duplicate prevention, and verification checks."""
    from app.campaign_lead_status import VERIFICATION_NEEDS_REVIEW
    from app.queue_logic import reserve_slots_for_new_leads_bulk
    from app.routers.suppression import is_email_or_domain_suppressed
    from app.verification_engine import validate_syntax_and_normalize

    camp_res = await db.execute(select(Campaign).where(Campaign.id == body.campaign_id))
    camp = camp_res.scalar_one_or_none()
    if not camp:
        raise HTTPException(status_code=404, detail="Target campaign not found")

    is_paused = bool(camp.paused)

    # Resolve lead_ids (either explicit list or select_all_filtered)
    lead_ids = list(body.lead_ids or [])
    if body.select_all_filtered and body.filters:
        stmt = _build_leads_stmt(**body.filters)
        f_res = await db.execute(stmt)
        lead_ids = [l.id for l in f_res.scalars().all()]

    # Deduplicate while preserving order
    unique_lids = list(dict.fromkeys(lead_ids))
    if not unique_lids:
        return {
            "ok": True,
            "assigned": 0,
            "already_enrolled": 0,
            "blocked": 0,
            "summary": BulkAssignSummary(
                total_selected=0,
                eligible=0,
                needs_review=0,
                blocked=0,
                already_enrolled=0,
                other_active_campaigns=0,
                other_active_details=[],
                blocked_details=[],
                campaign_id=camp.id,
                campaign_name=camp.name,
                campaign_paused=is_paused,
            ),
        }

    # Fetch leads with campaign_leads loaded
    leads_res = await db.execute(
        select(Lead)
        .options(selectinload(Lead.campaign_leads).selectinload(CampaignLead.campaign))
        .where(Lead.id.in_(unique_lids))
    )
    leads_map = {l.id: l for l in leads_res.scalars().all()}

    total_selected = len(unique_lids)
    eligible_count = 0
    needs_review_count = 0
    blocked_count = 0
    already_enrolled_count = 0
    other_active_count = 0
    other_active_details: list[dict] = []
    blocked_details: list[dict] = []

    leads_to_enroll: list[tuple[Lead, str, bool, bool]] = []  # (lead, status, sending_paused, is_schedulable)

    for lid in unique_lids:
        lead = leads_map.get(lid)
        if not lead:
            continue

        email = (lead.email or "").strip().lower()

        # 1. Check if already enrolled in THIS campaign
        is_already_enrolled = any(cl.campaign_id == camp.id for cl in lead.campaign_leads)
        if is_already_enrolled:
            already_enrolled_count += 1
            continue

        # 2. Check if enrolled in OTHER ACTIVE campaigns
        other_active_camps = [
            cl.campaign.name
            for cl in lead.campaign_leads
            if cl.campaign_id != camp.id
            and cl.campaign
            and not cl.campaign.paused
            and cl.enrollment_status in ("active", "contacted")
        ]
        if other_active_camps:
            other_active_count += 1
            other_active_details.append(
                {
                    "lead_id": lead.id,
                    "email": email,
                    "name": lead.name or "",
                    "campaigns": other_active_camps,
                }
            )

        # 3. Check syntax, deliverability, suppression, and review policies
        is_blocked = False
        blocked_reason = ""

        # Syntax check
        syntax_valid, _, _, _, _ = validate_syntax_and_normalize(email)
        if not syntax_valid:
            is_blocked = True
            blocked_reason = "Invalid email syntax"
        elif lead.email_verification_status == "invalid":
            is_blocked = True
            blocked_reason = "Invalid verification status"
        elif (lead.status or "").lower() in ("bounced", "unsubscribed", "invalid"):
            is_blocked = True
            blocked_reason = f"Contact is {lead.status}"
        elif await is_email_or_domain_suppressed(db, email):
            is_blocked = True
            blocked_reason = "Email or domain is on suppression list"

        if is_blocked:
            blocked_count += 1
            blocked_details.append({"lead_id": lead.id, "email": email, "reason": blocked_reason})
            continue

        # Check review requirement
        ev = (lead.email_verification_status or "").lower()
        ev_res = getattr(lead, "email_verification_result", None) or {}
        is_approved = bool(ev_res.get("approved") or ev_res.get("review_approved"))

        if ev in ("valid", "domain_validated") or is_approved:
            eligible_count += 1
            leads_to_enroll.append((lead, "active", False, True))
        elif ev in VERIFICATION_NEEDS_REVIEW or not ev:
            needs_review_count += 1
            leads_to_enroll.append((lead, "pending_review", True, False))
        else:
            eligible_count += 1
            leads_to_enroll.append((lead, "active", False, True))

    summary = BulkAssignSummary(
        total_selected=total_selected,
        eligible=eligible_count,
        needs_review=needs_review_count,
        blocked=blocked_count,
        already_enrolled=already_enrolled_count,
        other_active_campaigns=other_active_count,
        other_active_details=other_active_details[:50],
        blocked_details=blocked_details[:50],
        campaign_id=camp.id,
        campaign_name=camp.name,
        campaign_paused=is_paused,
    )

    if body.dry_run:
        return {
            "ok": True,
            "assigned": 0,
            "already_enrolled": already_enrolled_count,
            "blocked": blocked_count,
            "summary": summary,
        }

    # Execute enrollment
    assigned_count = 0
    new_schedulable_cl_ids: list[int] = []

    # Check if custom sequence mode applies
    has_personalized = False
    from app.models import Sequence
    seq_res = await db.execute(select(Sequence).where(Sequence.campaign_id == camp.id))
    for seq in seq_res.scalars().all():
        if getattr(seq, "has_personalized_variants", False):
            has_personalized = True
            break

    campaign_mode = getattr(camp, "custom_sequence_mode", "wait_for_all") or "wait_for_all"

    # Set of leads to skip if skip_other_active is True
    other_active_lids = {d["lead_id"] for d in other_active_details}

    for lead, initial_status, is_sending_paused, is_schedulable in leads_to_enroll:
        if body.skip_other_active and lead.id in other_active_lids:
            continue

        enr_status = initial_status
        if enr_status == "active" and has_personalized and campaign_mode != "asap":
            enr_status = "needs_custom_email"
            is_schedulable = False

        cl = CampaignLead(
            campaign_id=camp.id,
            lead_id=lead.id,
            enrollment_status=enr_status,
            sending_paused=is_sending_paused,
        )
        db.add(cl)
        await db.flush()
        assigned_count += 1

        if is_schedulable and not is_sending_paused:
            new_schedulable_cl_ids.append(cl.id)

    await db.commit()

    # Slot reservation: ONLY if the campaign is active (not paused!)
    if not is_paused and new_schedulable_cl_ids:
        try:
            await reserve_slots_for_new_leads_bulk(db, new_schedulable_cl_ids, camp.id)
            await db.commit()
            from app.routers.schedule import enqueue_global_recalculate
            enqueue_global_recalculate(background_tasks)
        except Exception as exc:
            log.warning("Could not reserve slots for bulk assigned leads: %s", exc)

    log.info("bulk_assign_to_campaign: assigned %d leads to campaign %s (paused=%s)", assigned_count, camp.id, is_paused)

    return {
        "ok": True,
        "assigned": assigned_count,
        "already_enrolled": already_enrolled_count,
        "blocked": blocked_count,
        "summary": summary,
    }


@router.post("/bulk-pipeline-status")
async def bulk_update_pipeline_status(
    body: LeadBulkPipelineStatusRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Bulk update sales pipeline status for selected prospects."""
    if not body.lead_ids:
        return {"ok": True, "updated": 0}

    target = body.pipeline_status.strip().lower()
    updated = 0
    stop_sending = target in ("interested", "meeting_scheduled", "proposal_sent", "won", "lost", "not_interested")

    for lid in body.lead_ids:
        lead_res = await db.execute(select(Lead).where(Lead.id == lid))
        lead = lead_res.scalar_one_or_none()
        if not lead:
            continue
        lead.pipeline_status = target
        updated += 1

        if stop_sending:
            # Stop follow-ups for this lead across their enrollments
            cls_res = await db.execute(select(CampaignLead).where(CampaignLead.lead_id == lid))
            for cl in cls_res.scalars().all():
                if target in ("interested", "not_interested"):
                    cl.interest_status = target
                # delete pending slots
                await db.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id == cl.id))

    await db.flush()
    from app.routers.schedule import enqueue_global_recalculate
    enqueue_global_recalculate(background_tasks)

    return {"ok": True, "updated": updated, "pipeline_status": target}




