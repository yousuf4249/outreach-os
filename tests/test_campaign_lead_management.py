"""
Weblinx Outreach OS - Campaign Lead Removal & Bulk Management Verification Test Suite
Verifies:
1. Single removal cancels queue slots and keeps Lead intact in central Prospect database.
2. Bulk removal cancels queue slots and keeps all Leads intact.
3. Stop sequence / unenroll marks status as 'stopped' and deletes pending queue slots.
4. Re-enrollment via bulk-campaign-assign allows previously removed leads to be selected again without restarting completed steps.
5. Global suppression and hard bounces cannot be bypassed by removal/re-enrollment.
6. Temporary delivery errors vs hard bounce distinction, and safe retry recovery.
7. Baseline preservation of the 31 original leads.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import delete, func, select
from app.database import AsyncSessionLocal
from app.models import (
    Campaign,
    CampaignInbox,
    CampaignLead,
    EmailLog,
    Inbox,
    Lead,
    QueueSlot,
    Sequence,
    SuppressionList,
)
from app.sender import SendFailure, classify_smtp_error
from app.campaign_lead_status import campaign_lead_may_receive_sends, ENROLLMENT_STATUSES, enrollment_blocks_sends
from app.queue_logic import reserve_slots_for_new_leads_bulk
from app.routers.campaigns import (
    bulk_action_campaign_leads,
    bulk_remove_leads_from_campaign,
    bulk_retry_campaign_leads,
    remove_lead_from_campaign,
    retry_bounced_campaign_lead,
)
from app.schemas import (
    CampaignLeadBulkActionRequest,
    CampaignLeadBulkRemoveRequest,
    CampaignLeadBulkRetryRequest,
    LeadBulkAssignCampaignRequest,
)
from app.routers.leads import bulk_assign_to_campaign
from fastapi import BackgroundTasks, HTTPException


class MockBackgroundTasks:
    def add_task(self, func, *args, **kwargs):
        pass


async def run_tests():
    print("=" * 70)
    print("STARTING CAMPAIGN LEAD REMOVAL & BULK MANAGEMENT VERIFICATION")
    print("=" * 70)

    bg = MockBackgroundTasks()

    async with AsyncSessionLocal() as session:
        # Pre-cleanup in case of aborted runs
        await session.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id.in_(
            select(CampaignLead.id).where(CampaignLead.campaign_id.in_(
                select(Campaign.id).where(Campaign.name.startswith("QA Lead Management"))
            ))
        )))
        await session.execute(delete(QueueSlot).where(~QueueSlot.campaign_lead_id.in_(
            select(CampaignLead.id)
        )))
        await session.execute(delete(CampaignLead).where(CampaignLead.campaign_id.in_(
            select(Campaign.id).where(Campaign.name.startswith("QA Lead Management"))
        )))
        await session.execute(delete(CampaignInbox).where(CampaignInbox.campaign_id.in_(
            select(Campaign.id).where(Campaign.name.startswith("QA Lead Management"))
        )))
        await session.execute(delete(Sequence).where(Sequence.campaign_id.in_(
            select(Campaign.id).where(Campaign.name.startswith("QA Lead Management"))
        )))
        await session.execute(delete(EmailLog).where(EmailLog.campaign_id.in_(
            select(Campaign.id).where(Campaign.name.startswith("QA Lead Management"))
        )))
        await session.execute(delete(Campaign).where(Campaign.name.startswith("QA Lead Management")))
        await session.execute(delete(Inbox).where(Inbox.email.startswith("sender-qa-")))
        await session.execute(delete(Inbox).where(Inbox.email == "sender-qa@weblinxsolution.com"))
        await session.execute(delete(SuppressionList).where(SuppressionList.email_or_domain.startswith("blocked-suppressed")))
        await session.execute(delete(Lead).where(Lead.email.startswith("qa-lead-")))
        await session.execute(delete(Lead).where(Lead.email.in_(["blocked-suppressed@example.com", "hard-bounced@example.com"])))
        await session.commit()

        # Check baseline lead count
        baseline_res = await session.execute(select(func.count(Lead.id)))
        baseline_lead_count = baseline_res.scalar() or 0
        print(f"[*] Initial Lead count in database: {baseline_lead_count}")
        assert baseline_lead_count >= 31, f"Expected at least 31 baseline leads, found {baseline_lead_count}"

        import time
        ts = int(time.time())
        # ── Setup QA Campaign, Inbox & Sequence ──
        qa_camp = Campaign(name=f"QA Lead Management Test Campaign {ts}", paused=False)
        session.add(qa_camp)
        await session.flush()

        qa_inbox = Inbox(email=f"sender-qa-{ts}@weblinxsolution.com", display_name="QA Sender", paused=False, max_emails_per_day=50)
        session.add(qa_inbox)
        await session.flush()

        ci = CampaignInbox(campaign_id=qa_camp.id, inbox_id=qa_inbox.id)
        session.add(ci)
        await session.flush()

        seq0 = Sequence(campaign_id=qa_camp.id, position=0, wait_days_after_previous=0, subject="Step 1 Subject", body="Step 1 Body")
        seq1 = Sequence(campaign_id=qa_camp.id, position=1, wait_days_after_previous=2, subject="Step 2 Followup", body="Step 2 Body")
        session.add_all([seq0, seq1])
        await session.flush()

        # ── Setup 4 Test Leads ──
        test_leads = [
            Lead(email=f"qa-lead-{i}@example.com", name=f"QA Lead {i}", company=f"Company {i}", status="active", email_verification_status="valid")
            for i in range(1, 5)
        ]
        session.add_all(test_leads)
        await session.flush()

        # Enroll all 4 leads
        cls = [
            CampaignLead(campaign_id=qa_camp.id, lead_id=l.id, enrollment_status="active")
            for l in test_leads
        ]
        session.add_all(cls)
        await session.flush()

        # Reserve queue slots for all 4
        cl_ids = [c.id for c in cls]
        await reserve_slots_for_new_leads_bulk(session, cl_ids, qa_camp.id)
        await session.commit()

        # Verify initial slots
        initial_slots = await session.execute(select(QueueSlot).where(QueueSlot.campaign_lead_id.in_(cl_ids)))
        slot_count = len(initial_slots.scalars().all())
        print(f"[TEST 0] Initial state: 4 leads enrolled, {slot_count} queue slots created.")
        assert slot_count > 0, "Expected queue slots to be scheduled"

        # ====================================================================
        # TEST 1: Single Lead Removal
        # ====================================================================
        print("\n[TEST 1] Testing Single Lead Removal...")
        target_lead = test_leads[0]
        target_cl_id = cls[0].id

        res = await remove_lead_from_campaign(qa_camp.id, target_lead.id, bg, session)
        assert res.get("ok") is True

        # Check CampaignLead is deleted
        check_cl = await session.execute(
            select(CampaignLead).where(CampaignLead.campaign_id == qa_camp.id, CampaignLead.lead_id == target_lead.id)
        )
        assert check_cl.scalar_one_or_none() is None, "CampaignLead must be deleted"

        # Check QueueSlot for this lead is deleted
        check_slots = await session.execute(select(QueueSlot).where(QueueSlot.campaign_lead_id == target_cl_id))
        assert len(check_slots.scalars().all()) == 0, "Queue slots for removed lead must be deleted"

        # CRITICAL: Check central Lead table record is 100% INTACT!
        check_lead = await session.execute(select(Lead).where(Lead.id == target_lead.id))
        intact_lead = check_lead.scalar_one_or_none()
        assert intact_lead is not None, "Lead record MUST NOT be deleted from central database!"
        assert intact_lead.email == target_lead.email
        print("PASS: Single lead removed from campaign. Queue slots cancelled. Central Lead record preserved!")

        # ====================================================================
        # TEST 2: Bulk Lead Removal
        # ====================================================================
        print("\n[TEST 2] Testing Bulk Lead Removal...")
        bulk_targets = [test_leads[1], test_leads[2]]
        bulk_target_ids = [l.id for l in bulk_targets]
        bulk_cl_ids = [cls[1].id, cls[2].id]

        bulk_req = CampaignLeadBulkRemoveRequest(lead_ids=bulk_target_ids)
        res_bulk = await bulk_remove_leads_from_campaign(qa_camp.id, bulk_req, bg, session)
        assert res_bulk.get("ok") is True
        assert res_bulk.get("removed") == 2

        # Check CampaignLeads deleted
        check_cls = await session.execute(
            select(CampaignLead).where(CampaignLead.campaign_id == qa_camp.id, CampaignLead.lead_id.in_(bulk_target_ids))
        )
        assert len(check_cls.scalars().all()) == 0

        # Check QueueSlots deleted
        check_slots = await session.execute(select(QueueSlot).where(QueueSlot.campaign_lead_id.in_(bulk_cl_ids)))
        assert len(check_slots.scalars().all()) == 0

        # CRITICAL: Check central Lead table records are 100% INTACT!
        for bt in bulk_targets:
            chk = await session.execute(select(Lead).where(Lead.id == bt.id))
            assert chk.scalar_one_or_none() is not None, f"Lead {bt.email} must remain in central database!"
        print("PASS: Bulk leads removed from campaign. All queue slots purged. All central Lead records preserved!")

        # ====================================================================
        # TEST 3: Stop Sequence / Unenroll (Single & Bulk)
        # ====================================================================
        print("\n[TEST 3] Testing Stop Sequence / Unenroll...")
        lead_to_stop = test_leads[3]
        cl_to_stop = cls[3]

        # Verify slots exist before stopping
        slots_before = await session.execute(select(QueueSlot).where(QueueSlot.campaign_lead_id == cl_to_stop.id))
        assert len(slots_before.scalars().all()) > 0, "Slots should exist before stopping"

        action_req = CampaignLeadBulkActionRequest(lead_ids=[lead_to_stop.id], action="stop")
        action_res = await bulk_action_campaign_leads(qa_camp.id, action_req, bg, session)
        assert action_res.get("ok") is True
        assert action_res.get("updated") == 1

        # Check CampaignLead status changed to 'stopped'
        cl_stopped_check = await session.execute(
            select(CampaignLead).where(CampaignLead.campaign_id == qa_camp.id, CampaignLead.lead_id == lead_to_stop.id)
        )
        cl_stopped = cl_stopped_check.scalar_one_or_none()
        assert cl_stopped is not None
        assert cl_stopped.enrollment_status == "stopped", f"Expected 'stopped', got {cl_stopped.enrollment_status}"
        assert enrollment_blocks_sends("stopped") is True, "stopped status must block sending"

        # Check all queue slots immediately cancelled
        slots_after = await session.execute(select(QueueSlot).where(QueueSlot.campaign_lead_id == cl_to_stop.id))
        assert len(slots_after.scalars().all()) == 0, "Pending queue slots must be cancelled upon stopping sequence"

        # Resume sequence
        resume_req = CampaignLeadBulkActionRequest(lead_ids=[lead_to_stop.id], action="resume")
        resume_res = await bulk_action_campaign_leads(qa_camp.id, resume_req, bg, session)
        assert resume_res.get("ok") is True
        cl_resumed = (await session.execute(select(CampaignLead).where(CampaignLead.id == cl_to_stop.id))).scalar_one()
        assert cl_resumed.enrollment_status == "active"
        print("PASS: Stop Sequence marks enrollment 'stopped' and deletes pending queue slots. Resume re-activates successfully!")

        # ====================================================================
        # TEST 4: Re-enrollment via bulk-campaign-assign (No Completed Steps Resent)
        # ====================================================================
        print("\n[TEST 4] Testing Re-enrollment of Previously Removed Leads...")
        # target_lead (test_leads[0]) was removed in Test 1.
        # Simulate that step 0 was already sent to target_lead previously:
        fake_log = EmailLog(lead_id=target_lead.id, campaign_id=qa_camp.id, sequence_index=0, subject="Step 1 Sent", body="Body")
        session.add(fake_log)
        await session.commit()

        # Re-enroll target_lead via bulk_assign_to_campaign (used by SelectProspectsModal)
        assign_body = LeadBulkAssignCampaignRequest(
            campaign_id=qa_camp.id,
            lead_ids=[target_lead.id],
            skip_other_active=False,
            dry_run=False,
        )
        assign_res = await bulk_assign_to_campaign(assign_body, bg, session)
        assert assign_res.get("ok") is True
        assert assign_res.get("assigned") == 1

        # Check newly created CampaignLead
        new_cl_res = await session.execute(
            select(CampaignLead).where(CampaignLead.campaign_id == qa_camp.id, CampaignLead.lead_id == target_lead.id)
        )
        new_cl = new_cl_res.scalar_one_or_none()
        assert new_cl is not None, "Lead should be successfully re-enrolled"

        # Check scheduled slots for re-enrolled lead:
        # Step 0 was already sent! Only step 1 should be scheduled, never resending step 0!
        new_slots_res = await session.execute(
            select(QueueSlot).where(QueueSlot.campaign_lead_id == new_cl.id).order_by(QueueSlot.sequence_index)
        )
        new_slots = new_slots_res.scalars().all()
        seq_indexes = [s.sequence_index for s in new_slots]
        assert 0 not in seq_indexes, f"Step 0 was already sent and MUST NOT be resent! Found slots: {seq_indexes}"
        assert 1 in seq_indexes, "Remaining step 1 should be scheduled"
        print(f"PASS: Re-enrolled lead scheduled remaining steps {seq_indexes} without restarting completed step 0!")

        # ====================================================================
        # TEST 5: Global Suppression and Hard Bounce Protection
        # ====================================================================
        print("\n[TEST 5] Testing Global Suppression and Hard Bounce Protection...")
        suppressed_lead = Lead(email="blocked-suppressed@example.com", name="Suppressed Contact", status="active", email_verification_status="valid")
        bounced_lead = Lead(email="hard-bounced@example.com", name="Bounced Contact", status="bounced", email_verification_status="invalid")
        session.add_all([suppressed_lead, bounced_lead])
        await session.flush()

        supp_entry = SuppressionList(email_or_domain="blocked-suppressed@example.com", reason="Competitor/Unsubscribe")
        session.add(supp_entry)
        await session.commit()

        # Attempt to enroll suppressed lead via bulk_assign_to_campaign
        supp_assign = await bulk_assign_to_campaign(
            LeadBulkAssignCampaignRequest(campaign_id=qa_camp.id, lead_ids=[suppressed_lead.id], dry_run=False),
            bg,
            session,
        )
        assert supp_assign.get("assigned") == 0
        assert supp_assign.get("blocked") == 1
        print("PASS: Globally suppressed lead blocked from campaign enrollment!")

        # Attempt to enroll hard bounced lead
        bounce_assign = await bulk_assign_to_campaign(
            LeadBulkAssignCampaignRequest(campaign_id=qa_camp.id, lead_ids=[bounced_lead.id], dry_run=False),
            bg,
            session,
        )
        assert bounce_assign.get("assigned") == 0
        assert bounce_assign.get("blocked") == 1
        print("PASS: Hard-bounced lead blocked from campaign enrollment!")

        # ====================================================================
        # TEST 6: SMTP Error Classification & Temporary Error Recovery
        # ====================================================================
        print("\n[TEST 6] Testing Temporary Failure vs Hard Bounce Classification & Retry...")
        # 1. Quota / Rate limit error classification
        err_type_quota, b_type_quota = classify_smtp_error(452, "452 4.2.2 Mailbox full / quota exceeded")
        assert err_type_quota == "temporary_failure"
        assert b_type_quota == "temporary_failure"

        # 2. Hard bounce classification (550 User unknown)
        err_type_hard, b_type_hard = classify_smtp_error(550, "550 5.1.1 User unknown")
        assert err_type_hard == "bounce"
        assert b_type_hard == "hard_bounce"

        # 3. Simulate temporary bounce on new_cl
        new_cl.enrollment_status = "bounced"
        new_cl.bounce_type = "temporary_failure"
        new_cl.failure_reason = "451 4.3.0 Mailbox busy / temporary server delay"
        await session.commit()

        # Retry eligible temporary failure
        retry_res = await retry_bounced_campaign_lead(qa_camp.id, target_lead.id, bg, session)
        assert retry_res.get("ok") is True
        cl_retried = (await session.execute(select(CampaignLead).where(CampaignLead.id == new_cl.id))).scalar_one()
        assert cl_retried.enrollment_status == "active"
        assert cl_retried.failure_reason is None
        assert cl_retried.bounce_type is None
        print("PASS: Temporary delivery failure successfully recovered and re-queued!")

        # 4. Simulate hard bounce and verify retry is REJECTED
        cl_retried.enrollment_status = "bounced"
        cl_retried.bounce_type = "hard_bounce"
        cl_retried.failure_reason = "550 5.1.1 User unknown"
        await session.commit()

        rejected = False
        try:
            await retry_bounced_campaign_lead(qa_camp.id, target_lead.id, bg, session)
        except HTTPException as exc:
            rejected = True
            assert exc.status_code == 400
            assert "Cannot retry confirmed permanent recipient bounce" in exc.detail
        assert rejected is True, "Hard bounce retry must be rejected!"
        print("PASS: Hard bounce retry strictly rejected with HTTP 400!")

        # ====================================================================
        # TEST 7: Teardown QA Records and Verify 31 Baseline Leads
        # ====================================================================
        print("\n[TEST 7] Cleaning up QA records & verifying 31 baseline leads...")
        # Delete QA campaign and its artifacts
        await session.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id.in_([c.id for c in cls] + [new_cl.id])))
        await session.execute(delete(CampaignLead).where(CampaignLead.campaign_id == qa_camp.id))
        await session.execute(delete(CampaignInbox).where(CampaignInbox.campaign_id == qa_camp.id))
        await session.execute(delete(Sequence).where(Sequence.campaign_id == qa_camp.id))
        await session.execute(delete(EmailLog).where(EmailLog.campaign_id == qa_camp.id))
        await session.execute(delete(Campaign).where(Campaign.id == qa_camp.id))
        await session.execute(delete(Inbox).where(Inbox.id == qa_inbox.id))
        await session.execute(delete(SuppressionList).where(SuppressionList.id == supp_entry.id))
        for tl in test_leads + [suppressed_lead, bounced_lead]:
            await session.execute(delete(Lead).where(Lead.id == tl.id))
        await session.commit()

        # Verify baseline leads count
        final_lead_res = await session.execute(select(func.count(Lead.id)))
        final_lead_count = final_lead_res.scalar() or 0
        print(f"[*] Final Lead count in database: {final_lead_count}")
        assert final_lead_count == baseline_lead_count, f"Expected exactly {baseline_lead_count} baseline leads, found {final_lead_count}"
        print("PASS: Baseline 31 prospects 100% intact and undamaged!")

    print("\n" + "=" * 70)
    print("ALL 7 CAMPAIGN LEAD MANAGEMENT QA CHECKS PASSED PERFECTLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
