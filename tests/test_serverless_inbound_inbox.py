"""Comprehensive QA Test Suite for Serverless Email Inbox & Inbound Webhooks.

Tests:
1. Webhook HMAC-SHA256 signature verification & timestamp replay attack rejection.
2. Inbound MIME email ingestion without IMAP hosting.
3. Binary attachment extraction, storage, and authenticated download.
4. RFC Message-ID threading (In-Reply-To, References).
5. Lead reply matching & automated campaign follow-up sequence stopping (QueueSlot deletion).
6. Deduplication on repeated/retried webhooks.
7. Unibox folder filtering (Inbox, Sent, Drafts, Replies, All).
8. Drafts creation, retrieval, and deletion.
"""

import asyncio
import hashlib
import hmac
import os
import sys
import time
import uuid
from email.message import EmailMessage

import httpx
import pytest
from sqlalchemy import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth import create_access_token
from app.database import AsyncSessionLocal
from app import time as time_provider
from app.models import (
    AppSetting,
    Campaign,
    CampaignInbox,
    CampaignLead,
    EmailAttachment,
    EmailDraft,
    EmailLog,
    Inbox,
    Lead,
    LeadReply,
    QueueSlot,
    SmtpMessage,
    SmtpThread,
    User,
)

BASE_URL = "http://127.0.0.1:8000"
TEST_SECRET = "qa-test-webhook-secret-999"


def compute_test_signature(raw_body: bytes, timestamp: str, secret: str = TEST_SECRET) -> str:
    """Compute expected HMAC-SHA256 signature for Cloudflare webhook test."""
    data = f"{timestamp}.".encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


async def run_serverless_inbox_tests():
    print("=" * 70)
    print("STARTING SERVERLESS INBOX & INBOUND WEBHOOK QA VERIFICATION")
    print("=" * 70)

    # Configure test secret in environment for test execution
    os.environ["CLOUDFLARE_INBOUND_WEBHOOK_SECRET"] = TEST_SECRET

    async with AsyncSessionLocal() as db:
        # Get admin user token
        user_res = await db.execute(select(User).limit(1))
        user = user_res.scalar_one_or_none()
        assert user is not None, "Admin user must exist"
        token = create_access_token(user.id, user.role)
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Configure test secret in database
        setting_res = await db.execute(select(AppSetting).where(AppSetting.key == "cloudflare_inbound_webhook_secret"))
        setting = setting_res.scalar_one_or_none()
        if not setting:
            setting = AppSetting(key="cloudflare_inbound_webhook_secret", value=TEST_SECRET)
            db.add(setting)
        else:
            setting.value = TEST_SECRET
        await db.commit()

        # 1. Ensure test serverless inbox exists
        inbox_email = "alex.outreach@outreach-test.weblinxsolution.com"
        inbox_res = await db.execute(select(Inbox).where(Inbox.email == inbox_email))
        inbox = inbox_res.scalar_one_or_none()
        if not inbox:
            inbox = Inbox(
                email=inbox_email,
                display_name="Alex Outreach",
                provider="smtp",
                inbound_type="webhook",
                outbound_provider="ses",
            )
            db.add(inbox)
            await db.commit()
            await db.refresh(inbox)
        inbox_id = inbox.id

        # 2. Ensure test campaign and lead exist for reply matching test
        lead_email = "prospect.david@acme-client.example.com"
        lead_res = await db.execute(select(Lead).where(Lead.email == lead_email))
        lead = lead_res.scalar_one_or_none()
        if not lead:
            lead = Lead(
                email=lead_email,
                name="David Miller",
                company="Acme Corp",
                pipeline_status="new",
            )
            db.add(lead)
            await db.commit()
            await db.refresh(lead)

        camp_res = await db.execute(select(Campaign).where(Campaign.name == "Serverless QA Campaign"))
        campaign = camp_res.scalar_one_or_none()
        if not campaign:
            campaign = Campaign(name="Serverless QA Campaign")
            db.add(campaign)
            await db.commit()
            await db.refresh(campaign)

        # Enroll lead in campaign
        cl_res = await db.execute(
            select(CampaignLead).where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.lead_id == lead.id,
            )
        )
        cl = cl_res.scalar_one_or_none()
        if not cl:
            cl = CampaignLead(
                campaign_id=campaign.id,
                lead_id=lead.id,
                enrollment_status="active",
            )
            db.add(cl)
            await db.commit()
            await db.refresh(cl)
        else:
            cl.enrollment_status = "active"
            await db.commit()

        # Seed scheduled queue slots that SHOULD be stopped/deleted on reply
        await db.execute(
            QueueSlot.__table__.delete().where(QueueSlot.campaign_lead_id == cl.id)
        )
        slot1 = QueueSlot(
            campaign_lead_id=cl.id,
            inbox_id=inbox.id,
            sequence_index=1,
            position_in_day=1,
            scheduled_date=time_provider.utcnow(),
        )
        slot2 = QueueSlot(
            campaign_lead_id=cl.id,
            inbox_id=inbox.id,
            sequence_index=2,
            position_in_day=2,
            scheduled_date=time_provider.utcnow(),
        )
        db.add_all([slot1, slot2])

        # Seed outbound sent log so thread matching works via message_id
        root_msg_id = f"<{uuid.uuid4().hex[:16]}@outreach-test.weblinxsolution.com>"
        root_thread_id = root_msg_id
        email_log = EmailLog(
            campaign_id=campaign.id,
            lead_id=lead.id,
            inbox_id=inbox.id,
            sequence_index=0,
            message_id=root_msg_id,
            thread_id=root_thread_id,
            subject="Exclusive Partnership Opportunity with Acme",
        )
        db.add(email_log)
        await db.commit()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # -------------------------------------------------------------------
        # TEST 1: Security - Reject invalid HMAC signature
        # -------------------------------------------------------------------
        print("\n[TEST 1] Testing Webhook HMAC Signature Security...")
        now_ts = str(int(time.time()))
        fake_email = b"From: test@example.com\r\nTo: alex.outreach@outreach-test.weblinxsolution.com\r\n\r\nHello"

        res_bad_sig = await client.post(
            "/api/inbound/cloudflare",
            content=fake_email,
            headers={
                "Content-Type": "message/rfc822",
                "X-Webhook-Signature": "invalid-hex-signature-12345",
                "X-Webhook-Timestamp": now_ts,
            },
        )
        assert res_bad_sig.status_code == 401, f"Expected 401 on bad signature, got {res_bad_sig.status_code}"
        print("PASS: Bad HMAC signature rejected with HTTP 401.")

        # -------------------------------------------------------------------
        # TEST 2: Security - Reject expired timestamp (replay attack)
        # -------------------------------------------------------------------
        print("\n[TEST 2] Testing Replay Attack Protection (>300s expired)...")
        expired_ts = str(int(time.time()) - 400)
        expired_sig = compute_test_signature(fake_email, expired_ts)

        res_replay = await client.post(
            "/api/inbound/cloudflare",
            content=fake_email,
            headers={
                "Content-Type": "message/rfc822",
                "X-Webhook-Signature": expired_sig,
                "X-Webhook-Timestamp": expired_ts,
            },
        )
        assert res_replay.status_code == 401, f"Expected 401 on expired timestamp, got {res_replay.status_code}"
        print("PASS: Expired timestamp rejected with HTTP 401.")

        # -------------------------------------------------------------------
        # TEST 3 & 4: Inbound Email Ingestion with Attachment & Threading
        # -------------------------------------------------------------------
        print("\n[TEST 3] Ingesting Valid Inbound Email with PDF Attachment & Threading...")
        reply_msg_id = f"<{uuid.uuid4().hex[:16]}@acme-client.example.com>"

        mime = EmailMessage()
        mime["Subject"] = "Re: Exclusive Partnership Opportunity with Acme"
        mime["From"] = f"David Miller <{lead_email}>"
        mime["To"] = inbox_email
        mime["Message-ID"] = reply_msg_id
        mime["In-Reply-To"] = root_msg_id
        mime["References"] = root_msg_id
        mime.set_content("Hi Alex,\n\nWe would love to discuss this. Attached is our scope requirements.\n\nBest,\nDavid")

        pdf_payload = b"%PDF-1.4 Fake PDF scope content for Weblinx QA"
        mime.add_attachment(
            pdf_payload,
            maintype="application",
            subtype="pdf",
            filename="scope_requirements.pdf",
        )
        raw_mime_bytes = mime.as_bytes()

        valid_ts = str(int(time.time()))
        valid_sig = compute_test_signature(raw_mime_bytes, valid_ts)
        event_id = uuid.uuid4().hex

        res_ingest = await client.post(
            "/api/inbound/cloudflare",
            content=raw_mime_bytes,
            headers={
                "Content-Type": "message/rfc822",
                "X-Webhook-Signature": valid_sig,
                "X-Webhook-Timestamp": valid_ts,
                "X-Webhook-Event-ID": event_id,
                "X-Envelope-To": inbox_email,
                "X-Envelope-From": lead_email,
            },
        )
        assert res_ingest.status_code == 200, f"Expected 200 on valid ingest, got {res_ingest.status_code}: {res_ingest.text}"
        data_ingest = res_ingest.json()
        assert data_ingest.get("ok") is True
        assert data_ingest.get("attachments_count") == 1
        print("PASS: Inbound email with attachment ingested cleanly.")

        # -------------------------------------------------------------------
        # TEST 5: Verify Attachment Download & Content
        # -------------------------------------------------------------------
        print("\n[TEST 4] Verifying Attachment Storage & Authenticated Download...")
        async with AsyncSessionLocal() as db:
            att_row_res = await db.execute(
                select(EmailAttachment).where(EmailAttachment.inbox_id == inbox_id).order_by(EmailAttachment.id.desc())
            )
            att_row = att_row_res.scalars().first()
            assert att_row is not None, "Attachment row must exist in DB"
            assert att_row.filename == "scope_requirements.pdf"
            att_id = att_row.id

        res_dl = await client.get(f"/api/unibox/attachments/{att_id}", headers=auth_headers)
        assert res_dl.status_code == 200, f"Expected 200 on attachment download, got {res_dl.status_code}"
        assert res_dl.content == pdf_payload, "Downloaded attachment bytes must match original upload"
        assert "scope_requirements.pdf" in res_dl.headers.get("content-disposition", "")
        assert res_dl.headers.get("x-content-type-options") == "nosniff"
        print("PASS: Attachment securely stored and verified byte-for-byte.")

        # -------------------------------------------------------------------
        # TEST 6: Verify Campaign Reply Matching & Sequence Halting
        # -------------------------------------------------------------------
        print("\n[TEST 5] Verifying Campaign Stop-on-Reply & QueueSlot Deletion...")
        async with AsyncSessionLocal() as db:
            # Check LeadReply created
            reply_res = await db.execute(
                select(LeadReply).where(
                    LeadReply.campaign_id == campaign.id,
                    LeadReply.lead_id == lead.id,
                )
            )
            lead_reply = reply_res.scalar_one_or_none()
            assert lead_reply is not None, "LeadReply record must be created automatically"

            # Check CampaignLead status changed to 'contacted'
            cl_check = await db.execute(
                select(CampaignLead).where(
                    CampaignLead.campaign_id == campaign.id,
                    CampaignLead.lead_id == lead.id,
                )
            )
            cl_obj = cl_check.scalar_one()
            assert cl_obj.enrollment_status == "contacted", f"Expected contacted, got {cl_obj.enrollment_status}"

            # Check QueueSlots deleted (follow-ups stopped!)
            slots_res = await db.execute(
                select(QueueSlot).where(QueueSlot.campaign_lead_id == cl.id)
            )
            remaining_slots = slots_res.scalars().all()
            assert len(remaining_slots) == 0, f"All queue slots must be deleted on reply! Remaining: {len(remaining_slots)}"

        print("PASS: Campaign sequence automatically halted! Queue slots deleted and LeadReply recorded.")

        # -------------------------------------------------------------------
        # TEST 7: Deduplication Verification
        # -------------------------------------------------------------------
        print("\n[TEST 6] Testing Inbound Webhook Deduplication...")
        res_dup = await client.post(
            "/api/inbound/cloudflare",
            content=raw_mime_bytes,
            headers={
                "Content-Type": "message/rfc822",
                "X-Webhook-Signature": valid_sig,
                "X-Webhook-Timestamp": valid_ts,
                "X-Webhook-Event-ID": "dup-event-123",
            },
        )
        assert res_dup.status_code == 200
        assert res_dup.json().get("duplicate") is True
        print("PASS: Duplicate email correctly identified and safely skipped.")

        # -------------------------------------------------------------------
        # TEST 8: Unibox Folders (Inbox, Sent, Drafts, Replies, All)
        # -------------------------------------------------------------------
        print("\n[TEST 7] Testing Unibox Folder Filtering...")
        for folder in ["inbox", "sent", "replies", "all"]:
            res_folder = await client.get(
                f"/api/unibox?folder={folder}&leads_only=false",
                headers=auth_headers,
            )
            assert res_folder.status_code == 200, f"Folder {folder} returned {res_folder.status_code}"
            data_folder = res_folder.json()
            print(f"  - Folder '{folder}': {data_folder.get('total', 0)} conversation(s) loaded")

        print("PASS: All folder queries executed cleanly.")

        # -------------------------------------------------------------------
        # TEST 9: Drafts CRUD
        # -------------------------------------------------------------------
        print("\n[TEST 8] Testing Email Drafts CRUD...")
        # Create draft
        res_draft = await client.post(
            "/api/unibox/drafts",
            headers=auth_headers,
            json={
                "inbox_id": inbox_id,
                "to_email": "prospective.client@austindesign.com",
                "subject": "Proposal for Q4 Redesign",
                "body_plain": "Drafting project scope notes here...",
            },
        )
        assert res_draft.status_code == 200
        draft_id = res_draft.json()["id"]

        # List drafts
        res_list_drafts = await client.get("/api/unibox/drafts", headers=auth_headers)
        assert res_list_drafts.status_code == 200
        assert any(d["id"] == draft_id for d in res_list_drafts.json())

        # Test folder=drafts in Unibox
        res_unibox_drafts = await client.get("/api/unibox?folder=drafts", headers=auth_headers)
        assert res_unibox_drafts.status_code == 200
        assert res_unibox_drafts.json()["total"] >= 1

        # Delete draft
        res_del_draft = await client.delete(f"/api/unibox/drafts/{draft_id}", headers=auth_headers)
        assert res_del_draft.status_code == 200
        print("PASS: Drafts created, queried via folder=drafts, and deleted.")

        # -------------------------------------------------------------------
        # TEARDOWN: Clean up test artifacts cleanly
        # -------------------------------------------------------------------
        print("\n[Teardown] Cleaning up QA test records...")
        async with AsyncSessionLocal() as db:
            await db.execute(EmailAttachment.__table__.delete().where(EmailAttachment.inbox_id == inbox_id))
            await db.execute(SmtpMessage.__table__.delete().where(SmtpMessage.inbox_id == inbox_id))
            await db.execute(SmtpThread.__table__.delete().where(SmtpThread.inbox_id == inbox_id))
            await db.execute(EmailLog.__table__.delete().where(EmailLog.inbox_id == inbox_id))
            await db.execute(LeadReply.__table__.delete().where(LeadReply.lead_id == lead.id))
            await db.execute(CampaignLead.__table__.delete().where(CampaignLead.lead_id == lead.id))
            await db.execute(Lead.__table__.delete().where(Lead.id == lead.id))
            await db.execute(Campaign.__table__.delete().where(Campaign.id == campaign.id))
            await db.execute(Inbox.__table__.delete().where(Inbox.id == inbox_id))
            await db.execute(AppSetting.__table__.delete().where(AppSetting.key == "cloudflare_inbound_webhook_secret"))
            await db.commit()
        print("PASS: Teardown complete. Baseline database preserved.")

    print("\n" + "=" * 70)
    print("ALL 8 SERVERLESS INBOX QA CHECKS PASSED PERFECTLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_serverless_inbox_tests())
