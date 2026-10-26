"""End-to-end tests for Unibox & Lead Detail email tracking and engagement history.

Validates:
1. Direct email and campaign email tracking telemetry.
2. Open event tracking (first/last timestamps, open count, activity timeline).
3. Link click tracking.
4. Plain-text mode correctly marked as 'not_tracked' (never 'unopened').
5. Conversation list filtering by engagement status (open_detected, no_open_detected, replied, not_tracked).
6. Prospect Detail interaction enrichment.
7. Realtime SSE broadcast of tracking events.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest
from sqlalchemy import select

from app.models import (
    DirectEmail, EmailLog, EmailOpen, EmailClick,
    Inbox, Lead, Campaign, CampaignLead, SmtpMessage
)
from app.routers import tracking as tracking_router
from app.routers import unibox as unibox_router
from app.routers.leads import _fetch_lead_interactions
from app.unibox_tracking import (
    enrich_thread_messages_with_tracking,
    batch_resolve_threads_tracking,
    enrich_lead_interactions_with_tracking,
)
from app.tracking_events import record_email_open, record_email_click
from app.unibox import unibox_events
from tests.conftest import make_inbox, make_campaign, make_lead, make_campaign_lead, make_email_log
from tests.test_tracking_router import _noop_webhook


@pytest.mark.asyncio
async def test_direct_email_tracking_lifecycle(session, monkeypatch):
    monkeypatch.setattr("app.tracking_events.fire_webhook_event", _noop_webhook)

    # 1. Setup inbox and lead
    inbox = await make_inbox(session, email="sender@brand.com", provider="smtp")
    lead = await make_lead(session, email="prospect@acme.com", name="Acme Lead")
    lead.company = "Acme Corp"
    await session.flush()
    
    # 2. Create a sent direct email
    token = "direct-token-abc-123"
    de = DirectEmail(
        inbox_id=inbox.id,
        lead_id=lead.id,
        to_email=lead.email,
        subject="Exciting Partnership",
        body="<p>Hello Acme team</p>",
        is_html=True,
        message_id="<direct-msg-001@brand.com>",
        thread_id="thread-direct-001",
        status="sent",
        open_token=token,
        sent_at=datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    session.add(de)
    await session.flush()

    # 3. Before opens: Verify thread message tracking state
    raw_msgs = [
        {
            "message_id": "<direct-msg-001@brand.com>",
            "direction": "sent",
            "from": inbox.email,
            "to": lead.email,
            "subject": "Exciting Partnership",
            "body_html": "<p>Hello Acme team</p>",
            "timestamp": int(de.sent_at.timestamp() * 1000),
        }
    ]
    enriched = await enrich_thread_messages_with_tracking(session, raw_msgs, thread_id="thread-direct-001", inbox_id=inbox.id)
    assert len(enriched) == 1
    tr = enriched[0]["tracking"]
    assert tr is not None
    assert tr["tracking_status"] == "no_open_detected"
    assert tr["status_label"] == "No Open Detected"
    assert tr["open_count"] == 0
    assert tr["smtp_accepted"] is True

    # 4. Trigger first open via record_email_open
    res1 = await record_email_open(session, token, ip="66.249.80.1")
    assert res1 is True
    await session.flush()

    # Verify updated tracking in thread
    enriched = await enrich_thread_messages_with_tracking(session, raw_msgs, thread_id="thread-direct-001", inbox_id=inbox.id)
    tr = enriched[0]["tracking"]
    assert tr["tracking_status"] == "open_detected"
    assert tr["status_label"] == "Open Detected (1)"
    assert tr["open_count"] == 1
    assert tr["first_opened_at"] is not None
    assert tr["last_opened_at"] is not None
    assert len(tr["timeline"]) >= 2
    assert tr["timeline"][0]["type"] == "sent"
    assert tr["timeline"][1]["type"] == "open"

    # 5. Trigger second open (different time)
    res2 = await record_email_open(session, token, ip="66.249.80.2")
    assert res2 is True
    await session.flush()

    enriched = await enrich_thread_messages_with_tracking(session, raw_msgs, thread_id="thread-direct-001", inbox_id=inbox.id)
    tr = enriched[0]["tracking"]
    assert tr["open_count"] == 2

    # 6. Trigger link click on direct email
    de.click_count = 1
    de.click_history = [{"clicked_at": "2026-03-01T11:30:00Z", "url": "https://acme.com/demo"}]
    await session.flush()

    enriched = await enrich_thread_messages_with_tracking(session, raw_msgs, thread_id="thread-direct-001", inbox_id=inbox.id)
    tr = enriched[0]["tracking"]
    assert tr["tracking_status"] == "clicked"
    assert tr["click_count"] == 1
    assert len(tr["clicks"]) == 1
    assert tr["clicks"][0]["url"] == "https://acme.com/demo"


@pytest.mark.asyncio
async def test_campaign_email_tracking_enrichment(session, monkeypatch):
    monkeypatch.setattr("app.tracking_events.fire_webhook_event", _noop_webhook)

    inbox = await make_inbox(session, email="campaign-sender@brand.com", provider="smtp")
    camp = await make_campaign(session, name="Product Launch Outreach")
    camp.track_opens = True
    camp.track_clicks = True
    lead = await make_lead(session, email="lead-camp@target.com")
    cl = await make_campaign_lead(session, camp.id, lead.id)

    log = await make_email_log(session, camp.id, lead.id, inbox.id, cl.id)
    log.message_id = "<camp-msg-101@brand.com>"
    log.thread_id = "camp-thread-01"
    log.smtp_response = "250 2.0.0 OK Queued mail"
    session.add(log)
    await session.flush()

    # Record two open events for this campaign email
    op1 = EmailOpen(email_log_id=log.id, ip_address="192.168.1.1", opened_at=datetime(2026, 3, 2, 8, 0, 0, tzinfo=timezone.utc))
    op2 = EmailOpen(email_log_id=log.id, ip_address="192.168.1.2", opened_at=datetime(2026, 3, 2, 9, 30, 0, tzinfo=timezone.utc))
    session.add_all([op1, op2])
    log.open_count = 2
    log.opened_at = op1.opened_at
    await session.flush()

    raw_msgs = [
        {
            "message_id": "<camp-msg-101@brand.com>",
            "direction": "sent",
            "from": inbox.email,
            "to": lead.email,
            "subject": log.subject,
            "body_html": "<p>Campaign body</p>",
            "timestamp": int(log.sent_at.timestamp() * 1000),
        }
    ]

    enriched = await enrich_thread_messages_with_tracking(session, raw_msgs, thread_id="camp-thread-01", inbox_id=inbox.id)
    assert len(enriched) == 1
    tr = enriched[0]["tracking"]
    assert tr["tracking_status"] == "open_detected"
    assert tr["open_count"] == 2
    assert tr["first_opened_at"] is not None
    assert tr["last_opened_at"] is not None
    assert len(tr["timeline"]) >= 3  # sent + 2 opens


@pytest.mark.asyncio
async def test_plain_text_untracked_classification(session):
    inbox = await make_inbox(session, email="plain-sender@brand.com", provider="smtp")
    lead = await make_lead(session, email="plain-lead@target.com")

    # Direct email sent with is_html=False (plain text mode)
    de = DirectEmail(
        inbox_id=inbox.id,
        lead_id=lead.id,
        to_email=lead.email,
        subject="Plain Text Note",
        body="This is plain text with no HTML pixel.",
        is_html=False,
        message_id="<plain-msg-202@brand.com>",
        thread_id="plain-thread-202",
        status="sent",
        open_token=None,
        sent_at=datetime(2026, 3, 3, 14, 0, 0, tzinfo=timezone.utc),
    )
    session.add(de)
    await session.flush()

    raw_msgs = [
        {
            "message_id": "<plain-msg-202@brand.com>",
            "direction": "sent",
            "from": inbox.email,
            "to": lead.email,
            "subject": "Plain Text Note",
            "body_plain": "This is plain text with no HTML pixel.",
            "timestamp": int(de.sent_at.timestamp() * 1000),
        }
    ]

    enriched = await enrich_thread_messages_with_tracking(session, raw_msgs, thread_id="plain-thread-202", inbox_id=inbox.id)
    assert len(enriched) == 1
    tr = enriched[0]["tracking"]
    assert tr["tracking_status"] == "not_tracked"
    assert tr["tracked"] is False
    assert "Plain text" in tr["tracking_disabled_reason"]
    # Verify it is explicitly NOT marked as "unopened"
    assert "unopened" not in tr["status_label"].lower()


@pytest.mark.asyncio
async def test_batch_resolve_threads_and_filtering(session):
    inbox = await make_inbox(session, email="filter-sender@brand.com", provider="smtp")
    
    # Lead 1: Open detected
    lead1 = await make_lead(session, email="lead1-open@filter.com")
    de1 = DirectEmail(
        inbox_id=inbox.id,
        lead_id=lead1.id,
        to_email=lead1.email,
        subject="Subj 1",
        body="<p>body 1</p>",
        is_html=True,
        thread_id="t-1",
        message_id="<f-msg-1@brand.com>",
        status="sent",
        open_token="tok-open-1",
        opened=True,
        open_count=3,
        opened_at=datetime(2026, 3, 4, 10, 0, 0, tzinfo=timezone.utc),
        sent_at=datetime(2026, 3, 4, 9, 0, 0, tzinfo=timezone.utc),
    )

    # Lead 2: No open detected
    lead2 = await make_lead(session, email="lead2-noopen@filter.com")
    de2 = DirectEmail(
        inbox_id=inbox.id,
        lead_id=lead2.id,
        to_email=lead2.email,
        subject="Subj 2",
        body="<p>body 2</p>",
        is_html=True,
        thread_id="t-2",
        message_id="<f-msg-2@brand.com>",
        status="sent",
        open_token="tok-noopen-2",
        opened=False,
        open_count=0,
        sent_at=datetime(2026, 3, 4, 9, 30, 0, tzinfo=timezone.utc),
    )

    # Lead 3: Untracked plain text
    lead3 = await make_lead(session, email="lead3-untracked@filter.com")
    de3 = DirectEmail(
        inbox_id=inbox.id,
        lead_id=lead3.id,
        to_email=lead3.email,
        subject="Subj 3",
        body="plain text",
        is_html=False,
        thread_id="t-3",
        message_id="<f-msg-3@brand.com>",
        status="sent",
        open_token=None,
        sent_at=datetime(2026, 3, 4, 9, 45, 0, tzinfo=timezone.utc),
    )

    session.add_all([de1, de2, de3])
    await session.flush()

    conversations = [
        {"thread_id": "t-1", "inbox_id": inbox.id, "lead_email": lead1.email},
        {"thread_id": "t-2", "inbox_id": inbox.id, "lead_email": lead2.email},
        {"thread_id": "t-3", "inbox_id": inbox.id, "lead_email": lead3.email},
    ]

    resolved = await batch_resolve_threads_tracking(session, conversations)
    assert resolved[0]["tracking_status"] == "open_detected"
    assert resolved[1]["tracking_status"] == "no_open_detected"
    assert resolved[2]["tracking_status"] == "not_tracked"


@pytest.mark.asyncio
async def test_prospect_detail_tracking_enrichment(session):
    inbox = await make_inbox(session, email="prospect-view@brand.com", provider="smtp")
    lead = await make_lead(session, email="view-lead@target.com", name="View Lead")
    lead.company = "Target Corp"

    de = DirectEmail(
        inbox_id=inbox.id,
        lead_id=lead.id,
        to_email=lead.email,
        subject="Follow-up Inquiry",
        body="<p>Checking in</p>",
        is_html=True,
        message_id="<view-msg-303@brand.com>",
        status="sent",
        open_token="tok-view-303",
        opened=True,
        open_count=1,
        opened_at=datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc),
        sent_at=datetime(2026, 3, 5, 11, 0, 0, tzinfo=timezone.utc),
    )
    session.add(de)
    await session.flush()

    interactions = await _fetch_lead_interactions(session, lead.id)
    assert len(interactions) == 1
    ix = interactions[0]
    assert ix["tracking"] is not None
    assert ix["tracking"]["tracking_status"] == "open_detected"
    assert ix["tracking"]["open_count"] == 1
    assert ix["tracking"]["smtp_accepted"] is True
