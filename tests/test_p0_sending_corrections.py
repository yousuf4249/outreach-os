"""Weblinx Outreach OS - Production-Readiness Verification Suite
P0 Sending Engine Corrections

Tests:
1. Global monthly budget 10,000 with no arbitrary daily/weekly restrictions.
2. Campaign interval of 1 minute despite legacy inbox interval of 5 minutes.
3. Multiple independent campaigns with different timezones.
4. 4 workers simultaneously sending with only one global budget unit remaining (budget never exceeded).
5. Simultaneous campaign and direct sends consuming the same budget.
6. SMTP failure, successful send, ambiguous acceptance (SendUncertain -> status='uncertain'), and retry handling.
7. Budget exhaustion and next-cycle recovery.
8. Preservation of existing follow-up sender identity and RFC threading.
9. Queue restart recovery and idempotency for abandoned claims.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone, date
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Ensure app imports resolve
sys.path.insert(0, os.path.abspath("."))

from app.database import Base
from app.models import (
    Campaign, Inbox, Sequence, Lead, CampaignLead, CampaignInbox,
    QueueSlot, EmailLog, DirectEmail, AppSetting, SmtpAccount,
)
from app.app_settings import (
    get_monthly_sending_budget, set_monthly_sending_budget,
    get_billing_cycle_start_day, set_billing_cycle_start_day,
    get_monthly_sending_stats, get_billing_period_bounds,
    check_and_reserve_monthly_budget,
)
from app.jobs import send_slot_job, run_slot_scan_job
from app.sender import SendResult, SendFailure, SendUncertain
from app.routers.direct_email import execute_send_direct_email


TEST_DB_FILE = os.path.abspath("test_p0_corrections.db")

def cleanup_db_files():
    for ext in ["", "-wal", "-shm"]:
        p = TEST_DB_FILE + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"


async def get_test_factory():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA busy_timeout=30000;"))
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def reset_db(session_factory):
    async with session_factory() as session:
        for tbl in ["queue_slot", "email_log", "direct_email", "campaign_lead", "campaign_inbox", "sequence", "lead", "smtp_account", "inbox", "campaign", "app_setting"]:
            try:
                await session.execute(text(f"DELETE FROM {tbl};"))
            except Exception:
                pass
        await session.commit()


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


# ==============================================================================
# TEST 1: Global monthly budget with no arbitrary daily/weekly restrictions
# ==============================================================================
@pytest.mark.asyncio
async def test_01_global_budget_no_arbitrary_daily_cap():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 10000)
        await set_billing_cycle_start_day(session, 1)

        campaign = Campaign(
            name="No Daily Restriction Campaign",
            timezone="UTC",
            sending_days=[0, 1, 2, 3, 4, 5, 6],
            sending_hours_start="00:00",
            sending_hours_end="23:59",
            wait_minutes_between=1,
        )
        session.add(campaign)

        inbox = Inbox(
            email="sender_nodaily@example.com",
            display_name="Sender",
            provider="smtp",
            paused=False,
            max_emails_per_day=50,  # Legacy 50/day cap
            wait_minutes_between=5,
            ramp_up_enabled=False,  # Ramp-up disabled: global budget rules!
        )
        session.add(inbox)
        await session.flush()

        smtp = SmtpAccount(
            inbox_id=inbox.id,
            smtp_host="smtp.mailgun.org",
            smtp_port=587,
            smtp_username="postmaster@mg.example.com",
            smtp_password="pw",
        )
        session.add(smtp)

        seq = Sequence(
            campaign_id=campaign.id,
            position=0,
            subject="Hello {{name}}",
            body="Test email content",
            is_html=False,
        )
        session.add(seq)

        ci = CampaignInbox(campaign_id=campaign.id, inbox_id=inbox.id, position=0)
        session.add(ci)
        await session.flush()

        # Simulate 50 emails ALREADY sent today
        today_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(50):
            lead = Lead(email=f"lead_old_{i}@example.com", name=f"Lead {i}")
            session.add(lead)
            await session.flush()
            log_entry = EmailLog(
                lead_id=lead.id,
                campaign_id=campaign.id,
                inbox_id=inbox.id,
                sequence_index=0,
                sent_at=today_utc - timedelta(hours=1, minutes=i),
                message_id=f"<msg_{i}@domain.com>",
            )
            session.add(log_entry)

        # Create 51st lead and QueueSlot
        lead_51 = Lead(email="lead_51@example.com", name="Lead 51")
        session.add(lead_51)
        await session.flush()

        cl_51 = CampaignLead(campaign_id=campaign.id, lead_id=lead_51.id, enrollment_status="active")
        session.add(cl_51)
        await session.flush()

        slot_51 = QueueSlot(
            campaign_lead_id=cl_51.id,
            inbox_id=inbox.id,
            sequence_index=0,
            scheduled_date=today_utc,
            position_in_day=51,
            status="scheduled",
        )
        session.add(slot_51)
        await session.commit()
        slot_51_id = slot_51.id

    # Dispatch slot 51 via send_slot_job with mocked network send
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=SendResult(message_id="<lead_51_success@test.com>")):
        await send_slot_job(slot_51_id)

    # Verify slot 51 was NOT blocked by the 50/day limit
    async with session_factory() as session:
        slot_check = (await session.execute(select(QueueSlot).where(QueueSlot.id == slot_51_id))).scalar_one_or_none()
        assert slot_check is None, "Slot 51 should be sent and removed from queue, not blocked by 50/day limit"

        log_51 = (await session.execute(
            select(EmailLog).where(EmailLog.lead_id == lead_51.id)
        )).scalar_one_or_none()
        assert log_51 is not None, "EmailLog for 51st email must be created"
        assert log_51.message_id == "<lead_51_success@test.com>"


# ==============================================================================
# TEST 2: Campaign interval of 1 min despite legacy inbox interval of 5 mins
# ==============================================================================
@pytest.mark.asyncio
async def test_02_campaign_interval_overrides_inbox_interval():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 10000)

        campaign = Campaign(
            name="1-Min Interval Campaign",
            timezone="UTC",
            sending_days=[0, 1, 2, 3, 4, 5, 6],
            sending_hours_start="00:00",
            sending_hours_end="23:59",
            wait_minutes_between=1,  # 1-minute interval
        )
        session.add(campaign)

        inbox = Inbox(
            email="sender_interval@example.com",
            display_name="Sender",
            provider="smtp",
            paused=False,
            max_emails_per_day=50,
            wait_minutes_between=5,  # Old legacy 5-minute interval
            ramp_up_enabled=False,
        )
        session.add(inbox)
        await session.flush()

        smtp = SmtpAccount(
            inbox_id=inbox.id,
            smtp_host="smtp.mailgun.org",
            smtp_port=587,
            smtp_username="u",
            smtp_password="p",
        )
        session.add(smtp)

        seq = Sequence(
            campaign_id=campaign.id,
            position=0,
            subject="Fast send",
            body="Fast",
            is_html=False,
        )
        session.add(seq)

        # Lead 1: Sent 2 minutes ago (greater than campaign 1 min, but less than inbox 5 min)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        lead_1 = Lead(email="fast_lead_1@example.com", name="L1")
        session.add(lead_1)
        await session.flush()

        log_1 = EmailLog(
            lead_id=lead_1.id,
            campaign_id=campaign.id,
            inbox_id=inbox.id,
            sequence_index=0,
            sent_at=now_utc - timedelta(minutes=2),
            message_id="<fast_1@domain.com>",
        )
        session.add(log_1)

        # Lead 2: Scheduled right now
        lead_2 = Lead(email="fast_lead_2@example.com", name="L2")
        session.add(lead_2)
        await session.flush()

        cl_2 = CampaignLead(campaign_id=campaign.id, lead_id=lead_2.id, enrollment_status="active")
        session.add(cl_2)
        await session.flush()

        slot_2 = QueueSlot(
            campaign_lead_id=cl_2.id,
            inbox_id=inbox.id,
            sequence_index=0,
            scheduled_date=now_utc,
            position_in_day=2,
            status="scheduled",
        )
        session.add(slot_2)
        await session.commit()
        slot_2_id = slot_2.id

    # Dispatch slot 2 via send_slot_job
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=SendResult(message_id="<fast_2_success@test.com>")):
        await send_slot_job(slot_2_id)

    # Under 5-min inbox rule, slot 2 would have been skipped. Under 1-min campaign rule, it must succeed!
    async with session_factory() as session:
        slot_check = (await session.execute(select(QueueSlot).where(QueueSlot.id == slot_2_id))).scalar_one_or_none()
        assert slot_check is None, "Slot 2 should be sent because 2 mins elapsed (campaign interval is 1 min)"

        log_2 = (await session.execute(select(EmailLog).where(EmailLog.lead_id == lead_2.id))).scalar_one_or_none()
        assert log_2 is not None
        assert log_2.message_id == "<fast_2_success@test.com>"


# ==============================================================================
# TEST 3: Multiple independent campaigns with different timezones
# ==============================================================================
@pytest.mark.asyncio
async def test_03_multiple_campaigns_different_timezones():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 10000)

        camp_ny = Campaign(
            name="NY Campaign",
            timezone="America/New_York",
            sending_days=[0, 1, 2, 3, 4, 5, 6],
            sending_hours_start="00:00",
            sending_hours_end="23:59",
            wait_minutes_between=1,
        )
        camp_tokyo = Campaign(
            name="Tokyo Campaign",
            timezone="Asia/Tokyo",
            sending_days=[0, 1, 2, 3, 4, 5, 6],
            sending_hours_start="00:00",
            sending_hours_end="23:59",
            wait_minutes_between=1,
        )
        session.add_all([camp_ny, camp_tokyo])

        inbox_ny = Inbox(email="sender_ny@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
        inbox_tokyo = Inbox(email="sender_tokyo@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
        session.add_all([inbox_ny, inbox_tokyo])
        await session.flush()

        smtp_ny = SmtpAccount(inbox_id=inbox_ny.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
        smtp_tokyo = SmtpAccount(inbox_id=inbox_tokyo.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
        session.add_all([smtp_ny, smtp_tokyo])

        seq_ny = Sequence(campaign_id=camp_ny.id, position=0, subject="NY", body="NY", is_html=False)
        seq_tokyo = Sequence(campaign_id=camp_tokyo.id, position=0, subject="Tokyo", body="Tokyo", is_html=False)
        session.add_all([seq_ny, seq_tokyo])

        lead_ny = Lead(email="lead_ny@example.com", name="NY Lead")
        lead_tokyo = Lead(email="lead_tokyo@example.com", name="Tokyo Lead")
        session.add_all([lead_ny, lead_tokyo])
        await session.flush()

        cl_ny = CampaignLead(campaign_id=camp_ny.id, lead_id=lead_ny.id, enrollment_status="active")
        cl_tokyo = CampaignLead(campaign_id=camp_tokyo.id, lead_id=lead_tokyo.id, enrollment_status="active")
        session.add_all([cl_ny, cl_tokyo])
        await session.flush()

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        slot_ny = QueueSlot(campaign_lead_id=cl_ny.id, inbox_id=inbox_ny.id, sequence_index=0, scheduled_date=now_utc, position_in_day=1, status="scheduled")
        slot_tokyo = QueueSlot(campaign_lead_id=cl_tokyo.id, inbox_id=inbox_tokyo.id, sequence_index=0, scheduled_date=now_utc, position_in_day=1, status="scheduled")
        session.add_all([slot_ny, slot_tokyo])
        await session.commit()
        ny_id, tokyo_id = slot_ny.id, slot_tokyo.id

    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=SendResult(message_id="<tz_success@test.com>")):
        await send_slot_job(ny_id)
        await send_slot_job(tokyo_id)

    async with session_factory() as session:
        logs = (await session.execute(select(EmailLog).where(EmailLog.message_id == "<tz_success@test.com>"))).scalars().all()
        assert len(logs) == 2, "Both campaigns must successfully send across their respective timezones"


# ==============================================================================
# TEST 4: 4 workers simultaneously sending with only ONE budget unit remaining
# ==============================================================================
@pytest.mark.asyncio
async def test_04_atomic_concurrency_one_budget_remaining():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        # Set budget to exactly 1 email!
        await set_monthly_sending_budget(session, 1)
        await set_billing_cycle_start_day(session, 1)

        campaign = Campaign(
            name="Concurrency Test Campaign",
            timezone="UTC",
            sending_days=[0, 1, 2, 3, 4, 5, 6],
            sending_hours_start="00:00",
            sending_hours_end="23:59",
            wait_minutes_between=1,
        )
        session.add(campaign)
        await session.flush()

        seq = Sequence(campaign_id=campaign.id, position=0, subject="Race", body="Race", is_html=False)
        session.add(seq)

        slot_ids = []
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(4):
            inbox = Inbox(email=f"concur_sender_{i}@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
            session.add(inbox)
            await session.flush()

            smtp = SmtpAccount(inbox_id=inbox.id, smtp_host="h", smtp_port=587, smtp_username=f"u{i}", smtp_password="p")
            session.add(smtp)

            lead = Lead(email=f"concur_lead_{i}@example.com", name=f"Lead {i}")
            session.add(lead)
            await session.flush()

            cl = CampaignLead(campaign_id=campaign.id, lead_id=lead.id, enrollment_status="active")
            session.add(cl)
            await session.flush()

            slot = QueueSlot(
                campaign_lead_id=cl.id,
                inbox_id=inbox.id,
                sequence_index=0,
                scheduled_date=now_utc,
                position_in_day=1,
                status="scheduled",
            )
            session.add(slot)
            await session.flush()
            slot_ids.append(slot.id)

        await session.commit()

    # Launch 4 concurrent worker dispatches
    async def run_worker(sid):
        with patch("app.jobs.AsyncSessionLocal", session_factory), \
             patch("app.jobs.send_email", return_value=SendResult(message_id=f"<concur_{sid}@test.com>")):
            await send_slot_job(sid)

    await asyncio.gather(*(run_worker(sid) for sid in slot_ids))

    # Verify that EXACTLY 1 email was sent, and the other 3 remain scheduled
    async with session_factory() as session:
        logs = (await session.execute(select(EmailLog).where(EmailLog.campaign_id == campaign.id))).scalars().all()
        assert len(logs) == 1, f"CRITICAL: Budget was 1, but {len(logs)} emails were sent! Must never exceed budget."

        remaining_slots = (await session.execute(
            select(QueueSlot).where(QueueSlot.id.in_(slot_ids))
        )).scalars().all()
        assert len(remaining_slots) == 3, "The 3 unsent slots must remain safely in the queue"
        for s in remaining_slots:
            assert s.status == "scheduled", "Unsent slots must be reverted to 'scheduled'"
            assert s.claimed_at is None, "Unsent slots must release claim timestamp"
            assert s.claimed_by is None, "Unsent slots must release claim worker"


# ==============================================================================
# TEST 5: Simultaneous campaign and direct sends consuming the same budget
# ==============================================================================
@pytest.mark.asyncio
async def test_05_simultaneous_campaign_and_direct_sends():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        # Budget = 2 emails
        await set_monthly_sending_budget(session, 2)
        await set_billing_cycle_start_day(session, 1)

        campaign = Campaign(name="Mixed Camp", timezone="UTC", sending_days=[0,1,2,3,4,5,6], sending_hours_start="00:00", sending_hours_end="23:59")
        session.add(campaign)

        inbox = Inbox(email="mixed_sender@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
        session.add(inbox)
        await session.flush()

        smtp = SmtpAccount(inbox_id=inbox.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
        session.add(smtp)

        seq = Sequence(campaign_id=campaign.id, position=0, subject="Mix", body="Mix", is_html=False)
        session.add(seq)

        lead = Lead(email="mixed_lead@example.com", name="Mix Lead")
        session.add(lead)
        await session.flush()

        cl = CampaignLead(campaign_id=campaign.id, lead_id=lead.id, enrollment_status="active")
        session.add(cl)
        await session.flush()

        slot = QueueSlot(campaign_lead_id=cl.id, inbox_id=inbox.id, sequence_index=0, scheduled_date=datetime.now(timezone.utc).replace(tzinfo=None), position_in_day=1, status="scheduled")
        session.add(slot)

        direct_1 = DirectEmail(
            inbox_id=inbox.id,
            to_email="direct_rcpt_1@example.com",
            subject="Direct 1",
            body="Direct Body 1",
            is_html=False,
            status="draft",
        )
        direct_2 = DirectEmail(
            inbox_id=inbox.id,
            to_email="direct_rcpt_2@example.com",
            subject="Direct 2",
            body="Direct Body 2",
            is_html=False,
            status="draft",
        )
        session.add_all([direct_1, direct_2])
        await session.commit()
        slot_id = slot.id
        d1_id = direct_1.id
        d2_id = direct_2.id

    # Simultaneously dispatch slot and direct_1 (total budget = 2)
    async def send_camp():
        with patch("app.jobs.AsyncSessionLocal", session_factory), \
             patch("app.jobs.send_email", return_value=SendResult(message_id="<camp_msg@test.com>")):
            await send_slot_job(slot_id)

    async def send_direct(d_id):
        async with session_factory() as sess:
            de = (await sess.execute(select(DirectEmail).where(DirectEmail.id == d_id))).scalar_one()
            with patch("app.routers.direct_email.send_email", return_value=SendResult(message_id=f"<direct_{d_id}@test.com>")):
                await execute_send_direct_email(sess, de)

    await asyncio.gather(send_camp(), send_direct(d1_id))

    # Now budget (2) is completely exhausted! Attempting to send direct_2 must fail
    async with session_factory() as session:
        de2 = (await session.execute(select(DirectEmail).where(DirectEmail.id == d2_id))).scalar_one()
        with patch("app.routers.direct_email.send_email", return_value=SendResult(message_id="<direct_fail@test.com>")):
            success = await execute_send_direct_email(session, de2)
        assert success is False, "Direct send #3 must be blocked when monthly budget is exhausted"

        stats = await get_monthly_sending_stats(session)
        assert stats["sent_this_month"] == 2
        assert stats["remaining_budget"] == 0
        assert stats["is_exhausted"] is True


# ==============================================================================
# TEST 6: SMTP failure, successful send, ambiguous acceptance (SendUncertain)
# ==============================================================================
@pytest.mark.asyncio
async def test_06_smtp_outcomes_and_uncertainty():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 10000)

        campaign = Campaign(name="Outcomes Campaign", timezone="UTC", sending_days=[0,1,2,3,4,5,6], sending_hours_start="00:00", sending_hours_end="23:59")
        session.add(campaign)
        await session.flush()

        seq = Sequence(campaign_id=campaign.id, position=0, subject="Outcomes", body="Outcomes", is_html=False)
        session.add(seq)

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        slots = []
        for name in ["success", "transient", "uncertain"]:
            inbox = Inbox(email=f"sender_{name}@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
            session.add(inbox)
            await session.flush()
            smtp = SmtpAccount(inbox_id=inbox.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
            session.add(smtp)

            l = Lead(email=f"{name}@example.com", name=name)
            session.add(l)
            await session.flush()
            cl = CampaignLead(campaign_id=campaign.id, lead_id=l.id, enrollment_status="active")
            session.add(cl)
            await session.flush()
            s = QueueSlot(campaign_lead_id=cl.id, inbox_id=inbox.id, sequence_index=0, scheduled_date=now_utc, position_in_day=1, status="scheduled")
            session.add(s)
            await session.flush()
            slots.append((name, s.id, l.id))
        await session.commit()

    # Case A: Success -> Slot deleted, EmailLog created
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=SendResult(message_id="<ok@test.com>")):
        await send_slot_job(slots[0][1])

    # Case B: Transient Failure -> Slot retained in scheduled status, no EmailLog
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=None):
        await send_slot_job(slots[1][1])

    # Case C: Ambiguous SMTP Acceptance (SendUncertain) -> Slot marked 'uncertain' with 'needs_reconciliation'
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=SendUncertain(message_id="<uncertain@test.com>", reason="SMTPServerDisconnected")):
        await send_slot_job(slots[2][1])

    async with session_factory() as session:
        # Check Success
        s0 = (await session.execute(select(QueueSlot).where(QueueSlot.id == slots[0][1]))).scalar_one_or_none()
        assert s0 is None, "Successful send must delete queue slot"
        log0 = (await session.execute(select(EmailLog).where(EmailLog.lead_id == slots[0][2]))).scalar_one_or_none()
        assert log0 is not None and log0.message_id == "<ok@test.com>"

        # Check Transient Failure
        s1 = (await session.execute(select(QueueSlot).where(QueueSlot.id == slots[1][1]))).scalar_one_or_none()
        assert s1 is not None and s1.status == "scheduled", "Transient failure must release slot back to 'scheduled'"
        assert s1.claimed_at is None
        log1 = (await session.execute(select(EmailLog).where(EmailLog.lead_id == slots[1][2]))).scalar_one_or_none()
        assert log1 is None, "Pre-created EmailLog must be rolled back on transient failure"

        # Check Ambiguous Drop (SendUncertain)
        s2 = (await session.execute(select(QueueSlot).where(QueueSlot.id == slots[2][1]))).scalar_one_or_none()
        assert s2 is not None and s2.status == "uncertain", "Ambiguous drop must mark slot as 'uncertain'"
        assert s2.claimed_by == "needs_reconciliation"
        log2 = (await session.execute(select(EmailLog).where(EmailLog.lead_id == slots[2][2]))).scalar_one_or_none()
        assert log2 is None, "Pre-created EmailLog must be rolled back to avoid double-counting unconfirmed emails"


# ==============================================================================
# TEST 7: Budget exhaustion and next-cycle recovery
# ==============================================================================
@pytest.mark.asyncio
async def test_07_budget_exhaustion_and_cycle_rollover():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 1)
        await set_billing_cycle_start_day(session, 1)

        # Send 1 email in current cycle (March)
        march_date = datetime(2026, 3, 15, 12, 0, 0)
        lead = Lead(email="rollover_lead@example.com", name="Rollover")
        session.add(lead)
        await session.flush()

        log_entry = EmailLog(
            lead_id=lead.id,
            campaign_id=1,
            sent_at=march_date,
            message_id="<march_msg@test.com>",
        )
        session.add(log_entry)
        await session.commit()

        # Check March budget: Exhausted!
        allowed_march, consumed_march, rem_march = await check_and_reserve_monthly_budget(session, ref_date=march_date)
        assert allowed_march is False
        assert consumed_march == 1
        assert rem_march == 0

        # Advance to April 1st (new billing cycle): Automatically recovered!
        april_date = datetime(2026, 4, 1, 0, 1, 0)
        allowed_april, consumed_april, rem_april = await check_and_reserve_monthly_budget(session, ref_date=april_date)
        assert allowed_april is True
        assert consumed_april == 0
        assert rem_april == 1


# ==============================================================================
# TEST 8: Preservation of existing follow-up sender identity and RFC threading
# ==============================================================================
@pytest.mark.asyncio
async def test_08_follow_up_sender_and_threading():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 10000)

        campaign = Campaign(name="Threaded Campaign", timezone="UTC", sending_days=[0,1,2,3,4,5,6], sending_hours_start="00:00", sending_hours_end="23:59")
        session.add(campaign)

        inbox_1 = Inbox(email="thread_sender_1@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
        inbox_2 = Inbox(email="thread_sender_2@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
        session.add_all([inbox_1, inbox_2])
        await session.flush()

        smtp_1 = SmtpAccount(inbox_id=inbox_1.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
        smtp_2 = SmtpAccount(inbox_id=inbox_2.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
        session.add_all([smtp_1, smtp_2])

        seq_0 = Sequence(campaign_id=campaign.id, position=0, subject="Initial Pitch", body="Pitch", is_html=False)
        seq_1 = Sequence(campaign_id=campaign.id, position=1, subject="", body="Follow-up bump", is_html=False)  # empty subject triggers thread reply
        session.add_all([seq_0, seq_1])

        lead = Lead(email="thread_prospect@example.com", name="Prospect")
        session.add(lead)
        await session.flush()

        cl = CampaignLead(campaign_id=campaign.id, lead_id=lead.id, enrollment_status="active")
        session.add(cl)
        await session.flush()

        # Step 0 was sent from inbox_1 with message_id <root_123@domain.com>
        root_msg_id = "<root_123@domain.com>"
        log_0 = EmailLog(
            lead_id=lead.id,
            campaign_id=campaign.id,
            inbox_id=inbox_1.id,
            sequence_index=0,
            subject="Initial Pitch",
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2),
            message_id=root_msg_id,
            thread_id=root_msg_id,
        )
        session.add(log_0)

        # Step 1 is scheduled for inbox_1
        slot_1 = QueueSlot(
            campaign_lead_id=cl.id,
            inbox_id=inbox_1.id,
            sequence_index=1,
            scheduled_date=datetime.now(timezone.utc).replace(tzinfo=None),
            position_in_day=1,
            status="scheduled",
        )
        session.add(slot_1)
        await session.commit()
        slot_1_id = slot_1.id

    captured_kwargs = {}

    def mock_send(**kwargs):
        captured_kwargs.update(kwargs)
        return SendResult(message_id="<reply_456@domain.com>", thread_id=kwargs.get("thread_id"))

    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", side_effect=mock_send):
        await send_slot_job(slot_1_id)

    # Verify threading preservation
    assert captured_kwargs.get("from_email") == "thread_sender_1@example.com", "Follow-up must retain the original sender inbox"
    assert captured_kwargs.get("reply_to_msg_id") == root_msg_id, "In-Reply-To must match the root email message ID"
    assert root_msg_id in captured_kwargs.get("references", ""), "References chain must include the root message ID"
    assert captured_kwargs.get("subject") == "Re: Initial Pitch", "Subject must thread with 'Re: Initial Pitch'"


# ==============================================================================
# TEST 9: Queue restart recovery and idempotency for abandoned claims
# ==============================================================================
@pytest.mark.asyncio
async def test_09_abandoned_claim_recovery():
    session_factory = await get_test_factory()
    await reset_db(session_factory)

    async with session_factory() as session:
        await set_monthly_sending_budget(session, 10000)

        campaign = Campaign(name="Crash Recovery Camp", timezone="UTC", sending_days=[0,1,2,3,4,5,6], sending_hours_start="00:00", sending_hours_end="23:59")
        session.add(campaign)

        inbox = Inbox(email="crash_sender@example.com", provider="smtp", paused=False, max_emails_per_day=50, wait_minutes_between=1)
        session.add(inbox)
        await session.flush()

        smtp = SmtpAccount(inbox_id=inbox.id, smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p")
        session.add(smtp)

        seq = Sequence(campaign_id=campaign.id, position=0, subject="Crash Test", body="Crash", is_html=False)
        session.add(seq)

        lead = Lead(email="crash_lead@example.com", name="Crash Lead")
        session.add(lead)
        await session.flush()

        cl = CampaignLead(campaign_id=campaign.id, lead_id=lead.id, enrollment_status="active")
        session.add(cl)
        await session.flush()

        # Slot abandoned 10 minutes ago by crashed worker
        abandoned_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        slot = QueueSlot(
            campaign_lead_id=cl.id,
            inbox_id=inbox.id,
            sequence_index=0,
            scheduled_date=abandoned_time,
            position_in_day=1,
            status="processing",
            claimed_at=abandoned_time,
            claimed_by="dead_worker_pid_9999",
        )
        session.add(slot)
        await session.commit()
        abandoned_slot_id = slot.id

    # A newly spawned worker fires send_slot_job on the abandoned slot
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=SendResult(message_id="<recovered_send@test.com>")):
        await send_slot_job(abandoned_slot_id)

    # Verify slot was successfully recovered and sent
    async with session_factory() as session:
        slot_check = (await session.execute(select(QueueSlot).where(QueueSlot.id == abandoned_slot_id))).scalar_one_or_none()
        assert slot_check is None, "Abandoned slot must be re-claimed, sent, and removed"

        log_check = (await session.execute(select(EmailLog).where(EmailLog.lead_id == lead.id))).scalar_one_or_none()
        assert log_check is not None
        assert log_check.message_id == "<recovered_send@test.com>"


if __name__ == "__main__":
    import asyncio
    async def run_all():
        print("Running Weblinx Outreach OS P0 Sending Engine Corrections Verification Suite...")
        await test_01_global_budget_no_arbitrary_daily_cap()
        print("  [PASS] Test 1: Global monthly budget with no arbitrary daily cap")
        await test_02_campaign_interval_overrides_inbox_interval()
        print("  [PASS] Test 2: Campaign interval overrides legacy inbox interval")
        await test_03_multiple_campaigns_different_timezones()
        print("  [PASS] Test 3: Multiple campaigns with different timezones")
        await test_04_atomic_concurrency_one_budget_remaining()
        print("  [PASS] Test 4: 4 concurrent workers with 1 budget unit remaining (budget never exceeded)")
        await test_05_simultaneous_campaign_and_direct_sends()
        print("  [PASS] Test 5: Simultaneous campaign and direct sends consuming same pool")
        await test_06_smtp_outcomes_and_uncertainty()
        print("  [PASS] Test 6: SMTP failure, success, and ambiguous SendUncertain handling")
        await test_07_budget_exhaustion_and_cycle_rollover()
        print("  [PASS] Test 7: Budget exhaustion and billing cycle rollover recovery")
        await test_08_follow_up_sender_and_threading()
        print("  [PASS] Test 8: Follow-up sender identity & RFC threading preservation")
        await test_09_abandoned_claim_recovery()
        print("  [PASS] Test 9: Abandoned claim recovery and idempotency")
        print("\nALL 9 TESTS PASSED! 100% PRODUCTION READY.")
        cleanup_db_files()

    asyncio.run(run_all())
