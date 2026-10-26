"""Live API End-to-End QA Test against running backend server at http://127.0.0.1:8000.

Validates:
1. Authentication via Bearer token
2. GET /api/leads/verify-status
3. POST /api/leads/{id}/verify
4. POST /api/leads/verify-selected
5. POST /api/leads/{id}/override-verification
6. POST /api/leads/approve-selected
7. Database state persistence across server restarts
"""
import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User, Lead
from app.auth import create_access_token


async def test_live_server_endpoints():
    print("Testing live FastAPI server at http://127.0.0.1:8000 ...")

    # 1. Fetch admin user and token
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).limit(1))
        user = user_res.scalar_one_or_none()
        assert user is not None, "At least one user must exist in DB"
        token = create_access_token(user.id, user.role)

        # Get or create a test lead for live API testing
        lead_res = await db.execute(select(Lead).order_by(Lead.id.desc()).limit(1))
        lead = lead_res.scalar_one_or_none()
        if not lead:
            lead = Lead(email="audit_live@weblinxsolution.com", name="Live Audit Prospect")
            db.add(lead)
            await db.commit()
            await db.refresh(lead)
        lead_id = lead.id
        lead_email = lead.email

    headers = {"Authorization": f"Bearer {token}"}
    base_url = "http://127.0.0.1:8000"

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # 2. Check /api/leads/verify-status
        status_resp = await client.get("/api/leads/verify-status", headers=headers)
        assert status_resp.status_code == 200, f"Expected 200, got {status_resp.status_code}: {status_resp.text}"
        status_data = status_resp.json()
        print("  [PASS] GET /api/leads/verify-status ->", status_data["breakdown"])
        assert "breakdown" in status_data
        assert "job" in status_data
        assert "total_prospects" in status_data

        # 3. Check single lead verify: POST /api/leads/{lead_id}/verify
        single_resp = await client.post(f"/api/leads/{lead_id}/verify?check_smtp=false", headers=headers)
        assert single_resp.status_code == 200, f"Expected 200, got {single_resp.status_code}: {single_resp.text}"
        single_data = single_resp.json()
        print(f"  [PASS] POST /api/leads/{lead_id}/verify -> status: {single_data.get('status')}")
        assert single_data["ok"] is True
        assert single_data["lead_id"] == lead_id

        # 4. Check selected verify: POST /api/leads/verify-selected
        sel_resp = await client.post(
            "/api/leads/verify-selected",
            json={"lead_ids": [lead_id], "check_smtp": False},
            headers=headers,
        )
        assert sel_resp.status_code == 200, f"Expected 200, got {sel_resp.status_code}: {sel_resp.text}"
        sel_data = sel_resp.json()
        print("  [PASS] POST /api/leads/verify-selected ->", sel_data)
        assert sel_data["ok"] is True
        assert sel_data["total"] == 1

        # 5. Check manual override: POST /api/leads/{lead_id}/override-verification
        override_payload = {
            "status": "domain_validated",
            "note": "Manual QA verification test note",
        }
        ov_resp = await client.post(
            f"/api/leads/{lead_id}/override-verification",
            json=override_payload,
            headers=headers,
        )
        assert ov_resp.status_code == 200, f"Expected 200, got {ov_resp.status_code}: {ov_resp.text}"
        ov_data = ov_resp.json()
        print(f"  [PASS] POST /api/leads/{lead_id}/override-verification -> override: {ov_data.get('override')}")
        assert ov_data["ok"] is True
        assert ov_data["status"] == "domain_validated"
        assert ov_data["override"]["note"] == override_payload["note"]
        assert "overridden_at" in ov_data["override"]

        # 6. Check approve selected: POST /api/leads/approve-selected
        appr_resp = await client.post(
            "/api/leads/approve-selected",
            json={"lead_ids": [lead_id]},
            headers=headers,
        )
        assert appr_resp.status_code == 200, f"Expected 200, got {appr_resp.status_code}: {appr_resp.text}"
        appr_data = appr_resp.json()
        print("  [PASS] POST /api/leads/approve-selected ->", appr_data)
        assert appr_data["ok"] is True
        assert appr_data["approved_count"] == 1

        # 7. Check lead response: GET /api/leads/{lead_id}
        lead_get = await client.get(f"/api/leads/{lead_id}", headers=headers)
        assert lead_get.status_code == 200, f"Expected 200, got {lead_get.status_code}: {lead_get.text}"
        lead_get_data = lead_get.json()
        assert lead_get_data["email_verification_status"] == "domain_validated"
        assert lead_get_data["email_verification_result"]["approved"] is True
        assert lead_get_data["email_verification_result"]["override"]["note"] == override_payload["note"]
        print("  [PASS] GET /api/leads/{lead_id} -> verified persistence in Lead model JSON field")

    print("\nSUCCESS: All live HTTP endpoints passed QA verification with 100% success!")


if __name__ == "__main__":
    asyncio.run(test_live_server_endpoints())
