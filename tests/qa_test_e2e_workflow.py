"""End-to-End QA Workflow Test Suite for Email Verification Engine.

Tests:
1. CSV import with instant syntax, disposable, and typo detection
2. On-demand single prospect verification with detailed diagnostics
3. Batch selected prospect verification and bulk status reporting
4. Manual verification status override with complete audit trail
5. Approval workflow for review-needed leads
6. Strict Campaign Verification Gate (blocking invalid/suppressed, approving reviewed)
7. State persistence across database queries
"""
import io
import json
import pytest
from datetime import datetime
from fastapi import UploadFile, BackgroundTasks
from sqlalchemy import select

from app.models import Lead, Campaign, CampaignLead, SuppressionList
from app.routers import leads as leads_router
from app.routers.leads import (
    import_prospects,
    verify_single_lead_endpoint,
    verify_selected_leads_endpoint,
    get_verification_status_endpoint,
    manual_override_verification_endpoint,
    approve_selected_leads_endpoint,
    LeadVerifySelectedRequest,
    LeadManualOverrideRequest,
    LeadApproveSelectedRequest,
)
from app.campaign_lead_status import campaign_lead_may_receive_sends
from app.routers.suppression import is_email_or_domain_suppressed
from app.verification_engine import (
    STATUS_VALID,
    STATUS_DOMAIN_VALIDATED,
    STATUS_INVALID,
    STATUS_RISKY,
    STATUS_UNKNOWN,
    STATUS_NOT_VERIFIED,
)


@pytest.mark.asyncio
async def test_csv_import_workflow(session):
    """Test CSV import with instant offline classification and verification gating."""
    csv_content = (
        "Email,Name,Company\n"
        "contact@weblinxsolution.com,Contact Person,Weblinx\n"
        "sales@weblinxsolution.com,Sales Team,Weblinx\n"
        "bad-syntax-no-at,Broken Lead,Unknown\n"
        "temp_user@mailinator.com,Disposable User,TrashCo\n"
        "user_typo@gamil.com,Typo User,Google\n"
    ).encode("utf-8")

    class MockUploadFile:
        filename = "qa_prospects.csv"
        async def read(self):
            return csv_content

    # Create campaign
    camp = Campaign(name="QA Test Campaign", paused=False)
    session.add(camp)
    await session.flush()

    res = await import_prospects(
        file=MockUploadFile(),
        campaign_id=camp.id,
        auto_verify=False,
        background_tasks=BackgroundTasks(),
        db=session,
    )

    assert res["imported"] == 4
    assert res["invalid"] == 1  # 'bad-syntax-no-at' rejected by syntax validation

    # Verify initial classifications
    leads_res = await session.execute(select(Lead).order_by(Lead.id.asc()))
    leads = leads_res.scalars().all()
    assert len(leads) == 4

    by_email = {l.email: l for l in leads}

    # Disposable lead
    disp = by_email.get("temp_user@mailinator.com")
    assert disp is not None
    assert disp.email_verification_status == STATUS_INVALID
    assert disp.email_verification_result["disposable"]["is_disposable"] is True

    # Typo lead
    typo = by_email.get("user_typo@gamil.com")
    assert typo is not None
    assert typo.email_verification_status == STATUS_RISKY
    assert typo.email_verification_result["typo"]["has_typo_risk"] is True
    assert typo.email_verification_result["typo"]["suggestion"] == "gmail.com"

    # Campaign Gate check on import:
    # Disposable lead (STATUS_INVALID) must NOT be enrolled in CampaignLead
    cl_disp = await session.execute(
        select(CampaignLead).where(
            CampaignLead.campaign_id == camp.id,
            CampaignLead.lead_id == disp.id,
        )
    )
    assert cl_disp.scalar_one_or_none() is None, "Invalid lead must be blocked from campaign enrollment on import"


@pytest.mark.asyncio
async def test_single_and_selected_verification_workflow(session):
    """Test on-demand verification and batch selected verification."""
    lead1 = Lead(email="contact@weblinxsolution.com", name="Lead 1", email_verification_status=STATUS_NOT_VERIFIED)
    lead2 = Lead(email="sales@weblinxsolution.com", name="Lead 2", email_verification_status=STATUS_NOT_VERIFIED)
    session.add_all([lead1, lead2])
    await session.commit()
    await session.refresh(lead1)
    await session.refresh(lead2)

    # 1. Single verification
    single_res = await verify_single_lead_endpoint(lead_id=lead1.id, check_smtp=False, db=session)
    assert single_res["ok"] is True
    assert single_res["status"] == STATUS_DOMAIN_VALIDATED
    assert single_res["result"]["domain"]["has_mx"] is True
    # Mailbox existence honesty rule: domain_validated != valid
    assert single_res["status"] != STATUS_VALID

    # 2. Selected verification
    sel_req = LeadVerifySelectedRequest(lead_ids=[lead2.id], check_smtp=False)
    batch_res = await verify_selected_leads_endpoint(body=sel_req, db=session)
    assert batch_res["ok"] is True
    assert batch_res["total"] == 1
    assert batch_res["counts"][STATUS_DOMAIN_VALIDATED] == 1

    await session.refresh(lead2)
    assert lead2.email_verification_status == STATUS_DOMAIN_VALIDATED
    assert lead2.email_verification_result["role_based"]["is_role_account"] is True
    assert lead2.email_verification_result["role_based"]["role_category"] == "sales_marketing"


@pytest.mark.asyncio
async def test_manual_override_audit_trail(session):
    """Test manual verification override with complete audit trail."""
    lead = Lead(
        email="special_case@partner.com",
        name="Partner Case",
        email_verification_status=STATUS_UNKNOWN,
        email_verification_result={"status": "unknown", "reason": "Timeout"},
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    class MockUser:
        email = "auditor@weblinxsolution.com"

    req = LeadManualOverrideRequest(
        status="domain_validated",
        note="Verified phone contact and confirmed legitimate corporate domain.",
    )

    res = await manual_override_verification_endpoint(
        lead_id=lead.id,
        body=req,
        user=MockUser(),
        db=session,
    )

    assert res["ok"] is True
    assert res["status"] == "domain_validated"
    assert res["override"]["previous_status"] == "unknown"
    assert res["override"]["new_status"] == "domain_validated"
    assert res["override"]["by_user"] == "auditor@weblinxsolution.com"
    assert res["override"]["note"] == "Verified phone contact and confirmed legitimate corporate domain."
    assert "overridden_at" in res["override"]

    # Check database persistence
    await session.refresh(lead)
    assert lead.email_verification_status == "domain_validated"
    assert lead.email_verification_result["approved"] is True
    assert lead.email_verification_result["override"]["note"] == req.note


@pytest.mark.asyncio
async def test_campaign_verification_gate_and_approvals(session):
    """Test strict sending gate enforcement for all deliverability statuses."""
    camp = Campaign(name="Outreach Sprint", paused=False)
    session.add(camp)
    await session.flush()

    # 1. Invalid status is strictly blocked
    lead_invalid = Lead(email="bad@burn.com", email_verification_status=STATUS_INVALID)
    session.add(lead_invalid)
    await session.flush()
    cl_invalid = CampaignLead(campaign_id=camp.id, lead_id=lead_invalid.id, enrollment_status="active")
    session.add(cl_invalid)
    assert campaign_lead_may_receive_sends(cl_invalid, lead_invalid) is False

    # 2. Domain Validated is permitted
    lead_valid = Lead(email="good@company.com", email_verification_status=STATUS_DOMAIN_VALIDATED)
    session.add(lead_valid)
    await session.flush()
    cl_valid = CampaignLead(campaign_id=camp.id, lead_id=lead_valid.id, enrollment_status="active")
    session.add(cl_valid)
    assert campaign_lead_may_receive_sends(cl_valid, lead_valid) is True

    # 3. Review-needed status (risky / unknown / not_verified) blocked when unapproved
    lead_review = Lead(
        email="risky@domain.com",
        email_verification_status=STATUS_RISKY,
        email_verification_result={"approved": False},
    )
    session.add(lead_review)
    await session.flush()
    cl_review = CampaignLead(campaign_id=camp.id, lead_id=lead_review.id, enrollment_status="active")
    session.add(cl_review)
    assert campaign_lead_may_receive_sends(cl_review, lead_review) is False

    # 4. Explicit approval via approve_selected endpoint
    appr_req = LeadApproveSelectedRequest(lead_ids=[lead_review.id])
    appr_res = await approve_selected_leads_endpoint(body=appr_req, db=session)
    assert appr_res["ok"] is True
    assert appr_res["approved_count"] == 1

    await session.refresh(lead_review)
    assert lead_review.email_verification_result["approved"] is True
    assert campaign_lead_may_receive_sends(cl_review, lead_review) is True

    # 5. Suppression check blocks even if approved
    rule = SuppressionList(
        email_or_domain=lead_review.email,
        reason="Requested unsubscribe",
    )
    session.add(rule)
    await session.commit()
    is_supp = await is_email_or_domain_suppressed(session, lead_review.email)
    assert is_supp is True


@pytest.mark.asyncio
async def test_verification_status_breakdown(session):
    """Test GET /api/leads/verify-status breakdown reporting."""
    res = await get_verification_status_endpoint(db=session)
    assert "breakdown" in res
    assert "total_prospects" in res
    assert "job" in res
    assert isinstance(res["breakdown"], dict)
    assert "domain_validated" in res["breakdown"]
    assert "invalid" in res["breakdown"]
