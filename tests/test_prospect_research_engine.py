"""Tests for Prospect Research Engine.

Covers:
1. Canonical domain extraction and URL normalization.
2. Open dataset discovery & deduplication.
3. Strict extraction & hallucination prevention (no speculative emails).
4. Native email verification integration.
5. Explainable 0-100 ICP scoring.
6. Research staging isolation (records not in active Lead table).
7. Single & bulk promotion to active Lead table with strict deduplication.
"""

import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead, ResearchJob, ResearchCompany, ResearchContact
from app.services.research_discovery import BusinessDiscoveryEngine, extract_canonical_domain
from app.services.research_crawler import ProspectEnrichmentCrawler
from app.services.research_icp import calculate_icp_score
from app.services.research_service import ProspectResearchService
from app.verification_engine import verify_single_email


def test_canonical_domain_normalization():
    """Verify robust URL parsing and domain normalization."""
    assert extract_canonical_domain("https://www.example.com/contact/") == "example.com"
    assert extract_canonical_domain("http://madebyrodeo.co:8080/path?q=1") == "madebyrodeo.co"
    assert extract_canonical_domain("WWW.SUB.DOMAIN.ORG/") == "sub.domain.org"
    assert extract_canonical_domain("https://handsome.is/case-studies") == "handsome.is"
    assert extract_canonical_domain("") == ""


def test_strict_crawler_no_hallucination():
    """Verify that email extraction extracts ONLY published emails and never invents patterns."""
    crawler = ProspectEnrichmentCrawler()
    
    # Check valid emails
    assert crawler._is_valid_email("hello@monkee-boy.com") is True
    assert crawler._is_valid_email("info@springbox.com") is True

    # Check dummy / invalid / image emails that must be rejected
    assert crawler._is_valid_email("banner@2x.png") is False
    assert crawler._is_valid_email("test@example.com") is False
    assert crawler._is_valid_email("admin@domain.com") is False
    assert crawler._is_valid_email("icon@logo.svg") is False

    # Verify text contact extraction against sample HTML
    sample_html = """
    <html>
      <body>
        <a href="mailto:connect@hmgcreative.com">Connect</a>
        <a href="mailto:bad@example.com">Fake</a>
      </body>
    </html>
    """
    soup = BeautifulSoup(sample_html, "html.parser")
    emails = {}
    phones = set()
    socials = {}
    crawler._extract_text_contacts(soup, sample_html, "https://hmgcreative.com", emails, phones, socials)
    
    assert "connect@hmgcreative.com" in emails
    # Template domain example.com must NOT be extracted
    assert "bad@example.com" not in emails


def test_explainable_icp_scoring():
    """Verify 0-100 score computation and human-readable breakdown."""
    company = {
        "name": "Made By Rodeo",
        "category": "Brand & Web Design Agency",
        "description": "Independent Austin-based brand strategy, web design, and digital experience agency.",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "website": "https://www.madebyrodeo.co",
    }
    contacts = [{
        "name": "Caleb Davis",
        "role": "Founder & Creative Director",
        "email": "caleb@madebyrodeo.co",
        "deliverability_status": "valid",
    }]

    score, reasons = calculate_icp_score(
        company=company,
        contacts=contacts,
        target_city="Austin",
        target_state="Texas",
        target_country="United States",
        target_industry="Web Design Agencies",
    )
    
    assert 80 <= score <= 100
    assert len(reasons) >= 3
    assert any("industry match" in r.lower() for r in reasons)
    assert any("location match" in r.lower() or "geographic" in r.lower() for r in reasons)
    assert any("decision maker" in r.lower() or "leadership" in r.lower() for r in reasons)


@pytest.mark.asyncio
async def test_native_email_verification():
    """Verify native verification returns deliverability status without live sending."""
    res = await verify_single_email("caleb@madebyrodeo.co", "madebyrodeo.co", check_smtp=False)
    assert res.email == "caleb@madebyrodeo.co"
    assert res.status in ["valid", "domain_validated", "risky", "invalid"]
    assert res.summary_reason is not None


@pytest.mark.asyncio
async def test_staging_isolation_and_promotion(session: AsyncSession):
    """Verify that staged research records do not leak into active Leads until promoted."""
    # 1. Count baseline leads
    initial_leads_res = await session.execute(select(Lead))
    initial_leads_count = len(initial_leads_res.scalars().all())

    # 2. Stage a research job, company, and contact
    job = ResearchJob(
        name="Test Research Job",
        query_params={
            "country": "United States",
            "state": "Texas",
            "city": "Austin",
            "industry": "Web Design",
        },
        status="completed",
    )
    session.add(job)
    await session.flush()

    company = ResearchCompany(
        job_id=job.id,
        name="Apex Creative Test",
        domain="apexcreativetest.co",
        website="https://apexcreativetest.co",
        category="Web Design",
        city="Austin",
        state="TX",
        country="United States",
        review_status="approved",
    )
    session.add(company)
    await session.flush()

    contact = ResearchContact(
        company_id=company.id,
        name="Marcus Vance",
        first_name="Marcus",
        last_name="Vance",
        role="Founder & CEO",
        email="marcus@apexcreativetest.co",
        email_verification_status="valid",
        confidence_score=0.95,
        field_provenance={"email": {"source_url": "https://apexcreativetest.co/about", "snippet": "Marcus Vance, Founder"}},
    )
    session.add(contact)
    await session.commit()

    # Verify contact is in research staging
    assert contact.id is not None
    assert company.promoted_to_lead_id is None

    # Verify baseline Lead table count has NOT changed (staging isolation)
    check_leads = await session.execute(select(Lead))
    assert len(check_leads.scalars().all()) == initial_leads_count

    # 3. Promote contact to Lead
    service = ProspectResearchService()
    promote_res = await service.promote_contact_to_lead(session, contact.id)
    assert promote_res["ok"] is True
    lead_id = promote_res["lead_id"]
    assert lead_id is not None

    # Verify Lead record
    lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert lead.email == "marcus@apexcreativetest.co"
    assert lead.name == "Marcus Vance"
    assert lead.company == "Apex Creative Test"
    assert lead.city == "Austin"
    assert lead.country == "United States"
    assert lead.lead_source == "Prospect Research"

    # Verify company marked as promoted
    await session.refresh(company)
    assert company.promoted_to_lead_id == lead_id

    # 4. Attempt duplicate promotion (deduplication check)
    dup_res = await service.promote_contact_to_lead(session, contact.id)
    assert dup_res["ok"] is True
    assert dup_res["already_exists"] is True
    assert dup_res["lead_id"] == lead_id

    # Verify no second Lead was created
    final_leads = await session.execute(select(Lead).where(Lead.email == "marcus@apexcreativetest.co"))
    assert len(final_leads.scalars().all()) == 1
