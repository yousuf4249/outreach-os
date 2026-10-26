"""Tracking and engagement history resolver for Unified Inbox (Unibox) and Prospect Detail.

Provides individual email tracking resolution, event history, timeline generation,
status classification, and engagement metrics for both Campaign and Direct emails.
"""

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Campaign,
    DirectEmail,
    EmailClick,
    EmailLog,
    EmailOpen,
    TrackedLink,
)

log = logging.getLogger("quickly.unibox_tracking")

DISCLAIMER_TEXT = (
    "Note: Email open tracking relies on an invisible 1x1 image pixel. "
    "Privacy features (such as Apple Mail Privacy Protection), image proxy services (such as Gmail Google Image Proxy), "
    "and corporate security email scanners may automatically request images upon receipt. "
    "An open event indicates the pixel was fetched, but does not guarantee human reading."
)


def _to_iso(dt: Any) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat() + "Z"
    if isinstance(dt, (int, float)):
        val = dt / 1000.0 if dt > 1e11 else float(dt)
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).isoformat() + "Z"
        except Exception:
            return str(dt)
    if isinstance(dt, str) and dt:
        return dt if dt.endswith("Z") else dt + "Z"
    return None


def build_activity_timeline(
    *,
    sent_at: Any = None,
    smtp_accepted: bool = True,
    is_tracked: bool = True,
    tracking_disabled_reason: str | None = None,
    opens: list[dict[str, Any]] | None = None,
    clicks: list[dict[str, Any]] | None = None,
    is_replied: bool = False,
    replied_at: Any = None,
    failed: bool = False,
    error_message: str | None = None,
) -> list[dict[str, Any]]:
    """Generate a step-by-step chronological activity timeline for an email."""
    timeline: list[dict[str, Any]] = []

    norm_sent = _to_iso(sent_at)
    norm_replied = _to_iso(replied_at)

    if failed:
        timeline.append(
            {
                "type": "failed",
                "title": "Delivery Failed",
                "timestamp": norm_sent,
                "description": error_message or "An error occurred during outbound SMTP transmission.",
            }
        )
        return timeline

    # 1. Sent event
    if norm_sent:
        timeline.append(
            {
                "type": "sent",
                "title": "Email Sent (SMTP 250 Accepted)",
                "timestamp": norm_sent,
                "description": "Outbound email accepted by SMTP mail server for delivery.",
            }
        )

    # 2. Tracking status event if untracked
    if not is_tracked:
        timeline.append(
            {
                "type": "not_tracked",
                "title": "Tracking Not Attached",
                "timestamp": norm_sent,
                "description": tracking_disabled_reason
                or "No open pixel or click tracking was injected into this email.",
            }
        )
    elif not opens and not clicks and not is_replied:
        timeline.append(
            {
                "type": "pending",
                "title": "Awaiting Engagement",
                "timestamp": norm_sent,
                "description": "Tracking pixel included in email. No open recorded yet (image blocking by recipient will prevent open detection).",
            }
        )

    # 3. Opens
    open_events = opens or []
    for idx, op in enumerate(open_events):
        op_time = _to_iso(op.get("opened_at"))
        ip = op.get("ip_address")
        ip_note = f" (IP: {ip})" if ip else ""
        title = f"Open Detected #{idx + 1}" if len(open_events) > 1 else "Open Detected"
        timeline.append(
            {
                "type": "open",
                "title": title,
                "timestamp": op_time,
                "description": f"Open tracking pixel loaded via email client or proxy{ip_note}.",
            }
        )

    # 4. Clicks
    click_events = clicks or []
    for idx, cl in enumerate(click_events):
        cl_time = _to_iso(cl.get("clicked_at"))
        url = cl.get("url") or cl.get("original_url") or "Tracked link"
        timeline.append(
            {
                "type": "click",
                "title": "Link Clicked",
                "timestamp": cl_time,
                "description": f"Recipient clicked destination link: {url}",
            }
        )

    # 5. Reply
    if is_replied:
        timeline.append(
            {
                "type": "replied",
                "title": "Reply Received",
                "timestamp": norm_replied or norm_sent,
                "description": "Recipient responded to this conversation.",
            }
        )

    # Sort timeline items chronologically if timestamp exists
    timeline.sort(key=lambda x: str(x.get("timestamp") or ""))
    return timeline


def compute_tracking_status_and_label(
    *,
    failed: bool = False,
    is_replied: bool = False,
    click_count: int = 0,
    open_count: int = 0,
    is_tracked: bool = True,
    tracking_disabled_reason: str | None = None,
) -> tuple[str, str]:
    """Compute (tracking_status, status_label)."""
    if failed:
        return "failed", "Failed"
    if is_replied:
        return "replied", "Replied"
    if click_count > 0:
        return "clicked", f"Link Clicked ({click_count})"
    if open_count > 0:
        return "open_detected", f"Open Detected ({open_count})"
    if not is_tracked:
        return "not_tracked", "Not Tracked"
    return "no_open_detected", "No Open Detected"


async def enrich_thread_messages_with_tracking(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    thread_id: str,
    inbox_id: int | None = None,
) -> list[dict[str, Any]]:
    """Enrich each message in a thread with individual email tracking metrics."""
    sent_indices = [i for i, m in enumerate(messages) if m.get("direction") == "sent"]
    if not sent_indices:
        for m in messages:
            m["tracking"] = None
        return messages

    # Inbound messages for reply detection
    received_msgs = [m for m in messages if m.get("direction") == "received"]

    # Candidate identifiers
    msg_identifiers = set()
    for i in sent_indices:
        m = messages[i]
        mid = m.get("message_id")
        if mid:
            msg_identifiers.add(mid)
        # SmtpMessage rfc_id might be stored
        rfc_id = m.get("rfc_message_id")
        if rfc_id:
            msg_identifiers.add(rfc_id)

    # Query DirectEmail matches
    de_query = select(DirectEmail).where(
        or_(
            DirectEmail.thread_id == thread_id,
            DirectEmail.message_id.in_(msg_identifiers) if msg_identifiers else False,
        )
    ).order_by(DirectEmail.sent_at.asc(), DirectEmail.created_at.asc())
    de_rows = (await db.execute(de_query)).scalars().all()

    # Query EmailLog matches with opens & clicks
    el_query = select(EmailLog).options(
        selectinload(EmailLog.opens),
        selectinload(EmailLog.clicks),
        selectinload(EmailLog.tracked_links),
        selectinload(EmailLog.campaign),
    ).where(
        or_(
            EmailLog.thread_id == thread_id,
            EmailLog.message_id.in_(msg_identifiers) if msg_identifiers else False,
        )
    ).order_by(EmailLog.sent_at.asc())
    el_rows = (await db.execute(el_query)).scalars().all()

    # Build lookup dictionaries by message_id
    de_by_msg_id: dict[str, DirectEmail] = {}
    for de in de_rows:
        if de.message_id:
            de_by_msg_id[de.message_id.strip("<>")] = de
            de_by_msg_id[de.message_id] = de

    el_by_msg_id: dict[str, EmailLog] = {}
    for el in el_rows:
        if el.message_id:
            el_by_msg_id[el.message_id.strip("<>")] = el
            el_by_msg_id[el.message_id] = el

    for idx, i in enumerate(sent_indices):
        m = messages[i]
        mid = str(m.get("message_id") or "")
        rfc_mid = str(m.get("rfc_message_id") or "")
        raw_mid = mid.strip("<>")

        matched_de: DirectEmail | None = None
        matched_el: EmailLog | None = None

        # 1. Match DirectEmail
        if mid in de_by_msg_id:
            matched_de = de_by_msg_id[mid]
        elif raw_mid in de_by_msg_id:
            matched_de = de_by_msg_id[raw_mid]
        elif rfc_mid and rfc_mid in de_by_msg_id:
            matched_de = de_by_msg_id[rfc_mid]
        elif len(de_rows) == 1 and len(sent_indices) == 1:
            matched_de = de_rows[0]
        elif idx < len(de_rows) and not el_rows:
            matched_de = de_rows[idx]

        # 2. Match EmailLog if not DirectEmail
        if not matched_de:
            if mid in el_by_msg_id:
                matched_el = el_by_msg_id[mid]
            elif raw_mid in el_by_msg_id:
                matched_el = el_by_msg_id[raw_mid]
            elif rfc_mid and rfc_mid in el_by_msg_id:
                matched_el = el_by_msg_id[rfc_mid]
            elif len(el_rows) == 1 and len(sent_indices) == 1:
                matched_el = el_rows[0]
            elif idx < len(el_rows):
                matched_el = el_rows[idx]

        # Check if replied by subsequent received message
        msg_time = m.get("timestamp") or ""
        subsequent_received = [r for r in received_msgs if (r.get("timestamp") or "") > msg_time]
        is_replied = bool(subsequent_received)
        replied_at = subsequent_received[0]["timestamp"] if subsequent_received else None

        if matched_de:
            is_html = getattr(matched_de, "is_html", True)
            has_token = bool(matched_de.open_token)
            is_tracked = bool(is_html and has_token)
            disabled_reason = None
            if not is_html:
                is_tracked = False
                disabled_reason = "Plain text email (open tracking pixel requires HTML rendering)"
            elif not has_token:
                is_tracked = False
                disabled_reason = "Open tracking was disabled for this email"

            open_count = matched_de.open_count or (1 if matched_de.opened else 0)
            first_opened_at = _to_iso(matched_de.opened_at)
            last_opened_at = _to_iso(getattr(matched_de, "last_opened_at", None) or matched_de.opened_at)
            click_count = getattr(matched_de, "click_count", 0) or 0

            opens = getattr(matched_de, "open_history", None) or []
            if not opens and matched_de.opened and first_opened_at:
                opens = [{"opened_at": first_opened_at, "ip_address": None}]

            clicks = getattr(matched_de, "click_history", None) or []

            is_failed = matched_de.status == "failed"
            status, label = compute_tracking_status_and_label(
                failed=is_failed,
                is_replied=is_replied or bool(matched_de.replied),
                click_count=click_count,
                open_count=open_count,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
            )

            timeline = build_activity_timeline(
                sent_at=m.get("timestamp"),
                smtp_accepted=not is_failed,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
                opens=opens,
                clicks=clicks,
                is_replied=is_replied or bool(matched_de.replied),
                replied_at=replied_at or _to_iso(matched_de.replied_at),
                failed=is_failed,
                error_message=matched_de.error_message,
            )

            m["tracking"] = {
                "source": "direct_email",
                "id": matched_de.id,
                "tracked": is_tracked,
                "tracking_status": status,
                "status_label": label,
                "tracking_disabled_reason": disabled_reason,
                "sent_at": m.get("timestamp"),
                "smtp_accepted": not is_failed,
                "smtp_accepted_at": m.get("timestamp"),
                "open_count": open_count,
                "first_opened_at": first_opened_at,
                "last_opened_at": last_opened_at,
                "click_count": click_count,
                "first_clicked_at": clicks[0].get("clicked_at") if clicks else None,
                "last_clicked_at": clicks[-1].get("clicked_at") if clicks else None,
                "opens": opens,
                "clicks": clicks,
                "replied": is_replied or bool(matched_de.replied),
                "replied_at": replied_at or _to_iso(matched_de.replied_at),
                "timeline": timeline,
                "disclaimer": DISCLAIMER_TEXT,
            }

        elif matched_el:
            camp = matched_el.campaign
            track_opens = getattr(camp, "track_opens", False) if camp else False
            track_clicks = getattr(camp, "track_clicks", False) if camp else False
            override = matched_el.format_override or ""

            is_tracked = bool((track_opens or track_clicks) and override not in ("text_forced_tracking_disabled", "first_text_tracking_disabled"))
            disabled_reason = None
            if override in ("text_forced_tracking_disabled", "first_text_tracking_disabled"):
                is_tracked = False
                disabled_reason = "Plain text mode forced by campaign settings (open pixel omitted)"
            elif not (track_opens or track_clicks):
                is_tracked = False
                disabled_reason = "Open and click tracking disabled in campaign settings"

            opens_list = [
                {"opened_at": _to_iso(o.opened_at), "ip_address": o.ip_address}
                for o in (matched_el.opens or [])
            ]
            tracked_links_map = {
                tl.token: tl.original_url for tl in (matched_el.tracked_links or [])
            }
            clicks_list = [
                {
                    "clicked_at": _to_iso(c.clicked_at),
                    "ip_address": c.ip_address,
                    "url": tracked_links_map.get(getattr(c, "token", ""), "Tracked Link"),
                }
                for c in (matched_el.clicks or [])
            ]

            open_count = len(opens_list) or (1 if matched_el.opened else 0)
            click_count = len(clicks_list) or (1 if matched_el.clicked else 0)
            first_opened_at = opens_list[0]["opened_at"] if opens_list else (_to_iso(matched_el.sent_at) if matched_el.opened else None)
            last_opened_at = opens_list[-1]["opened_at"] if opens_list else first_opened_at
            first_clicked_at = clicks_list[0]["clicked_at"] if clicks_list else None
            last_clicked_at = clicks_list[-1]["clicked_at"] if clicks_list else None

            status, label = compute_tracking_status_and_label(
                failed=False,
                is_replied=is_replied,
                click_count=click_count,
                open_count=open_count,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
            )

            timeline = build_activity_timeline(
                sent_at=m.get("timestamp"),
                smtp_accepted=True,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
                opens=opens_list,
                clicks=clicks_list,
                is_replied=is_replied,
                replied_at=replied_at,
            )

            m["tracking"] = {
                "source": "campaign_email",
                "id": matched_el.id,
                "campaign_id": matched_el.campaign_id,
                "campaign_name": getattr(camp, "name", "") if camp else "",
                "tracked": is_tracked,
                "tracking_status": status,
                "status_label": label,
                "tracking_disabled_reason": disabled_reason,
                "sent_at": m.get("timestamp"),
                "smtp_accepted": True,
                "smtp_accepted_at": m.get("timestamp"),
                "open_count": open_count,
                "first_opened_at": first_opened_at,
                "last_opened_at": last_opened_at,
                "click_count": click_count,
                "first_clicked_at": first_clicked_at,
                "last_clicked_at": last_clicked_at,
                "opens": opens_list,
                "clicks": clicks_list,
                "replied": is_replied,
                "replied_at": replied_at,
                "timeline": timeline,
                "disclaimer": DISCLAIMER_TEXT,
            }

        else:
            # Fallback for sent message without tracking metadata
            timeline = [
                {
                    "type": "sent",
                    "title": "Email Sent",
                    "timestamp": m.get("timestamp"),
                    "description": "Message recorded in sent folder.",
                },
                {
                    "type": "not_tracked",
                    "title": "Tracking Not Configured",
                    "timestamp": m.get("timestamp"),
                    "description": "No tracking mechanism was attached to this sent message.",
                },
            ]
            if is_replied:
                timeline.append(
                    {
                        "type": "replied",
                        "title": "Reply Received",
                        "timestamp": replied_at,
                        "description": "Recipient responded to this conversation.",
                    }
                )

            m["tracking"] = {
                "source": "untracked",
                "tracked": False,
                "tracking_status": "replied" if is_replied else "not_tracked",
                "status_label": "Replied" if is_replied else "Not Tracked",
                "tracking_disabled_reason": "No tracking record associated with this message",
                "sent_at": m.get("timestamp"),
                "smtp_accepted": True,
                "smtp_accepted_at": m.get("timestamp"),
                "open_count": 0,
                "first_opened_at": None,
                "last_opened_at": None,
                "click_count": 0,
                "first_clicked_at": None,
                "last_clicked_at": None,
                "opens": [],
                "clicks": [],
                "replied": is_replied,
                "replied_at": replied_at,
                "timeline": timeline,
                "disclaimer": DISCLAIMER_TEXT,
            }

    return messages


async def batch_resolve_threads_tracking(
    db: AsyncSession,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich conversation items in list_unibox_conversations with aggregate tracking status."""
    if not items:
        return items

    thread_ids = [it["thread_id"] for it in items if it.get("thread_id")]
    if not thread_ids:
        return

    # DirectEmail aggregation by thread_id
    de_res = await db.execute(
        select(
            DirectEmail.thread_id,
            func.max(DirectEmail.opened).label("max_opened"),
            func.sum(DirectEmail.open_count).label("sum_opens"),
            func.max(DirectEmail.replied).label("max_replied"),
            func.max(DirectEmail.click_count).label("max_clicks"),
            func.min(DirectEmail.is_html).label("min_is_html"),
            func.max(DirectEmail.open_token).label("max_token"),
        )
        .where(DirectEmail.thread_id.in_(thread_ids))
        .group_by(DirectEmail.thread_id)
    )
    de_map = {
        row[0]: {
            "opened": bool(row[1]),
            "open_count": int(row[2] or 0),
            "replied": bool(row[3]),
            "clicks": int(row[4] or 0),
            "is_html": bool(row[5]),
            "has_token": bool(row[6]),
        }
        for row in de_res.all()
    }

    # EmailLog aggregation by thread_id
    el_res = await db.execute(
        select(
            EmailLog.thread_id,
            func.max(EmailLog.opened).label("max_opened"),
            func.max(EmailLog.clicked).label("max_clicked"),
            func.max(EmailLog.format_override).label("format_override"),
        )
        .where(EmailLog.thread_id.in_(thread_ids))
        .group_by(EmailLog.thread_id)
    )
    el_map = {
        row[0]: {
            "opened": bool(row[1]),
            "clicked": bool(row[2]),
            "override": row[3],
        }
        for row in el_res.all()
    }

    for it in items:
        tid = it.get("thread_id")
        de_info = de_map.get(tid)
        el_info = el_map.get(tid)

        unread_reply = bool(it.get("unread_lead_reply"))
        tot_opens = (de_info["open_count"] if de_info else 0) + (1 if (el_info and el_info["opened"]) else 0)
        has_click = (de_info and de_info["clicks"] > 0) or (el_info and el_info["clicked"])
        is_replied = unread_reply or (de_info and de_info["replied"])

        if is_replied:
            it["tracking_status"] = "replied"
            it["tracking_label"] = "Replied"
        elif has_click:
            it["tracking_status"] = "clicked"
            it["tracking_label"] = "Link Clicked"
        elif tot_opens > 0 or (de_info and de_info["opened"]) or (el_info and el_info["opened"]):
            it["tracking_status"] = "open_detected"
            it["tracking_label"] = f"Open Detected ({tot_opens})"
        elif de_info and (de_info["is_html"] and de_info["has_token"]):
            it["tracking_status"] = "no_open_detected"
            it["tracking_label"] = "No Open Detected"
        elif el_info and el_info.get("override") not in ("text_forced_tracking_disabled", "first_text_tracking_disabled"):
            it["tracking_status"] = "no_open_detected"
            it["tracking_label"] = "No Open Detected"
        else:
            it["tracking_status"] = "not_tracked"
            it["tracking_label"] = "Not Tracked"

        it["open_count"] = tot_opens

    return items


async def enrich_lead_interactions_with_tracking(
    db: AsyncSession,
    events: list[dict[str, Any]],
    lead_id: int,
) -> list[dict[str, Any]]:
    """Enrich lead interactions with individual email tracking metrics."""
    outbound_events = [e for e in events if e.get("direction") == "outbound"]
    if not outbound_events:
        return events

    # Inbound messages for reply detection
    has_reply = any(e.get("direction") == "inbound" for e in events)
    first_reply_time = next((e.get("at") for e in events if e.get("direction") == "inbound"), None)

    direct_ids = [e.get("id") for e in outbound_events if e.get("kind") == "direct_email" and e.get("id")]
    campaign_log_ids = [e.get("id") for e in outbound_events if e.get("kind") == "campaign_email" and e.get("id")]

    # Fetch DirectEmail rows
    de_rows = (
        await db.execute(
            select(DirectEmail).where(
                or_(
                    DirectEmail.lead_id == lead_id,
                    DirectEmail.id.in_(direct_ids) if direct_ids else False,
                )
            )
        )
    ).scalars().all()
    de_by_id = {de.id: de for de in de_rows}

    # Fetch EmailLog rows with opens, clicks, links, campaign
    el_rows = (
        await db.execute(
            select(EmailLog)
            .options(
                selectinload(EmailLog.opens),
                selectinload(EmailLog.clicks),
                selectinload(EmailLog.tracked_links),
                selectinload(EmailLog.campaign),
            )
            .where(
                or_(
                    EmailLog.lead_id == lead_id,
                    EmailLog.id.in_(campaign_log_ids) if campaign_log_ids else False,
                )
            )
        )
    ).scalars().all()
    el_by_id = {el.id: el for el in el_rows}

    for e in outbound_events:
        kind = e.get("kind")
        item_id = e.get("id")
        event_time = e.get("at")
        is_replied_after = any(
            inv.get("direction") == "inbound" and (inv.get("at") or "") > (event_time or "")
            for inv in events
        )
        replied_at_time = next(
            (
                inv.get("at")
                for inv in events
                if inv.get("direction") == "inbound" and (inv.get("at") or "") > (event_time or "")
            ),
            first_reply_time if has_reply else None,
        )

        if kind == "direct_email" and item_id in de_by_id:
            de = de_by_id[item_id]
            is_html = getattr(de, "is_html", True)
            has_token = bool(de.open_token)
            is_tracked = bool(is_html and has_token)
            disabled_reason = None
            if not is_html:
                is_tracked = False
                disabled_reason = "Plain text email (open pixel requires HTML)"
            elif not has_token:
                is_tracked = False
                disabled_reason = "Open tracking was disabled for this email"

            open_count = de.open_count or (1 if de.opened else 0)
            first_opened_at = _to_iso(de.opened_at)
            last_opened_at = _to_iso(getattr(de, "last_opened_at", None) or de.opened_at)
            click_count = getattr(de, "click_count", 0) or 0
            opens = getattr(de, "open_history", None) or []
            if not opens and de.opened and first_opened_at:
                opens = [{"opened_at": first_opened_at, "ip_address": None}]
            clicks = getattr(de, "click_history", None) or []

            is_failed = de.status == "failed"
            status, label = compute_tracking_status_and_label(
                failed=is_failed,
                is_replied=is_replied_after or bool(de.replied),
                click_count=click_count,
                open_count=open_count,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
            )

            timeline = build_activity_timeline(
                sent_at=event_time,
                smtp_accepted=not is_failed,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
                opens=opens,
                clicks=clicks,
                is_replied=is_replied_after or bool(de.replied),
                replied_at=replied_at_time or _to_iso(de.replied_at),
                failed=is_failed,
                error_message=de.error_message,
            )

            e["tracking"] = {
                "source": "direct_email",
                "id": de.id,
                "tracked": is_tracked,
                "tracking_status": status,
                "status_label": label,
                "tracking_disabled_reason": disabled_reason,
                "sent_at": event_time,
                "smtp_accepted": not is_failed,
                "smtp_accepted_at": event_time,
                "open_count": open_count,
                "first_opened_at": first_opened_at,
                "last_opened_at": last_opened_at,
                "click_count": click_count,
                "first_clicked_at": clicks[0].get("clicked_at") if clicks else None,
                "last_clicked_at": clicks[-1].get("clicked_at") if clicks else None,
                "opens": opens,
                "clicks": clicks,
                "replied": is_replied_after or bool(de.replied),
                "replied_at": replied_at_time or _to_iso(de.replied_at),
                "timeline": timeline,
                "disclaimer": DISCLAIMER_TEXT,
            }

        elif kind == "campaign_email" and item_id in el_by_id:
            el = el_by_id[item_id]
            camp = el.campaign
            track_opens = getattr(camp, "track_opens", False) if camp else False
            track_clicks = getattr(camp, "track_clicks", False) if camp else False
            override = el.format_override or ""

            is_tracked = bool((track_opens or track_clicks) and override not in ("text_forced_tracking_disabled", "first_text_tracking_disabled"))
            disabled_reason = None
            if override in ("text_forced_tracking_disabled", "first_text_tracking_disabled"):
                is_tracked = False
                disabled_reason = "Plain text mode forced by campaign settings (open pixel omitted)"
            elif not (track_opens or track_clicks):
                is_tracked = False
                disabled_reason = "Open and click tracking disabled in campaign settings"

            opens_list = [
                {"opened_at": _to_iso(o.opened_at), "ip_address": o.ip_address}
                for o in (el.opens or [])
            ]
            tracked_links_map = {
                tl.token: tl.original_url for tl in (el.tracked_links or [])
            }
            clicks_list = [
                {
                    "clicked_at": _to_iso(c.clicked_at),
                    "ip_address": c.ip_address,
                    "url": tracked_links_map.get(getattr(c, "token", ""), "Tracked Link"),
                }
                for c in (el.clicks or [])
            ]

            open_count = len(opens_list) or (1 if el.opened else 0)
            click_count = len(clicks_list) or (1 if el.clicked else 0)
            first_opened_at = opens_list[0]["opened_at"] if opens_list else (_to_iso(el.sent_at) if el.opened else None)
            last_opened_at = opens_list[-1]["opened_at"] if opens_list else first_opened_at
            first_clicked_at = clicks_list[0]["clicked_at"] if clicks_list else None
            last_clicked_at = clicks_list[-1]["clicked_at"] if clicks_list else None

            status, label = compute_tracking_status_and_label(
                failed=False,
                is_replied=is_replied_after,
                click_count=click_count,
                open_count=open_count,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
            )

            timeline = build_activity_timeline(
                sent_at=event_time,
                smtp_accepted=True,
                is_tracked=is_tracked,
                tracking_disabled_reason=disabled_reason,
                opens=opens_list,
                clicks=clicks_list,
                is_replied=is_replied_after,
                replied_at=replied_at_time,
            )

            e["tracking"] = {
                "source": "campaign_email",
                "id": el.id,
                "campaign_id": el.campaign_id,
                "campaign_name": getattr(camp, "name", "") if camp else "",
                "tracked": is_tracked,
                "tracking_status": status,
                "status_label": label,
                "tracking_disabled_reason": disabled_reason,
                "sent_at": event_time,
                "smtp_accepted": True,
                "smtp_accepted_at": event_time,
                "open_count": open_count,
                "first_opened_at": first_opened_at,
                "last_opened_at": last_opened_at,
                "click_count": click_count,
                "first_clicked_at": first_clicked_at,
                "last_clicked_at": last_clicked_at,
                "opens": opens_list,
                "clicks": clicks_list,
                "replied": is_replied_after,
                "replied_at": replied_at_time,
                "timeline": timeline,
                "disclaimer": DISCLAIMER_TEXT,
            }
        else:
            e["tracking"] = None

    return events

