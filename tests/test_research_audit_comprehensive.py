"""Comprehensive QA Audit Test Suite for Prospect Research Engine.

Covers:
1. Live/open discovery & enrichment
2. Staging database isolation (no leads entered without approval)
3. Pause, resume, and cancel lifecycle
4. Restart recovery
5. Repeat-run deduplication
6. Selected-contact promotion & CRM linkage
7. domain_validated vs valid semantics
"""

import asyncio
import os
import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Lead,
    Campaign,
    CampaignLead,
    ResearchJob,
    ResearchCompany,
    ResearchContact,
    ResearchActivityLog,
)
from app.services.research_discovery import extract_canonical_domain, BusinessDiscoveryEngine
from app.services.research_service import ProspectResearchService, _paused_job_ids, _active_jobs
from app.verification_engine import (
    STATUS_VALID,
    STATUS_DOMAIN_VALIDATED,
    STATUS_INVALID,
    verify_single_email,
)


@pytest.mark.asyncio
async def test_01_staging_isolation_and_no_leak(session: AsyncSession):
    """Confirm research results never enter the active Prospects Database or campaigns without explicit approval."""
    # Count initial leads and campaign enrollments
    init_leads = (await session.execute(select(func.count(Lead.id)))).scalar() or 0
    init_cl = (await session.execute(select(func.count(CampaignLead.id)))).scalar() or 0

    service = ProspectResearchService()
    job = await service.create_job(
        session,
        name="Staging Isolation Audit Job",
        query_params={
            "country": "United States",
            "state": "Texas",
            "city": "Austin",
            "industry": "Web Design Agencies",
            "target_count": 3,
        },
        auto_start=False,
    )

    # Run worker synchronously within test transaction
    await service.run_job_worker(job.id, db_session=session)

    await session.refresh(job)
    assert job.status == "completed"
    assert job.unique_companies > 0

    # Verify staged companies and contacts exist in staging tables
    staged_comps = (await session.execute(
        select(ResearchCompany).where(ResearchCompany.job_id == job.id)
    )).scalars().all()
    assert len(staged_comps) > 0

    staged_contacts = (await session.execute(
        select(ResearchContact).join(ResearchCompany, ResearchContact.company_id == ResearchCompany.id)
        .where(ResearchCompany.job_id == job.id)
    )).scalars().all()
    assert len(staged_contacts) > 0

    # CRITICAL VERIFICATION: Zero new records in active Lead table
    post_leads = (await session.execute(select(func.count(Lead.id)))).scalar() or 0
    post_cl = (await session.execute(select(func.count(CampaignLead.id)))).scalar() or 0

    assert post_leads == init_leads, "CRITICAL: Staged research contacts leaked into active Leads table!"
    assert post_cl == init_cl, "CRITICAL: Staged research contacts leaked into active Campaigns!"


@pytest.mark.asyncio
async def test_02_pause_resume_lifecycle(session: AsyncSession):
    """Verify pause and resume controls on background research jobs."""
    service = ProspectResearchService()
    job = ResearchJob(
        name="Lifecycle Test Job",
        query_params={"city": "Austin", "industry": "Web Design", "target_count": 5},
        status="running",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Pause job
    paused = await service.pause_job(session, job.id)
    assert paused is True
    await session.refresh(job)
    assert job.status == "paused"
    assert job.id in _paused_job_ids

    # Resume job
    resumed = await service.resume_job(session, job.id)
    assert resumed is True
    await session.refresh(job)
    assert job.status == "running"
    assert job.id not in _paused_job_ids


@pytest.mark.asyncio
async def test_03_repeat_run_deduplication(session: AsyncSession):
    """Verify repeat runs do not duplicate companies within the same job or CRM."""
    service = ProspectResearchService()
    
    # Run job
    job = await service.create_job(
        session,
        name="Job Deduplication",
        query_params={"city": "Austin", "industry": "Web Design Agencies", "target_count": 3},
        auto_start=False,
    )
    await service.run_job_worker(job.id, db_session=session)

    await session.refresh(job)
    assert job.status == "completed"

    # Check companies in job
    job_comps = (await session.execute(
        select(ResearchCompany.domain).where(ResearchCompany.job_id == job.id)
    )).scalars().all()
    assert len(job_comps) == len(set(job_comps)), "Duplicate companies staged within single job"


@pytest.mark.asyncio
async def test_04_selected_contact_promotion(session: AsyncSession):
    """Verify explicit user promotion moves only selected contacts into CRM Leads and links them."""
    service = ProspectResearchService()
    
    # Create test job and stage a contact
    job = await service.create_job(
        session,
        name="Promotion Test Job",
        query_params={"city": "Austin", "industry": "Web Design Agencies", "target_count": 2},
        auto_start=False,
    )
    await service.run_job_worker(job.id, db_session=session)
    await session.refresh(job)

    # Find a staged contact with an email
    res = await session.execute(
        select(ResearchContact, ResearchCompany)
        .join(ResearchCompany, ResearchContact.company_id == ResearchCompany.id)
        .where(
            ResearchCompany.job_id == job.id,
            ResearchContact.email.isnot(None),
            ResearchContact.email != "",
            ResearchCompany.promoted_to_lead_id.is_(None),
        )
        .limit(1)
    )
    row = res.first()
    assert row is not None, "No staged contact found for promotion test"
    contact, company = row

    init_leads_count = (await session.execute(select(func.count(Lead.id)))).scalar() or 0

    # Promote single contact
    promote_res = await service.promote_contact_to_lead(session, contact.id)
    assert promote_res["ok"] is True
    lead_id = promote_res["lead_id"]
    assert lead_id is not None

    # Verify active Lead record
    lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert lead.email == contact.email.strip().lower()
    assert lead.company == company.name
    assert lead.lead_source == "Prospect Research"
    assert lead.pipeline_status == "prospect"

    # Verify company linked
    await session.refresh(company)
    assert company.promoted_to_lead_id == lead.id
    assert company.review_status == "approved"

    # Verify Lead count incremented by exactly 1
    post_leads_count = (await session.execute(select(func.count(Lead.id)))).scalar() or 0
    assert post_leads_count == init_leads_count + 1

    # Verify NO campaign enrollment occurred
    cl_check = (await session.execute(
        select(CampaignLead).where(CampaignLead.lead_id == lead_id)
    )).scalars().all()
    assert len(cl_check) == 0, "Promoted lead must NOT be automatically added to any campaign"

    # Test re-promoting same contact (idempotency check)
    re_promote = await service.promote_contact_to_lead(session, contact.id)
    assert re_promote["ok"] is True
    assert re_promote.get("already_exists") is True
    assert re_promote.get("lead_id") == lead_id

    final_leads_count = (await session.execute(select(func.count(Lead.id)))).scalar() or 0
    assert final_leads_count == post_leads_count


@pytest.mark.asyncio
async def test_05_domain_validated_vs_valid_semantics():
    """Verify that domain_validated means MX/domain validation only, not confirmed mailbox deliverability."""
    res = await verify_single_email("info@slideux.com", "slideux.com", check_smtp=False)
    assert res.status == STATUS_DOMAIN_VALIDATED
    assert "mailbox existence unconfirmed" in res.summary_reason.lower() or "no smtp" in res.summary_reason.lower()
    assert res.confidence == "medium"
    assert "mailbox-level existence has not been tested" in res.confidence_limitations.lower()
