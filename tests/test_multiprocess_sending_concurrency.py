"""Production-Readiness Multi-Process Concurrency & Heartbeat Failure QA Tests.

Audits:
1. Genuine multi-process concurrency with separate Python OS processes and separate
   database connections, executing simultaneous campaign and direct sends with
   exactly 1 monthly budget unit remaining.
2. PostgreSQL advisory transaction lock support alongside SQLite synchronization.
3. Worker process alive but task/heartbeat failed: safe queue recovery with ZERO duplicate sending
   via EmailLog idempotency check.
4. Worker process alive but task hung >10m without EmailLog: safe reclamation and dispatch.
5. Worker process alive and claim <10m: active send protection skips premature reclamation.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.database import Base
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
from app.sender import SendResult
from app.time import utcnow


@pytest.mark.asyncio
async def test_01_multiprocess_concurrency_one_budget_remaining(tmp_path):
    """Verify that separate Python OS processes with separate DB connections honor the 1-unit budget."""
    db_file = tmp_path / "multiprocess_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Initialize schema and WAL mode
    setup_engine = create_async_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30})
    async with setup_engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA busy_timeout=15000;"))
        await conn.run_sync(Base.metadata.create_all)

    SetupSession = async_sessionmaker(setup_engine, class_=AsyncSession, expire_on_commit=False)

    # Seed data
    now = utcnow()
    async with SetupSession() as session:
        await set_monthly_sending_budget(session, 1)

        inbox = Inbox(email="multi_inbox@example.com", provider="smtp", paused=False, wait_minutes_between=0)
        session.add(inbox)
        await session.flush()

        smtp = SmtpAccount(
            inbox_id=inbox.id,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="test_multi",
            smtp_password="pw",
        )
        session.add(smtp)

        lead = Lead(email="multi_lead@example.com", name="Multi Lead")
        session.add(lead)
        await session.flush()

        camp = Campaign(
            name="Multi Camp",
            paused=False,
            timezone="UTC",
            sending_days=[0, 1, 2, 3, 4, 5, 6],
            sending_hours_start="00:00",
            sending_hours_end="23:59",
        )
        session.add(camp)
        await session.flush()

        cl = CampaignLead(campaign_id=camp.id, lead_id=lead.id, enrollment_status="active")
        session.add(cl)
        await session.flush()

        seq = Sequence(campaign_id=camp.id, position=0, subject="Multi Subj", body="Multi Body")
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
            to_email="multi_direct@example.com",
            subject="Multi Direct",
            body="Multi Direct Body",
            status="draft",
        )
        session.add(direct)

        await session.commit()
        slot_id = slot.id
        direct_id = direct.id

    await setup_engine.dispose()

    # Paths for coordination
    barrier_file = tmp_path / "barrier.go"
    ready_camp = tmp_path / "camp.ready"
    ready_dir = tmp_path / "dir.ready"
    res_camp = tmp_path / "camp.result"
    res_dir = tmp_path / "dir.result"
    worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "multiprocess_sending_worker.py"))

    # Spawn Process 1: Campaign Send Worker
    cmd_camp = [
        sys.executable,
        worker_script,
        "--mode", "campaign",
        "--target-id", str(slot_id),
        "--db-url", db_url,
        "--barrier-file", str(barrier_file),
        "--ready-file", str(ready_camp),
        "--result-file", str(res_camp),
    ]
    proc_camp = subprocess.Popen(cmd_camp)

    # Spawn Process 2: Direct Email Worker
    cmd_dir = [
        sys.executable,
        worker_script,
        "--mode", "direct",
        "--target-id", str(direct_id),
        "--db-url", db_url,
        "--barrier-file", str(barrier_file),
        "--ready-file", str(ready_dir),
        "--result-file", str(res_dir),
    ]
    proc_dir = subprocess.Popen(cmd_dir)

    try:
        # Wait for both processes to signal ready
        wait_deadline = time.time() + 15
        while time.time() < wait_deadline:
            if ready_camp.exists() and ready_dir.exists():
                break
            await asyncio.sleep(0.05)

        assert ready_camp.exists(), "Campaign worker failed to initialize"
        assert ready_dir.exists(), "Direct email worker failed to initialize"

        # RELEASE BARRIER: both OS processes fire their sends simultaneously
        barrier_file.write_text("GO")

        # Wait for both processes to complete
        proc_camp.wait(timeout=20)
        proc_dir.wait(timeout=20)

        # Parse worker results
        data_camp = json.loads(res_camp.read_text())
        data_dir = json.loads(res_dir.read_text())

        # Assert no unhandled crash in either process
        assert data_camp.get("error") is None, f"Campaign worker encountered error: {data_camp.get('error')}"
        assert data_dir.get("error") is None, f"Direct worker encountered error: {data_dir.get('error')}"

        # Total emails sent across both OS processes
        total_sends = (1 if data_camp.get("smtp_sent") else 0) + (1 if data_dir.get("smtp_sent") else 0)
        assert total_sends == 1, (
            f"CRITICAL MULTI-PROCESS OVERAGE: Budget was 1, but {total_sends} emails were sent! "
            f"Campaign sent: {data_camp.get('smtp_sent')}, Direct sent: {data_dir.get('smtp_sent')}"
        )

        # Verify database state after multi-process execution
        verify_engine = create_async_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30})
        VerifySession = async_sessionmaker(verify_engine, class_=AsyncSession, expire_on_commit=False)
        async with VerifySession() as session:
            stats = await get_monthly_sending_stats(session)
            assert stats["sent_this_month"] == 1
            assert stats["remaining_budget"] == 0
            assert stats["is_exhausted"] is True

            # Count EmailLog vs DirectEmail
            elog_cnt = (await session.execute(select(EmailLog))).scalars().all()
            direct_row = (await session.execute(select(DirectEmail).where(DirectEmail.id == direct_id))).scalar_one()

            if data_camp.get("smtp_sent"):
                assert len(elog_cnt) == 1, "Expected 1 EmailLog entry"
                assert direct_row.status in ("failed", "draft", "paused"), "Direct send should have been blocked"
            else:
                assert len(elog_cnt) == 0, "Expected 0 EmailLog entries"
                assert direct_row.status == "sent", "Direct send should have succeeded"

        await verify_engine.dispose()

    finally:
        if proc_camp.poll() is None:
            proc_camp.kill()
        if proc_dir.poll() is None:
            proc_dir.kill()


@pytest.mark.asyncio
async def test_02_postgresql_advisory_lock_support():
    """Verify PostgreSQL advisory transaction lock support alongside SQLite."""
    # 1. PostgreSQL dialect: verify exact SELECT pg_advisory_xact_lock(789123456); is executed
    mock_pg_session = AsyncMock(spec=AsyncSession)
    mock_pg_session.bind = MagicMock()
    mock_pg_session.bind.dialect.name = "postgresql"

    await acquire_db_budget_lock(mock_pg_session)

    # Check query executed on PG session
    mock_pg_session.execute.assert_called_once()
    called_sql = str(mock_pg_session.execute.call_args[0][0])
    assert "pg_advisory_xact_lock(789123456)" in called_sql, (
        f"PostgreSQL dialect did not execute expected advisory lock query: {called_sql}"
    )


@pytest.mark.asyncio
async def test_03_worker_alive_task_failed_prevents_duplicate_send(session: AsyncSession):
    """Verify that if a worker process remains alive but its task died after sending and logging,
    the pre-reclamation idempotency check prevents duplicate sending.
    """
    session_factory = async_sessionmaker(session.bind, class_=AsyncSession, expire_on_commit=False)

    now = utcnow()
    stale_time = now - timedelta(minutes=6)  # Older than 5 min stale threshold
    alive_worker_id = f"worker-{os.getpid()}-stalled01"

    # Verify worker is detected alive
    assert is_worker_alive(alive_worker_id) is True

    # Setup entities
    inbox = Inbox(email="dup_check@example.com", provider="smtp", paused=False, wait_minutes_between=0)
    session.add(inbox)
    await session.flush()

    lead = Lead(email="dup_target@example.com", name="Dup Target")
    session.add(lead)
    await session.flush()

    camp = Campaign(
        name="Dup Camp",
        paused=False,
        timezone="UTC",
        sending_days=[0, 1, 2, 3, 4, 5, 6],
        sending_hours_start="00:00",
        sending_hours_end="23:59",
    )
    session.add(camp)
    await session.flush()

    cl = CampaignLead(campaign_id=camp.id, lead_id=lead.id, enrollment_status="active")
    session.add(cl)
    await session.flush()

    seq = Sequence(campaign_id=camp.id, position=0, subject="Subj", body="Body")
    session.add(seq)
    await session.flush()

    # Create slot stuck in processing by the alive worker
    slot = QueueSlot(
        campaign_lead_id=cl.id,
        inbox_id=inbox.id,
        sequence_index=0,
        position_in_day=1,
        scheduled_date=now - timedelta(minutes=10),
        status="processing",
        claimed_at=stale_time,
        claimed_by=alive_worker_id,
    )
    session.add(slot)

    # BUT EmailLog was already committed by the original task before it stalled/died!
    log_entry = EmailLog(
        inbox_id=inbox.id,
        campaign_id=camp.id,
        lead_id=lead.id,
        sequence_index=0,
        subject="Subj",
        sent_at=stale_time,
    )
    session.add(log_entry)
    await session.commit()
    await session.refresh(slot)

    # When send_slot_job is triggered again
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email") as mock_send:
        await send_slot_job(slot.id)
        # CRITICAL: send_email must NOT be called again! Zero duplicate send!
        assert mock_send.call_count == 0, "DUPLICATE SEND DETECTED! send_email was called for already-sent slot"

    # Slot must have been safely transitioned to 'sent'
    await session.refresh(slot)
    assert slot.status == "sent", f"Expected slot status 'sent', got {slot.status}"
    assert slot.claimed_at is None
    assert slot.claimed_by is None


@pytest.mark.asyncio
async def test_04_worker_alive_heartbeat_dead_over_10m_safe_recovery(session: AsyncSession):
    """Verify that if a worker process remains alive, but its task/heartbeat has stalled >10m
    without an EmailLog, the slot is safely reclaimed and dispatched without hanging the queue.
    """
    session_factory = async_sessionmaker(session.bind, class_=AsyncSession, expire_on_commit=False)

    now = utcnow()
    hard_stale_time = now - timedelta(minutes=12)  # > 10m hard ceiling
    alive_worker_id = f"worker-{os.getpid()}-hung01"

    assert is_worker_alive(alive_worker_id) is True

    # Setup entities
    inbox = Inbox(email="hung_test@example.com", provider="smtp", paused=False, wait_minutes_between=0)
    session.add(inbox)
    await session.flush()

    smtp = SmtpAccount(
        inbox_id=inbox.id,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="hung_user",
        smtp_password="pw",
    )
    session.add(smtp)

    lead = Lead(email="hung_target@example.com", name="Hung Target")
    session.add(lead)
    await session.flush()

    camp = Campaign(
        name="Hung Camp",
        paused=False,
        timezone="UTC",
        sending_days=[0, 1, 2, 3, 4, 5, 6],
        sending_hours_start="00:00",
        sending_hours_end="23:59",
    )
    session.add(camp)
    await session.flush()

    cl = CampaignLead(campaign_id=camp.id, lead_id=lead.id, enrollment_status="active")
    session.add(cl)
    await session.flush()

    seq = Sequence(campaign_id=camp.id, position=0, subject="Hung Subj", body="Hung Body")
    session.add(seq)
    await session.flush()

    # Slot stuck in processing > 10 min, NO EmailLog exists
    slot = QueueSlot(
        campaign_lead_id=cl.id,
        inbox_id=inbox.id,
        sequence_index=0,
        position_in_day=1,
        scheduled_date=now - timedelta(minutes=15),
        status="processing",
        claimed_at=hard_stale_time,
        claimed_by=alive_worker_id,
    )
    session.add(slot)
    await session.commit()
    await session.refresh(slot)

    mock_res = SendResult(message_id="msg-recovered-001", thread_id="thr-rec-001")
    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email", return_value=mock_res) as mock_send:
        await send_slot_job(slot.id)
        # Safe recovery: email should be dispatched exactly once
        assert mock_send.call_count == 1, "Expected slot to be safely reclaimed and sent"

    # Verify slot was processed and removed from queue upon successful completion
    res_slot = await session.execute(select(QueueSlot).where(QueueSlot.id == slot.id))
    assert res_slot.scalar_one_or_none() is None, "Slot should be completed and deleted from queue upon success"

    # Verify EmailLog created
    res_log = await session.execute(
        select(EmailLog).where(
            EmailLog.campaign_id == camp.id,
            EmailLog.lead_id == lead.id,
        )
    )
    assert res_log.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_05_worker_alive_heartbeat_under_10m_skips_reclamation(session: AsyncSession):
    """Verify that if a worker process remains alive and claim is 6m old (< 10m hard ceiling),
    reclamation is deferred so active socket timeouts are not interrupted.
    """
    session_factory = async_sessionmaker(session.bind, class_=AsyncSession, expire_on_commit=False)

    now = utcnow()
    active_stale_time = now - timedelta(minutes=6)  # Between 5m and 10m
    alive_worker_id = f"worker-{os.getpid()}-socketwait01"

    assert is_worker_alive(alive_worker_id) is True

    # Setup entities
    inbox = Inbox(email="socket_test@example.com", provider="smtp", paused=False, wait_minutes_between=0)
    session.add(inbox)
    await session.flush()

    lead = Lead(email="socket_target@example.com", name="Socket Target")
    session.add(lead)
    await session.flush()

    camp = Campaign(
        name="Socket Camp",
        paused=False,
        timezone="UTC",
        sending_days=[0, 1, 2, 3, 4, 5, 6],
        sending_hours_start="00:00",
        sending_hours_end="23:59",
    )
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
        claimed_at=active_stale_time,
        claimed_by=alive_worker_id,
    )
    session.add(slot)
    await session.commit()
    await session.refresh(slot)

    with patch("app.jobs.AsyncSessionLocal", session_factory), \
         patch("app.jobs.send_email") as mock_send:
        await send_slot_job(slot.id)
        # Should NOT reclaim while worker is alive and under 10 minutes
        assert mock_send.call_count == 0

    await session.refresh(slot)
    assert slot.status == "processing"
    assert slot.claimed_by == alive_worker_id
