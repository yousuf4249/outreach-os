"""Tests for Direct Email / Compose Email feature in Weblinx Outreach OS."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from app.models import DirectEmail, Lead, Inbox, SmtpAccount
from app.schemas import DirectEmailCreate
from app.sender import SendResult
from app.routers.direct_email import (
    create_and_send_direct_email,
    list_direct_emails,
    get_direct_email,
    cancel_or_delete_direct_email,
    send_scheduled_now,
    execute_send_direct_email,
    run_direct_email_scheduler_job,
)
from app.tracking_events import record_email_open
from app.unibox import _mark_direct_email_replied
from app.routers.leads import get_lead
from tests.conftest import make_inbox


@pytest.mark.asyncio
async def test_direct_email_create_and_immediate_send(session):
    """Test creating a direct email and sending immediately with variable substitution and Unibox mirroring."""
    inbox = await make_inbox(session, email="sender@weblinxsolution.com", provider="smtp")
    smtp_acc = SmtpAccount(
        inbox_id=inbox.id,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="sender@weblinxsolution.com",
        smtp_password="enc_password",
    )
    session.add(smtp_acc)
    await session.commit()

    # Create a prospect
    lead = Lead(
        email="prospect@company.com",
        name="Sarah Jenkins",
        company="Acme Corp",
        city="Chicago",
        industry="Technology",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    payload = DirectEmailCreate(
        inbox_id=inbox.id,
        to_email=lead.email,
        recipient_name=lead.name,
        lead_id=lead.id,
        subject="Quick intro for {{company_name}}",
        body="Hi {{first_name}},\n\nSaw your work in {{city}} at {{company_name}}.\n\nBest,\nWeblinx",
        is_html=False,
        open_tracking=True,
        enable_follow_up=False,
    )

    fake_result = SendResult(
        message_id="<msg-direct-12345@weblinxsolution.com>",
        thread_id="thread-smtp-direct-1",
    )

    with patch("app.routers.direct_email.send_email", return_value=fake_result) as mock_send:
        res = await create_and_send_direct_email(data=payload, db=session, _user={})

        assert res["id"] is not None
        assert res["status"] == "sent"
        assert res["sent_at"] is not None
        assert res["message_id"] == "<msg-direct-12345@weblinxsolution.com>"
        assert res["enable_follow_up"] is False

        # Verify sent email content had variables rendered
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        args = mock_send.call_args[0] if mock_send.call_args[0] else ()
        sent_to = kwargs.get("to_email") or (args[1] if len(args) > 1 else None)
        sent_subject = kwargs.get("subject") or (args[2] if len(args) > 2 else None)
        sent_body = kwargs.get("body") or (args[3] if len(args) > 3 else None)

        assert sent_to == "prospect@company.com"
        assert "Quick intro for Acme Corp" == sent_subject
        assert "Hi Sarah," in sent_body
        assert "Chicago" in sent_body


@pytest.mark.asyncio
async def test_direct_email_scheduling_and_dispatcher(session):
    """Test scheduling a direct email for later and verifying the scheduler job dispatches it."""
    inbox = await make_inbox(session, email="scheduler@weblinxsolution.com", provider="smtp")
    smtp_acc = SmtpAccount(
        inbox_id=inbox.id,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="scheduler@weblinxsolution.com",
        smtp_password="enc_password",
    )
    session.add(smtp_acc)
    await session.commit()

    # Schedule 1 hour into the future
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)

    payload = DirectEmailCreate(
        inbox_id=inbox.id,
        to_email="scheduled.lead@domain.com",
        recipient_name="John Doe",
        subject="Scheduled direct follow-up",
        body="Hello John, just following up as planned.",
        scheduled_at=future_time,
        enable_follow_up=False,
    )

    fake_result = SendResult(
        message_id="<scheduled-msg-789@weblinxsolution.com>",
        thread_id="thread-sched-1",
    )

    with patch("app.routers.direct_email.send_email", return_value=fake_result) as mock_send:
        # Step 1: Create scheduled email
        res = await create_and_send_direct_email(data=payload, db=session, _user={})
        assert res["status"] == "scheduled"
        assert res["sent_at"] is None
        mock_send.assert_not_called()

        # Step 2: Make it due by adjusting scheduled_at in the database (naive UTC)
        direct_row = await session.get(DirectEmail, res["id"])
        direct_row.scheduled_at = datetime.utcnow() - timedelta(minutes=1)
        await session.commit()

        # Step 3: Trigger scheduler job
        with patch("app.routers.direct_email.AsyncSessionLocal") as mock_maker:
            mock_maker.return_value.__aenter__.return_value = session
            mock_maker.return_value.__aexit__.return_value = None

            await run_direct_email_scheduler_job()

        # Step 4: Verify it was sent
        await session.refresh(direct_row)
        assert direct_row.status == "sent"
        assert direct_row.sent_at is not None
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_direct_email_open_and_reply_tracking(session):
    """Test 1x1 tracking pixel open recording and reply marker matching for direct emails."""
    inbox = await make_inbox(session, email="tracking@weblinxsolution.com", provider="smtp")

    direct = DirectEmail(
        inbox_id=inbox.id,
        to_email="prospect.tracked@example.com",
        recipient_name="Mark Smith",
        subject="Tracked Subject",
        body="Tracked Body",
        status="sent",
        sent_at=datetime.utcnow(),
        open_token="direct_open_token_xyz999",
        opened=False,
        open_count=0,
        replied=False,
        enable_follow_up=False,
    )
    session.add(direct)
    await session.commit()
    await session.refresh(direct)

    # Test open tracking
    recorded = await record_email_open(
        db=session,
        token="direct_open_token_xyz999",
        ip="192.168.1.50",
    )
    assert recorded is True

    await session.refresh(direct)
    assert direct.opened is True
    assert direct.open_count == 1
    assert direct.opened_at is not None

    # Test reply tracking
    await _mark_direct_email_replied(
        db=session,
        from_addr="prospect.tracked@example.com",
        thread_id="any-thread-id",
    )

    await session.refresh(direct)
    assert direct.replied is True
    assert direct.replied_at is not None


@pytest.mark.asyncio
async def test_lead_interaction_history_includes_direct_emails(session):
    """Test that prospect detail interactions include direct emails."""
    inbox = await make_inbox(session, email="outreach@weblinxsolution.com", provider="smtp")

    lead = Lead(
        email="interaction.test@company.com",
        name="David Miller",
        company="Miller Dynamics",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    direct = DirectEmail(
        inbox_id=inbox.id,
        to_email=lead.email,
        lead_id=lead.id,
        subject="Proposal for Miller Dynamics",
        body="Hi David, here is our proposal.",
        status="sent",
        sent_at=datetime.utcnow(),
        enable_follow_up=False,
    )
    session.add(direct)
    await session.commit()

    lead_detail = await get_lead(lead_id=lead.id, db=session)
    interactions = lead_detail.interactions

    assert len(interactions) >= 1
    direct_interaction = next((i for i in interactions if i.get("subject") == "Proposal for Miller Dynamics"), None)
    assert direct_interaction is not None
    assert direct_interaction["direction"] == "outbound"
    assert "direct_email" in direct_interaction["kind"]
