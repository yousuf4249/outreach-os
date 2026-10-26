"""Comprehensive tests for Campaign Bulk Select, Bulk Delete, and Bulk Archive functionality in Weblinx Outreach OS."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    Campaign,
    CampaignLead,
    CampaignInbox,
    Lead,
    QueueSlot,
    Sequence,
    EmailLog,
)
from app.schemas import (
    BulkCampaignDeleteRequest,
    BulkCampaignArchiveRequest,
)
from app.routers import campaigns as campaigns_router
from tests.conftest import (
    make_campaign,
    make_inbox,
    make_lead,
    make_campaign_lead,
    make_campaign_inbox,
    make_queue_slot,
    make_sequence,
)


@pytest.mark.asyncio
async def test_single_delete_active_campaign_raises_400(session):
    """Accidental deletion of active campaign is blocked; must be paused first."""
    active_camp = await make_campaign(session, name="Active Production Campaign", paused=False)

    with pytest.raises(HTTPException) as exc_info:
        await campaigns_router.delete_campaign(active_camp.id, db=session)
    assert exc_info.value.status_code == 400
    assert "Please pause the campaign before deleting" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_single_delete_paused_campaign_preserves_central_prospects(session):
    """Deleting a paused campaign removes queue slots and campaign_lead, but keeps central prospects intact."""
    paused_camp = await make_campaign(session, name="Paused Pilot Campaign", paused=True)
    inbox = await make_inbox(session, email="inbox_test@example.com")
    await make_campaign_inbox(session, paused_camp.id, inbox.id)

    prospect = await make_lead(session, email="valuable_prospect@company.com", name="Valuable Contact")
    cl = await make_campaign_lead(session, paused_camp.id, prospect.id)
    slot = await make_queue_slot(session, cl.id, inbox.id, sequence_index=0)

    # Delete paused campaign (default purge_leads=False preserves central prospects)
    res = await campaigns_router.delete_campaign(paused_camp.id, db=session)
    assert res == {"ok": True}

    # Verify campaign is deleted
    camp_check = (await session.execute(select(Campaign).where(Campaign.id == paused_camp.id))).scalar_one_or_none()
    assert camp_check is None

    # Verify queue slot is deleted
    slot_check = (await session.execute(select(QueueSlot).where(QueueSlot.id == slot.id))).scalar_one_or_none()
    assert slot_check is None

    # Verify central prospect in Lead table is NOT deleted
    lead_check = (await session.execute(select(Lead).where(Lead.id == prospect.id))).scalar_one_or_none()
    assert lead_check is not None
    assert lead_check.email == "valuable_prospect@company.com"


@pytest.mark.asyncio
async def test_bulk_delete_multiple_paused_campaigns(session):
    """Bulk delete successfully removes multiple paused campaigns."""
    c1 = await make_campaign(session, name="Bulk Paused 1", paused=True)
    c2 = await make_campaign(session, name="Bulk Paused 2", paused=True)
    c3 = await make_campaign(session, name="Bulk Paused 3", paused=True)

    req = BulkCampaignDeleteRequest(campaign_ids=[c1.id, c2.id, c3.id])
    res = await campaigns_router.bulk_delete_campaigns(req, db=session)

    assert res.ok is True
    assert res.deleted_count == 3
    assert res.failed_count == 0
    assert len(res.deleted_campaigns) == 3

    # Confirm all are gone
    camps = (await session.execute(select(Campaign).where(Campaign.id.in_([c1.id, c2.id, c3.id])))).scalars().all()
    assert len(camps) == 0


@pytest.mark.asyncio
async def test_bulk_delete_partial_failure_with_active_campaigns(session):
    """Bulk delete removes paused campaigns but skips active campaigns with clear reporting."""
    paused1 = await make_campaign(session, name="Paused Alpha", paused=True)
    active1 = await make_campaign(session, name="Active Beta", paused=False)
    paused2 = await make_campaign(session, name="Paused Gamma", paused=True)
    active2 = await make_campaign(session, name="Active Delta", paused=False)

    req = BulkCampaignDeleteRequest(campaign_ids=[paused1.id, active1.id, paused2.id, active2.id, 99999])
    res = await campaigns_router.bulk_delete_campaigns(req, db=session)

    assert res.ok is False  # Partial failure
    assert res.deleted_count == 2
    assert res.failed_count == 3  # 2 active + 1 not found

    deleted_ids = [d["id"] for d in res.deleted_campaigns]
    assert paused1.id in deleted_ids
    assert paused2.id in deleted_ids

    failed_reasons = {f["id"]: f["reason"] for f in res.failed_campaigns}
    assert "currently active" in failed_reasons[active1.id]
    assert "currently active" in failed_reasons[active2.id]
    assert "not found" in failed_reasons[99999]

    # Active campaigns still exist
    active_in_db = (await session.execute(select(Campaign).where(Campaign.id.in_([active1.id, active2.id])))).scalars().all()
    assert len(active_in_db) == 2


@pytest.mark.asyncio
async def test_bulk_archive_and_unarchive(session):
    """Bulk archive sets archived flag to True, and unarchive restores to False."""
    c1 = await make_campaign(session, name="Archive Camp 1")
    c2 = await make_campaign(session, name="Archive Camp 2")

    # Bulk Archive
    req_archive = BulkCampaignArchiveRequest(campaign_ids=[c1.id, c2.id], archive=True)
    res_arch = await campaigns_router.bulk_archive_campaigns(req_archive, db=session)
    assert res_arch.ok is True
    assert res_arch.updated_count == 2

    c1_check = (await session.execute(select(Campaign).where(Campaign.id == c1.id))).scalar_one()
    assert c1_check.archived is True

    # Bulk Unarchive
    req_unarchive = BulkCampaignArchiveRequest(campaign_ids=[c1.id, c2.id], archive=False)
    res_unarch = await campaigns_router.bulk_archive_campaigns(req_unarchive, db=session)
    assert res_unarch.ok is True
    assert res_unarch.updated_count == 2

    c1_uncheck = (await session.execute(select(Campaign).where(Campaign.id == c1.id))).scalar_one()
    assert c1_uncheck.archived is False


@pytest.mark.asyncio
async def test_single_toggle_campaign_archive(session):
    """Single toggle endpoint flips archive state."""
    camp = await make_campaign(session, name="Toggle Camp")
    res1 = await campaigns_router.toggle_campaign_archive(camp.id, db=session)
    assert res1["ok"] is True
    assert res1["archived"] is True

    res2 = await campaigns_router.toggle_campaign_archive(camp.id, db=session)
    assert res2["ok"] is True
    assert res2["archived"] is False
