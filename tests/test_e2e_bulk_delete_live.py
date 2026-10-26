"""Live API End-to-End Verification for Bulk Campaign Operations in Weblinx Outreach OS."""

import asyncio
import json
import urllib.request
from app.auth import create_access_token
from app.database import AsyncSessionLocal, init_db
from app.models import Campaign, Lead, CampaignLead, QueueSlot, Inbox
from sqlalchemy import select


def make_request(path, method='GET', data=None, token=None):
    url = f"http://127.0.0.1:8000{path}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    req_data = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            return e.code, json.loads(body)
        except:
            return e.code, body


async def main():
    await init_db()
    token = create_access_token('1', role='admin')
    print("=== LIVE E2E VERIFICATION: CAMPAIGN BULK OPERATIONS ===")

    # 1. Create 3 isolated test campaigns in DB
    async with AsyncSessionLocal() as session:
        # Get an inbox
        inbox = (await session.execute(select(Inbox))).scalars().first()
        if not inbox:
            inbox = Inbox(email="bulk_test_inbox@example.com")
            session.add(inbox)
            await session.flush()

        # Create isolated central prospect
        prospect = Lead(
            email="e2e_central_prospect@example.com",
            name="E2E Central Lead",
            company="Central Database Corp"
        )
        session.add(prospect)
        await session.flush()

        # Create 2 paused campaigns and 1 active campaign
        camp_paused1 = Campaign(name="[E2E-TEST] Paused Camp 1", paused=True)
        camp_paused2 = Campaign(name="[E2E-TEST] Paused Camp 2", paused=True)
        camp_active = Campaign(name="[E2E-TEST] Active Camp Protected", paused=False)
        session.add_all([camp_paused1, camp_paused2, camp_active])
        await session.flush()

        # Enroll prospect in paused camp 1 and create queue slot
        cl = CampaignLead(campaign_id=camp_paused1.id, lead_id=prospect.id)
        session.add(cl)
        await session.flush()

        slot = QueueSlot(
            campaign_lead_id=cl.id,
            inbox_id=inbox.id,
            sequence_index=0,
            scheduled_date=prospect.created_at,
            position_in_day=1
        )
        session.add(slot)
        await session.commit()

        p1_id = camp_paused1.id
        p2_id = camp_paused2.id
        act_id = camp_active.id
        prospect_id = prospect.id
        slot_id = slot.id

    print(f"Created isolated test data: Paused IDs=[{p1_id}, {p2_id}], Active ID={act_id}, Lead ID={prospect_id}")

    # 2. Test Single Delete on Active Campaign -> Expect 400
    status, res = make_request(f"/api/campaigns/{act_id}", method='DELETE', token=token)
    print(f"Single Delete Active Campaign -> HTTP {status}: {res}")
    assert status == 400, f"Expected 400, got {status}"
    assert "Please pause the campaign before deleting" in res.get("detail", "")
    print("  [PASS] Single delete on active campaign safely blocked with HTTP 400.")

    # 3. Test Bulk Archive
    status, res = make_request("/api/campaigns/bulk-archive", method='POST', data={
        "campaign_ids": [p1_id, p2_id],
        "archive": True
    }, token=token)
    print(f"Bulk Archive -> HTTP {status}: {res}")
    assert status == 200 and res.get("updated_count") == 2
    print("  [PASS] Bulk archive updated 2 campaigns.")

    # 4. Test Bulk Delete with mixed [Paused 1, Paused 2, Active]
    status, res = make_request("/api/campaigns/bulk-delete", method='POST', data={
        "campaign_ids": [p1_id, p2_id, act_id]
    }, token=token)
    print(f"Bulk Delete Mixed -> HTTP {status}: {res}")
    assert status == 200
    assert res.get("deleted_count") == 2
    assert res.get("failed_count") == 1
    deleted_ids = [d["id"] for d in res.get("deleted_campaigns", [])]
    assert p1_id in deleted_ids and p2_id in deleted_ids
    failed_ids = [f["id"] for f in res.get("failed_campaigns", [])]
    assert act_id in failed_ids
    print("  [PASS] Bulk delete safely deleted 2 paused campaigns and skipped the active campaign.")

    # 5. Verify database integrity
    async with AsyncSessionLocal() as session:
        # Check deleted campaigns
        c1 = (await session.execute(select(Campaign).where(Campaign.id == p1_id))).scalar_one_or_none()
        c2 = (await session.execute(select(Campaign).where(Campaign.id == p2_id))).scalar_one_or_none()
        assert c1 is None and c2 is None, "Paused campaigns should be deleted"

        # Check active campaign remains intact
        c_act = (await session.execute(select(Campaign).where(Campaign.id == act_id))).scalar_one_or_none()
        assert c_act is not None, "Active campaign should still exist in DB"

        # Check queue slot was safely removed
        slot_in_db = (await session.execute(select(QueueSlot).where(QueueSlot.id == slot_id))).scalar_one_or_none()
        assert slot_in_db is None, "Queue slot should have been removed"

        # CRITICAL (Requirement 10): Central prospect in Lead table is NOT deleted!
        lead_in_db = (await session.execute(select(Lead).where(Lead.id == prospect_id))).scalar_one_or_none()
        assert lead_in_db is not None, "Central prospect must remain intact in Prospects database!"
        assert lead_in_db.email == "e2e_central_prospect@example.com"
        print("  [PASS] Central prospect in Lead table remained 100% intact!")

        # Clean up the remaining active campaign and test lead
        await session.delete(c_act)
        await session.delete(lead_in_db)
        await session.commit()
        print("  [PASS] Test teardown completed cleanly.")

    print("\n=== ALL LIVE E2E BULK OPERATION TESTS PASSED SUCCESSFULLY! ===")


if __name__ == '__main__':
    asyncio.run(main())
