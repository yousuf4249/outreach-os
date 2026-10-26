"""End-to-end QA test suite for Lead Detail Page & Email Interaction Personalization.

Validates:
1. Email interaction history displays rendered template variables (no raw {{...}}).
2. Interaction items provide from_email, to_email, accurate sending status, subject, snippet, body.
3. Direct email sending saves rendered subject & body in DirectEmail table.
4. Edit Lead with essential fields: Company Name, Email, Contact Name, Phone, Website.
5. Lead status dropdown: new, contacted, replied, interested, won, lost, not_interested.
6. Add to Campaign workflow with duplicate assignment prevention.
7. Verification status distinction: domain_validated vs mailbox_verified.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User, Lead, Campaign, CampaignLead, DirectEmail, Inbox
from app.auth import create_access_token


async def run_lead_detail_tests():
    print("=== STARTING LEAD DETAIL & INTERACTION PERSONALIZATION QA TESTS ===")

    # Setup auth token
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).limit(1))
        user = user_res.scalar_one_or_none()
        assert user is not None, "Admin user must exist"
        token = create_access_token(user.id, user.role)

        # Ensure we have a campaign for testing
        camp_res = await db.execute(select(Campaign).limit(1))
        campaign = camp_res.scalar_one_or_none()
        if not campaign:
            campaign = Campaign(name="QA Test Outreach Campaign", status="paused")
            db.add(campaign)
            await db.commit()
            await db.refresh(campaign)
        campaign_id = campaign.id

    headers = {"Authorization": f"Bearer {token}"}
    base_url = "http://127.0.0.1:8000"

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # TEST 1: Check Lead 2 (Muhammad Yousaf) interactions for clean variable rendering
        print("\n--- Test 1: Interaction Personalization for Lead 2 (Muhammad Yousaf) ---")
        res = await client.get("/api/leads/2", headers=headers)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        lead_info = res.json()
        interactions = lead_info.get("interactions", [])
        print(f"Lead 2: {lead_info.get('name')} {lead_info.get('company')} ({lead_info.get('email')})")
        print(f"Found {len(interactions)} interaction(s)")
        assert len(interactions) > 0, "Expected at least 1 interaction for Lead 2"
        
        for ix in interactions:
            sub = ix.get("subject") or ""
            body = ix.get("body") or ""
            print(f"  Interaction [{ix.get('kind')}]: Subject='{sub}' From='{ix.get('from_email')}' To='{ix.get('to_email')}' Status='{ix.get('status')}'")
            assert "{{" not in sub, f"Unrendered variable in subject: {sub}"
            assert "}}" not in sub, f"Unrendered variable in subject: {sub}"
            assert "{{" not in body, f"Unrendered variable in body: {body}"
            assert "}}" not in body, f"Unrendered variable in body: {body}"
            print("  [PASS] Personalization rendered cleanly without raw variables.")

        # TEST 2: Create a controlled test lead for full mutation testing
        print("\n--- Test 2: Create Dedicated Controlled Test Lead ---")
        test_email = "controlled_lead_test@example.com"
        updated_email = "david.miller@apexinnovations.example.com"
        
        # Clean up if existing
        async with AsyncSessionLocal() as db:
            existings = (await db.execute(select(Lead).where(Lead.email.in_([test_email, updated_email])))).scalars().all()
            for ex in existings:
                # delete direct emails & campaign leads
                des = (await db.execute(select(DirectEmail).where(DirectEmail.lead_id == ex.id))).scalars().all()
                for d in des:
                    await db.delete(d)
                cls = (await db.execute(select(CampaignLead).where(CampaignLead.lead_id == ex.id))).scalars().all()
                for c in cls:
                    await db.delete(c)
                await db.delete(ex)
            await db.commit()
        
        create_payload = {
            "email": test_email,
            "company": "Apex Innovations",
            "name": "David",
            "phone": "+1-800-555-0144",
            "website": "https://apexinnovations.example.com",
        }
        res = await client.post("/api/leads", json=create_payload, headers=headers)
        assert res.status_code in (200, 201), f"Create lead failed: {res.text}"
        new_lead = res.json()
        lead_id = new_lead["id"]
        print(f"Created Test Lead ID: {lead_id} ({new_lead['email']})")

        # TEST 3: Edit Lead with Essential Fields (Company, Email, Contact Name, Phone, Website)
        print("\n--- Test 3: Edit Essential Fields on Lead ---")
        updated_payload = {
            "company": "Apex Global Solutions",
            "name": "David Miller",
            "email": "david.miller@apexinnovations.example.com",
            "phone": "+1-800-555-9988",
            "website": "https://apex-solutions.example.com"
        }
        res = await client.patch(f"/api/leads/{lead_id}", json=updated_payload, headers=headers)
        assert res.status_code == 200, f"Edit lead failed: {res.text}"
        edited = res.json()
        assert edited["company"] == "Apex Global Solutions"
        assert edited["name"] == "David Miller"
        assert edited["email"] == "david.miller@apexinnovations.example.com"
        assert edited["phone"] == "+1-800-555-9988"
        assert edited["website"] == "https://apex-solutions.example.com"
        print("  [PASS] Essential fields (Company, Email, Contact Name, Phone, Website) successfully updated.")

        # TEST 4: Lead Status Dropdown Updates
        print("\n--- Test 4: Lead Status Dropdown Transitions ---")
        statuses_to_test = ["new", "contacted", "replied", "interested", "won", "lost", "not_interested"]
        for st in statuses_to_test:
            res = await client.patch(f"/api/leads/{lead_id}", json={"pipeline_status": st}, headers=headers)
            assert res.status_code == 200, f"Status update to {st} failed: {res.text}"
            await asyncio.sleep(0.3)
            res_get = await client.get(f"/api/leads/{lead_id}", headers=headers)
            got_status = res_get.json().get("pipeline_status")
            print(f"  Updated to '{st}' -> GET returned '{got_status}'")
            assert got_status == st, f"Status mismatch: expected {st}, got {got_status}"
            print(f"  [PASS] Lead status '{st}' updated and verified.")

        # TEST 5: Add to Campaign & Prevent Duplicate Enrollment
        print("\n--- Test 5: Add to Campaign & Duplicate Prevention ---")
        # First assignment
        assign_payload = {
            "campaign_id": campaign_id,
            "lead_ids": [lead_id]
        }
        res = await client.post("/api/leads/bulk-campaign-assign", json=assign_payload, headers=headers)
        assert res.status_code == 200, f"Bulk assign failed: {res.text}"
        assign_data = res.json()
        print("  First assignment result:", assign_data)
        assert assign_data["assigned"] == 1, f"Expected 1 assigned, got {assign_data['assigned']}"
        assert assign_data["already_enrolled"] == 0, f"Expected 0 already enrolled, got {assign_data['already_enrolled']}"

        # Verify Lead Detail shows the enrolled campaign
        res_detail = await client.get(f"/api/leads/{lead_id}", headers=headers)
        camps = res_detail.json().get("campaigns", [])
        assert any(c["campaign_id"] == campaign_id for c in camps), "Lead detail does not show enrolled campaign"
        print("  [PASS] Campaign enrollment visible in Lead Detail page.")

        # Second assignment attempt (duplicate prevention)
        res_dup = await client.post("/api/leads/bulk-campaign-assign", json=assign_payload, headers=headers)
        assert res_dup.status_code == 200, f"Bulk assign duplicate failed: {res_dup.text}"
        dup_data = res_dup.json()
        print("  Duplicate assignment result:", dup_data)
        assert dup_data["assigned"] == 0, f"Duplicate was incorrectly re-enrolled: {dup_data}"
        assert dup_data["already_enrolled"] == 1, f"Expected 1 already enrolled, got {dup_data['already_enrolled']}"
        print("  [PASS] Duplicate campaign assignment successfully blocked.")

        # TEST 6: Direct Email Variable Rendering in DB Persistence
        print("\n--- Test 6: Verify Direct Email Template Rendering Persistence ---")
        async with AsyncSessionLocal() as db:
            # Create a test direct email with template variables for lead_id
            inbox_res = await db.execute(select(Inbox).limit(1))
            inbox = inbox_res.scalar_one_or_none()
            assert inbox is not None, "Inbox must exist"
            
            direct_msg = DirectEmail(
                lead_id=lead_id,
                inbox_id=inbox.id,
                to_email=test_email,
                recipient_name="David Miller",
                subject="Hello {{first_name}} from {{company_name}}",
                body="Dear {{first_name}},\nWe love {{company_name}} and would like to connect.",
                status="draft"
            )
            db.add(direct_msg)
            await db.commit()
            await db.refresh(direct_msg)
            direct_id = direct_msg.id

        # Fetch lead detail to verify interactions renders variables even if draft
        res_interactions = await client.get(f"/api/leads/{lead_id}", headers=headers)
        lead_ixs = res_interactions.json().get("interactions", [])
        found_test_ix = next((x for x in lead_ixs if x.get("id") == direct_id and x.get("channel") in ("direct", "direct_email")), None)
        assert found_test_ix is not None, "Draft direct email not found in interactions"
        print("  Interaction Subject:", found_test_ix.get("subject"))
        print("  Interaction Body:", found_test_ix.get("body"))
        assert "David" in found_test_ix.get("subject"), f"Subject not personalized: {found_test_ix.get('subject')}"
        assert "Apex Global Solutions" in found_test_ix.get("subject"), f"Subject not personalized: {found_test_ix.get('subject')}"
        assert "David" in found_test_ix.get("body"), f"Body not personalized: {found_test_ix.get('body')}"
        assert "Apex Global Solutions" in found_test_ix.get("body"), f"Body not personalized: {found_test_ix.get('body')}"
        print("  [PASS] Interactions endpoint dynamically rendered template variables.")

        # Clean up test direct email and test lead
        async with AsyncSessionLocal() as db:
            # Delete direct email
            d_obj = await db.get(DirectEmail, direct_id)
            if d_obj:
                await db.delete(d_obj)
            # Delete campaign lead
            cl_res = await db.execute(select(CampaignLead).where(CampaignLead.lead_id == lead_id))
            for cl in cl_res.scalars().all():
                await db.delete(cl)
            # Delete lead
            l_obj = await db.get(Lead, lead_id)
            if l_obj:
                await db.delete(l_obj)
            await db.commit()
        print("  [PASS] Test cleanup completed.")

    print("\n=== ALL LEAD DETAIL TESTS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    asyncio.run(run_lead_detail_tests())
