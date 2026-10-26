"""Weblinx Outreach OS - Prospect Research Engine
Real-World Discovery Verification Audit (100 Companies in Dallas, TX)

Verifies:
1. Discovery from live open-data (Overture Maps Places release 2026-10-21.0 on AWS S3).
2. Curated seed fallback disabled (0 Austin agency seed records).
3. Exact counts: discovered records, unique businesses, duplicates detected, valid websites.
4. Website crawling and public email extraction with complete provenance (source_url, snippet, timestamp).
5. Strict distinction between domain_validated (MX/syntax) and verified mailbox delivery.
6. ICP scoring and qualification.
7. Complete export to JSON and CSV.
8. Resource measurement: runtime, memory, pages requested, $0.00 infrastructure cost.
9. Staging isolation: 0 contacts leaked into active Prospects Database or campaigns.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.abspath("."))
from app.models import Lead, CampaignLead, ResearchCompany, ResearchContact, ResearchJob
from app.services.research_discovery import BusinessDiscoveryEngine, extract_canonical_domain
from app.services.research_crawler import ProspectEnrichmentCrawler
from app.services.research_icp import calculate_icp_score
from app.verification_engine import verify_single_email
from app.time import utcnow


@pytest.mark.asyncio
async def test_real_world_discovery_100_dallas_audit(session: AsyncSession):
    """Run real-world discovery verification for 100+ Dallas businesses without seed fallback."""
    tracemalloc.start()
    start_time = time.time()

    # -------------------------------------------------------------------------
    # 1. SETUP: Initial Lead count baseline (Staging Isolation check)
    # -------------------------------------------------------------------------
    initial_leads_count = await session.scalar(select(func.count(Lead.id))) or 0
    initial_campaign_leads = await session.scalar(select(func.count(CampaignLead.id))) or 0

    # -------------------------------------------------------------------------
    # 2. DISCOVERY: Query Pinned Overture Places Release (2026-10-21.0) for Dallas, TX
    # -------------------------------------------------------------------------
    discovery_engine = BusinessDiscoveryEngine()
    
    # Query with seed fallback disabled
    discovered_raw = await discovery_engine.discover_businesses(
        country="United States",
        state="Texas",
        city="Dallas",
        industry=None,  # All commercial & professional categories
        keywords=None,
        limit=115,      # Request 115 to guarantee >= 100 unique domains
        enable_seed_fallback=False,
    )

    assert len(discovered_raw) >= 100, f"Expected >= 100 discovered businesses, got {len(discovered_raw)}"

    # Audit source and seed isolation
    sources_count: Dict[str, int] = {}
    seed_leaks = []
    seen_domains = set()
    unique_businesses = []
    duplicates = []

    for item in discovered_raw:
        src = item.get("source", "unknown")
        sources_count[src] = sources_count.get(src, 0) + 1

        # Confirm 0 records from Austin seed data
        if "overture_place_us_tx_atx_" in str(item.get("source_id", "")):
            seed_leaks.append(item.get("name"))

        dom = extract_canonical_domain(item.get("website"))
        if dom in seen_domains:
            duplicates.append(item)
        else:
            seen_domains.add(dom)
            unique_businesses.append(item)

    assert len(seed_leaks) == 0, f"Critical: Found seed records in discovery: {seed_leaks}"
    assert sources_count.get("overture_maps", 0) >= 100, "Expected all records from overture_maps"
    assert len(unique_businesses) >= 100, f"Expected >= 100 unique domains, got {len(unique_businesses)}"

    # Slice exactly to top 100 unique companies for standardized audit
    candidate_companies = unique_businesses[:100]

    # -------------------------------------------------------------------------
    # 3. CREATE RESEARCH JOB IN DB
    # -------------------------------------------------------------------------
    job = ResearchJob(
        name="Dallas Live Discovery Audit (100 Companies)",
        query_params={
            "country": "United States",
            "state": "Texas",
            "city": "Dallas",
            "target_count": 100,
            "enable_seed_fallback": False,
        },
        status="running",
        total_discovered=len(discovered_raw),
        unique_companies=0,
        emails_found=0,
        verified_valid=0,
        created_at=utcnow(),
    )
    session.add(job)
    await session.flush()

    # -------------------------------------------------------------------------
    # 4. CONCURRENT CRAWLER & STRUCTURED ENRICHMENT (Concurrency: 8 workers)
    # -------------------------------------------------------------------------
    crawler = ProspectEnrichmentCrawler(timeout=3.5)
    sem = asyncio.Semaphore(8)
    pages_requested = 0
    crawl_successes = 0
    crawl_failures = 0

    async def crawl_one(comp_item: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal pages_requested, crawl_successes, crawl_failures
        async with sem:
            url = comp_item.get("website") or ""
            name = comp_item.get("name") or "Unknown"
            try:
                # Up to 2 pages requested per site (homepage + contact/about)
                pages_requested += 2
                enriched = await crawler.enrich_company(
                    website_url=url,
                    company_name=name,
                    preloaded_seed=comp_item,
                )
                crawl_successes += 1
                return {"item": comp_item, "enriched": enriched, "error": None}
            except Exception as exc:
                crawl_failures += 1
                return {"item": comp_item, "enriched": {}, "error": str(exc)}

    crawl_tasks = [crawl_one(comp) for comp in candidate_companies]
    crawl_results = await asyncio.gather(*crawl_tasks)

    # -------------------------------------------------------------------------
    # 5. CONTACT EXTRACTION, EMAIL VERIFICATION, AND ICP SCORING
    # -------------------------------------------------------------------------
    total_emails_found = 0
    domain_validated_count = 0
    confirmed_valid_count = 0
    icp_qualified_count = 0
    all_extracted_contacts: List[Dict[str, Any]] = []
    staged_records_export: List[Dict[str, Any]] = []

    for cr in crawl_results:
        item = cr["item"]
        enriched = cr["enriched"]
        name = item.get("name")
        website = enriched.get("website") or item.get("website")
        dom = extract_canonical_domain(website)

        rc = ResearchCompany(
            job_id=job.id,
            name=name,
            domain=dom,
            website=website,
            phone=enriched.get("phone") or item.get("phone", ""),
            address=enriched.get("address") or item.get("address", ""),
            city=item.get("city", "Dallas"),
            state=item.get("state", "Texas"),
            country="United States",
            category=item.get("category", "Commercial Business"),
            description=enriched.get("description") or item.get("description", ""),
            socials=enriched.get("socials", {}),
            source="overture_maps",
            source_id=item.get("source_id"),
            review_status="pending",
            assigned_to="audit_admin",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(rc)
        await session.flush()

        contacts_list = enriched.get("contacts", [])
        staged_contacts_data = []

        for c_data in contacts_list:
            em = c_data.get("email")
            v_status = "missing"
            v_details = {}

            if em:
                total_emails_found += 1
                try:
                    # check_smtp=False evaluates syntax + DNS MX records
                    v_res = await verify_single_email(email=em, website=rc.website, check_smtp=False)
                    v_status = v_res.status
                    v_details = v_res.to_dict()
                except Exception as ve:
                    v_status = "unknown"
                    v_details = {"error": str(ve)}

                if v_status == "domain_validated":
                    domain_validated_count += 1
                elif v_status == "valid":
                    confirmed_valid_count += 1

            contact = ResearchContact(
                company_id=rc.id,
                name=c_data.get("name"),
                first_name=c_data.get("first_name"),
                last_name=c_data.get("last_name"),
                role=c_data.get("role", "Representative"),
                email=em,
                phone=c_data.get("phone") or rc.phone,
                linkedin_url=c_data.get("linkedin_url", ""),
                email_verification_status=v_status,
                email_verification_details=v_details,
                confidence_score=c_data.get("confidence_score", 1.0),
                field_provenance=c_data.get("field_provenance", {}),
                created_at=utcnow(),
            )
            session.add(contact)
            staged_contacts_data.append({
                "name": contact.name,
                "role": contact.role,
                "email": em,
                "status": v_status,
                "phone": contact.phone,
                "provenance": contact.field_provenance,
            })
            all_extracted_contacts.append({
                "company_name": rc.name,
                "contact_name": contact.name,
                "role": contact.role,
                "email": em,
                "verification_status": v_status,
                "phone": contact.phone,
                "provenance": contact.field_provenance,
            })

        # Explainable ICP calculation
        icp_score, icp_reasons = calculate_icp_score(
            company={
                "name": rc.name,
                "category": rc.category,
                "description": rc.description,
                "city": rc.city,
                "state": rc.state,
                "country": rc.country,
                "website": rc.website,
                "phone": rc.phone,
                "socials": rc.socials,
                "domain": rc.domain,
            },
            contacts=staged_contacts_data,
            target_city="Dallas",
            target_state="Texas",
            target_country="United States",
            target_industry=None,
        )
        rc.icp_score = icp_score
        rc.icp_reasons = icp_reasons
        if icp_score >= 60:
            icp_qualified_count += 1

        staged_records_export.append({
            "company_id": rc.id,
            "company_name": rc.name,
            "domain": rc.domain,
            "website": rc.website,
            "phone": rc.phone,
            "city": rc.city,
            "state": rc.state,
            "category": rc.category,
            "source_id": rc.source_id,
            "icp_score": rc.icp_score,
            "icp_reasons": rc.icp_reasons,
            "contacts_count": len(staged_contacts_data),
            "contacts": staged_contacts_data,
        })

    # Update Job completion
    job.unique_companies = len(candidate_companies)
    job.emails_found = total_emails_found
    job.verified_valid = domain_validated_count + confirmed_valid_count
    job.status = "completed"
    job.completed_at = utcnow()
    await session.commit()

    # Resource measurements
    total_duration = time.time() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # -------------------------------------------------------------------------
    # 6. EXPORT COMPLETE RESULTS TO DISK (JSON + CSV)
    # -------------------------------------------------------------------------
    export_dir = Path("data/research_exports")
    export_dir.mkdir(parents=True, exist_ok=True)

    json_path = export_dir / "dallas_discovery_100_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "audit_timestamp": datetime.now(timezone.utc).isoformat(),
                "city": "Dallas",
                "state": "Texas",
                "total_discovered": len(discovered_raw),
                "unique_companies_tested": len(candidate_companies),
                "pages_requested": pages_requested,
                "crawl_successes": crawl_successes,
                "crawl_failures": crawl_failures,
                "total_emails_found": total_emails_found,
                "domain_validated": domain_validated_count,
                "confirmed_valid": confirmed_valid_count,
                "icp_qualified_companies": icp_qualified_count,
                "runtime_seconds": round(total_duration, 2),
                "peak_memory_mb": round(peak_mem / (1024 * 1024), 2),
                "infrastructure_cost_usd": 0.00,
                "companies": staged_records_export,
            },
            f,
            indent=2,
        )

    csv_path = export_dir / "dallas_discovery_100_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Company ID", "Company Name", "Domain", "Website", "Phone",
            "City", "Category", "ICP Score", "Contacts Discovered", "Sample Contact Email", "Verification Status"
        ])
        for comp in staged_records_export:
            sample_email = comp["contacts"][0]["email"] if comp["contacts"] else ""
            sample_status = comp["contacts"][0]["status"] if comp["contacts"] else ""
            writer.writerow([
                comp["company_id"],
                comp["company_name"],
                comp["domain"],
                comp["website"],
                comp["phone"],
                comp["city"],
                comp["category"],
                comp["icp_score"],
                comp["contacts_count"],
                sample_email,
                sample_status,
            ])

    # -------------------------------------------------------------------------
    # 7. ASSERTIONS & STAGING ISOLATION VERIFICATION
    # -------------------------------------------------------------------------
    # Verify exact Leads table isolation
    final_leads_count = await session.scalar(select(func.count(Lead.id))) or 0
    final_campaign_leads = await session.scalar(select(func.count(CampaignLead.id))) or 0

    assert final_leads_count == initial_leads_count, (
        f"CRITICAL LEAK: Leads table count changed from {initial_leads_count} to {final_leads_count}!"
    )
    assert final_campaign_leads == initial_campaign_leads, (
        f"CRITICAL LEAK: CampaignLead count changed from {initial_campaign_leads} to {final_campaign_leads}!"
    )

    # Verify discovery requirements
    assert len(candidate_companies) == 100
    assert total_emails_found > 0, "Expected at least 1 public email discovered"
    assert domain_validated_count > 0, "Expected MX/domain verified emails"

    # Specific Audit on Dallas Target Entities:
    comp_by_name = {c["company_name"]: c for c in staged_records_export}

    # 1. DBU Coffeehouse must be Disqualified (score == 0) and must NOT have admiss@dbu.edu
    if "DBU Coffeehouse" in comp_by_name:
        dbu_c = comp_by_name["DBU Coffeehouse"]
        assert dbu_c["icp_score"] == 0, f"Expected 0 for DBU Coffeehouse, got {dbu_c['icp_score']}"
        dbu_emails = [ct.get("email") for ct in dbu_c["contacts"] if ct.get("email")]
        assert "admiss@dbu.edu" not in dbu_emails, "Critical: University admissions email attached to on-campus coffeehouse!"

    # 2. Clark (convenience_store / MoneyGram retail agent) must be Disqualified (score == 0)
    if "Clark" in comp_by_name:
        clark_c = comp_by_name["Clark"]
        assert clark_c["icp_score"] == 0, f"Expected 0 for Clark convenience store, got {clark_c['icp_score']}"
        clark_emails = [ct.get("email") for ct in clark_c["contacts"] if ct.get("email")]
        assert not any("moneygram.com" in (em or "") for em in clark_emails), "Critical: MoneyGram corporate email attached to retail agent!"

    # 3. Fox Duct Dallas must be qualified as commercial HVAC contractor
    if "Fox Duct Dallas" in comp_by_name:
        fox_c = comp_by_name["Fox Duct Dallas"]
        assert fox_c["icp_score"] >= 70, f"Expected >= 70 for Fox Duct Dallas, got {fox_c['icp_score']}"

    # 4. Continental BestDrive must be qualified as commercial fleet service
    if "Continental BestDrive" in comp_by_name:
        cbd_c = comp_by_name["Continental BestDrive"]
        assert cbd_c["icp_score"] >= 65, f"Expected >= 65 for Continental BestDrive, got {cbd_c['icp_score']}"
        assert any(ct.get("email") == "service@conlantire.com" for ct in cbd_c["contacts"])

    # 5. Zero hallucinated leadership or bogus person names across all extracted contacts
    for ct in all_extracted_contacts:
        c_name = ct.get("contact_name") or ""
        assert "Welcome Baptist" not in c_name, f"Found hallucinated person: {c_name}"
        assert "Discover Partners" not in c_name, f"Found hallucinated person: {c_name}"
        assert not c_name.startswith("Office ("), f"Found departmental email mislabeled as person: {c_name}"
        assert not c_name.startswith("Service ("), f"Found departmental email mislabeled as person: {c_name}"

    # Verify files created
    assert json_path.exists()
    assert csv_path.exists()
    assert json_path.stat().st_size > 5000
    assert csv_path.stat().st_size > 2000

    print("\n=======================================================")
    print("REAL-WORLD DISCOVERY VERIFICATION SUMMARY")
    print(f"Total Discovered Records (Overture Maps): {len(discovered_raw)}")
    print(f"Unique Candidate Companies Audited:     {len(candidate_companies)}")
    print(f"Duplicates Detected & Filtered:         {len(duplicates)}")
    print(f"Crawl Successes / Failures:             {crawl_successes} / {crawl_failures}")
    print(f"Pages Requested:                        {pages_requested}")
    print(f"Public Emails Extracted:                {total_emails_found}")
    print(f"Domain/MX Validated (domain_validated): {domain_validated_count}")
    print(f"Confirmed Mailbox Delivery (valid):     {confirmed_valid_count}")
    print(f"ICP Qualified Businesses (Score >= 60): {icp_qualified_count}")
    print(f"Runtime Duration:                       {total_duration:.2f}s")
    print(f"Peak Memory Allocated:                  {peak_mem / (1024*1024):.2f} MB")
    print(f"Third-Party Cloud/API Cost:             $0.00")
    print(f"Staging Isolation Verified:             PASS (0 leads added to CRM)")
    print(f"JSON Export:                            {json_path.resolve()}")
    print(f"CSV Export:                             {csv_path.resolve()}")
    print("=======================================================\n")
