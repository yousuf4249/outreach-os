"""End-to-End Verification Test for Deliverability Inspector & Syntax Validation.

Validates:
1. Verification of Gmail prospect (DNS/MX scan, Google Workspace MX resolution, RFC 5322 syntax)
2. Immediate persistence of verification result and classification in database
3. Invalid syntax rejection / blocking in campaign sending gate
4. Inability to approve contacts with invalid syntax
5. Verification modal data structure alignment
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User, Lead, Campaign, CampaignLead
from app.auth import create_access_token
from app.campaign_lead_status import campaign_lead_may_receive_sends
from app.verification_engine import (
    validate_syntax_and_normalize,
    verify_single_email,
    STATUS_VALID,
    STATUS_DOMAIN_VALIDATED,
    STATUS_INVALID,
)


async def run_deliverability_inspector_tests():
    print("============================================================")
    print("  DELIVERABILITY INSPECTOR & SYNTAX VALIDATION E2E TEST")
    print("============================================================")

    # 1. Fetch user token
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).limit(1))
        user = user_res.scalar_one_or_none()
        assert user is not None
        token = create_access_token(user.id, user.role)

        # Ensure lead 3 exists or fetch it
        lead3_res = await db.execute(select(Lead).where(Lead.id == 3))
        lead3 = lead3_res.scalar_one_or_none()
        if not lead3:
            lead3 = Lead(id=3, email="yousuf4229@gmail.com", name="Test Gmail Prospect")
            db.add(lead3)
            await db.commit()
            await db.refresh(lead3)

    headers = {"Authorization": f"Bearer {token}"}
    base_url = "http://127.0.0.1:8000"

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # TEST 1: Inspect before verify
        pre_get = await client.get("/api/leads/3", headers=headers)
        assert pre_get.status_code == 200
        pre_data = pre_get.json()
        print(f"[TEST 1] Pre-verification lead 3 status: {pre_data.get('email_verification_status')}")

        # TEST 2: Call Verify DNS/MX endpoint (POST /api/leads/3/verify?check_smtp=false)
        verif_resp = await client.post("/api/leads/3/verify?check_smtp=false", headers=headers)
        assert verif_resp.status_code == 200, f"Failed: {verif_resp.text}"
        verif_data = verif_resp.json()
        print(f"[TEST 2] Verify response: ok={verif_data.get('ok')}, status={verif_data.get('status')}")
        assert verif_data["ok"] is True
        assert verif_data["status"] == STATUS_DOMAIN_VALIDATED
        assert verif_data["result"]["syntax"]["valid"] is True
        assert verif_data["result"]["domain"]["has_mx"] is True
        assert "gmail-smtp-in.l.google.com" in [mx["host"] for mx in verif_data["result"]["domain"]["mx_records"]]

        # TEST 3: Verify database persistence after verify
        post_get = await client.get("/api/leads/3", headers=headers)
        assert post_get.status_code == 200
        post_data = post_get.json()
        print(f"[TEST 3] Post-verification lead 3 in DB: status={post_data.get('email_verification_status')}, provider={post_data.get('provider')}")
        assert post_data["email_verification_status"] == STATUS_DOMAIN_VALIDATED
        assert post_data["email_verification_result"]["syntax"]["valid"] is True
        assert post_data["email_verification_result"]["domain"]["has_mx"] is True

        # TEST 4: Attempt to create prospect with invalid syntax
        invalid_create = await client.post(
            "/api/leads",
            json={"email": "broken@@domain..com", "name": "Broken Syntax Lead"},
            headers=headers,
        )
        print(f"[TEST 4] Creation of invalid syntax lead: status_code={invalid_create.status_code} ({invalid_create.text})")
        assert invalid_create.status_code == 400
        assert "invalid email syntax" in invalid_create.text.lower()

        # TEST 5: Verify Campaign Gate strictly blocks invalid syntax
        mock_invalid_lead = Lead(email="invalid-syntax-no-at.com", email_verification_status=STATUS_INVALID)
        mock_cl = CampaignLead(campaign_id=999, lead_id=999, enrollment_status="active", sending_paused=False)
        may_send = campaign_lead_may_receive_sends(mock_cl, mock_invalid_lead)
        print(f"[TEST 5] Campaign Gate eligibility for invalid syntax lead: may_send={may_send}")
        assert may_send is False

        # TEST 6: Attempt to approve lead with invalid syntax
        async with AsyncSessionLocal() as db:
            bad_lead = Lead(email="unparseable.address", name="Bad Lead", email_verification_status="not_verified")
            db.add(bad_lead)
            await db.commit()
            await db.refresh(bad_lead)
            bad_lead_id = bad_lead.id

        appr_resp = await client.post(
            "/api/leads/approve-selected",
            json={"lead_ids": [bad_lead_id], "note": "Attempt approval"},
            headers=headers,
        )
        assert appr_resp.status_code == 200
        appr_data = appr_resp.json()
        print(f"[TEST 6] Approve selected on invalid syntax lead: approved_count={appr_data.get('approved_count')}")
        assert appr_data["approved_count"] == 0, "Invalid syntax lead must NOT be approved"

        # TEST 7: Cleanup temporary bad lead
        async with AsyncSessionLocal() as db:
            lead_to_del = await db.get(Lead, bad_lead_id)
            if lead_to_del:
                await db.delete(lead_to_del)
                await db.commit()

    print("\nSUCCESS: All 7 Deliverability Inspector & Syntax validation tests passed!")


if __name__ == "__main__":
    asyncio.run(run_deliverability_inspector_tests())
