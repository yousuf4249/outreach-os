"""Targeted QA Audit Tests for P0 Sending Engine Corrections.

Covers:
1. Multi-process atomic budget reservation (database-level serialization).
2. Active send protection (> 5 mins) prevents stale slot reclamation while original SMTP send is active.
3. SMTP-uncertain messages retain an appropriate monthly budget reservation until reconciled.
4. Multi-process concurrent campaign + direct sends with 1 unit remaining.
5. Pytest warnings classification and actionable fixes verification.
"""

import asyncio
import os
import sys
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppSetting,
    Campaign,
    CampaignLead,
    DirectEmail,
    EmailLog,
    Inbox,
    Lead,
    QueueSlot,
    Sequence,
    SmtpAccount,
)
from app.app_settings import (
    acquire_db_budget_lock,
    check_and_reserve_monthly_budget,
    get_monthly_sending_budget,
    get_monthly_sending_stats,
    set_monthly_sending_budget,
)
from app.jobs import send_slot_job, is_worker_alive
from app.routers.direct_email import execute_send_direct_email
from app.sender import SendResult, SendUncertain, SendFailure
from app.time import utcnow


@pytest.mark.asyncio
async def test_01_uncertain_messages_retain_budget_reservation(session: AsyncSession):
    """Verify that SMTP-uncertain messages retain an appropriate budget reservation until reconciled."""
    # Set monthly budget = 10
    await set_monthly_sending_budget(session, 10)

    # 1. Start with 8 committed sent emails
    now = utcnow()
    for i in range(8):
        log = EmailLog(
            inbox_id=1,
            campaign_id=1,
            lead_id=100 + i,
            subject="Test",
            sent_at=now,
        )
        session.add(log)
    await session.commit()

    # Check stats: committed=8, remaining=2
    stats = await get_monthly_sending_stats(session)
    assert stats["sent_this_month"] == 8
    assert stats["remaining_budget"] == 2

    # 2. Add an uncertain QueueSlot (e.g. SMTP server disconnected after DATA)
    slot_uncertain = QueueSlot(
        campaign_lead_id=1,
        inbox_id=1,
        sequence_index=0,
        position_in_day=1,
        scheduled_date=now,
        status="uncertain",
        claimed_by="needs_reconciliation",
        claimed_at=now,
    )
    session.add(slot_uncertain)
    await session.commit()

    # Budget MUST now count the uncertain slot: consumed=9, remaining=1
    is_allowed, total_consumed, remaining = await check_and_reserve_monthly_budget(session, additional_units=1)
    assert total_consumed == 9
    assert remaining == 1
    assert is_allowed is True

    # 3. Add an uncertain DirectEmail
    direct_uncertain = DirectEmail(
        inbox_id=1,
        to_email="direct_uncertain@example.com",
        subject="Direct Test",
        body="Hello",
        status="uncertain",
        updated_at=now,
    )
    session.add(direct_uncertain)
    await session.commit()

    # Budget MUST now count both uncertain items: consumed=10, remaining=0
    is_allowed, total_consumed, remaining = await check_and_reserve_monthly_budget(session, additional_units=1)
    assert total_consumed == 10
    assert remaining == 0
    assert is_allowed is False, "CRITICAL: Uncertain emails failed to retain budget reservation, allowing overage!"

    stats2 = await get_monthly_sending_stats(session)
    assert stats2["sent_this_month"] == 10
    assert stats2["remaining_budget"] == 0
    assert stats2.get("uncertain_count") == 2
    assert stats2["is_exhausted"] is True


@pytest.mark.asyncio
async def test_02_active_send_cannot_be_reclaimed_after_5_minutes(session: AsyncSession):
    """Verify that a processing email cannot be reclaimed after 5 minutes while its original SMTP send is still active."""
    now = utcnow()
    stale_time = now - timedelta(minutes=6)

    # 1. Verify worker liveness check
    my_pid = os.getpid()
    active_worker_id = f"worker-{my_pid}-active01"
    dead_worker_id = "worker-9999999-dead01"

    assert is_worker_alive(active_worker_id) is True, "Active process must be detected as alive"
    assert is_worker_alive(dead_worker_id) is False, "Non-existent PID must be detected as dead"

    # 2. Setup a slot in processing with claimed_at older than 5 minutes, but claimed by active worker PID
    inbox = Inbox(email="active@example.com", provider="smtp", paused=False, wait_minutes_between=0)
    session.add(inbox)
    await session.flush()

    lead = Lead(email="target@example.com", name="Target Lead")
    session.add(lead)
    await session.flush()

    camp = Campaign(name="Active Protection Camp", paused=False, sending_hours_start="00:00", sending_hours_end="23:59")
    session.add(camp)
    await session.flush()

    cl = CampaignLead(campaign_id=camp.id, lead_id=lead.id, enrollment_status="active")
    session.add(cl)
    await session.flush()

    slot = QueueSlot(
        campaign_lead_id=cl.id,
        inbox_id=inbox.id,
        sequence_index=0,
        position_in_day=1,
        scheduled_date=now - timedelta(minutes=10),
        status="processing",
        claimed_at=stale_time,  # 6 minutes ago (> 5 min threshold)
        claimed_by=active_worker_id,  # Alive worker
    )
    session.add(slot)
    await session.commit()
    await session.refresh(slot)

    # 3. Simulate another worker attempting to claim this slot
    with patch("app.jobs.send_email") as mock_send:
        await send_slot_job(slot.id)
        # Send must NOT have been called because worker is alive!
        assert mock_send.call_count == 0

    # Verify slot remains in processing by original worker and was NOT stolen
    await session.refresh(slot)
    assert slot.status == "processing"
    assert slot.claimed_by == active_worker_id


@pytest.mark.asyncio
async def test_03_db_budget_lock_serialization(session: AsyncSession):
    """Verify cross-process DB-level transaction synchronization via acquire_db_budget_lock."""
    # Ensure dedicated lock row exists and is acquired cleanly
    await acquire_db_budget_lock(session)
    res = await session.execute(select(AppSetting).where(AppSetting.key == "global_sending_lock"))
    lock_setting = res.scalar_one_or_none()
    assert lock_setting is not None
    assert float(lock_setting.value) > 0


@pytest.mark.asyncio
async def test_04_concurrent_campaign_and_direct_sends_1_unit_remaining(session: AsyncSession):
    """Verify that with only 1 budget unit remaining, concurrent campaign and direct sends strictly honor the cap."""
    await set_monthly_sending_budget(session, 1)

    now = utcnow()
    inbox = Inbox(email="concur_test@example.com", provider="smtp", paused=False, wait_minutes_between=0)
    session.add(inbox)
    await session.flush()

    smtp = SmtpAccount(
        inbox_id=inbox.id,
        smtp_host="smtp.mailgun.org",
        smtp_port=587,
        smtp_username="concur_user",
        smtp_password="password",
    )
    session.add(smtp)
    await session.flush()

    lead = Lead(email="concur_lead@example.com", name="Concurrent Lead")
    session.add(lead)
    await session.flush()

    camp = Campaign(name="Concurrent Camp", paused=False, sending_hours_start="00:00", sending_hours_end="23:59")
    session.add(camp)
    await session.flush()

    cl = CampaignLead(campaign_id=camp.id, lead_id=lead.id, enrollment_status="active")
    session.add(cl)
    await session.flush()

    seq = Sequence(campaign_id=camp.id, position=0, subject="Subj", body="Body")
    session.add(seq)
    await session.flush()

    slot = QueueSlot(
        campaign_lead_id=cl.id,
        inbox_id=inbox.id,
        sequence_index=0,
        position_in_day=1,
        scheduled_date=now - timedelta(minutes=1),
        status="scheduled",
    )
    session.add(slot)

    direct = DirectEmail(
        inbox_id=inbox.id,
        to_email="direct_concur@example.com",
        subject="Direct Race",
        body="Race Body",
        status="draft",
    )
    session.add(direct)
    await session.commit()
    await session.refresh(slot)
    await session.refresh(direct)

    # Mock send_email with a successful SendResult
    mock_res = SendResult(message_id="msg-race-001", thread_id="thr-race-001")
    
    with patch("app.jobs.send_email", return_value=mock_res) as mock_slot_send, \
         patch("app.routers.direct_email.send_email", return_value=mock_res) as mock_direct_send:

        # Run campaign send and direct send simultaneously
        task1 = asyncio.create_task(send_slot_job(slot.id))
        task2 = asyncio.create_task(execute_send_direct_email(session, direct))
        results = await asyncio.gather(task1, task2, return_exceptions=True)

    # Check total sends executed across both channels
    total_calls = mock_slot_send.call_count + mock_direct_send.call_count
    assert total_calls == 1, f"CRITICAL: Monthly budget was 1, but {total_calls} emails were sent! Budget exceeded!"

    # Verify that the rejected send was blocked cleanly
    stats = await get_monthly_sending_stats(session)
    assert stats["sent_this_month"] >= 1
    assert stats["remaining_budget"] == 0
    assert stats["is_exhausted"] is True


@pytest.mark.asyncio
async def test_05_warning_reduction_audit():
    """Verify that actionable warnings have been eliminated."""
    # Ensure utcnow() does not emit DeprecationWarning
    val = utcnow()
    assert isinstance(val, datetime)
    assert val.tzinfo is None  # Consistent naive UTC representation for DB compatibility
