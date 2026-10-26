"""Weblinx Outreach OS - Prospect Research Service & Job Orchestrator

Manages:
1. Asynchronous Research Jobs (Start, Pause, Resume, Stop)
2. Discovery, Crawling, Native Verification, and ICP Scoring
3. Staging Database Management (ResearchJob, ResearchCompany, ResearchContact)
4. Multi-level Deduplication (Intra-job, Research DB, Active CRM Leads)
5. Promotion to Active Prospects Database (Phase 8)
6. Research Activity Audit Logging
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import (
    Lead,
    ResearchActivityLog,
    ResearchCompany,
    ResearchContact,
    ResearchJob,
    User,
)
from app.services.research_crawler import ProspectEnrichmentCrawler
from app.services.research_discovery import (
    BusinessDiscoveryEngine,
    extract_canonical_domain,
)
from app.services.research_icp import calculate_icp_score
from app.time import utcnow
from app.verification_engine import verify_single_email

logger = logging.getLogger("weblinx.research.service")

# In-memory tracking of active background job tasks
_active_jobs: Dict[int, asyncio.Task] = {}
_paused_job_ids: Set[int] = set()


class ProspectResearchService:
    """Core orchestrator for discovery, enrichment, verification, and CRM promotion."""

    def __init__(self):
        self.discovery_engine = BusinessDiscoveryEngine()
        self.crawler = ProspectEnrichmentCrawler(timeout=8.0)

    async def create_job(
        self,
        db: AsyncSession,
        name: str,
        query_params: Dict[str, Any],
        user: Optional[User] = None,
        auto_start: bool = True,
    ) -> ResearchJob:
        """Create and queue a new background research job."""
        job = ResearchJob(
            name=name,
            query_params=query_params,
            status="pending",
            total_discovered=0,
            unique_companies=0,
            emails_found=0,
            verified_valid=0,
            created_at=utcnow(),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Log creation
        log = ResearchActivityLog(
            job_id=job.id,
            event_type="created",
            message=f"Research job '{job.name}' configured by {user.email if user else 'system'}",
            created_at=utcnow(),
        )
        db.add(log)
        await db.commit()

        # Start asynchronous worker detached from request session if auto_start
        if auto_start:
            self.start_job_worker(job.id)

        return job

    def start_job_worker(self, job_id: int):
        """Schedule detached worker in asyncio event loop."""
        async def _runner():
            await asyncio.sleep(0.1)
            await self.run_job_worker(job_id)

        task = asyncio.create_task(_runner())
        _active_jobs[job_id] = task

    async def pause_job(self, db: AsyncSession, job_id: int) -> bool:
        """Pause a currently running research job."""
        _paused_job_ids.add(job_id)
        job = await db.get(ResearchJob, job_id)
        if job and job.status == "running":
            job.status = "paused"
            log = ResearchActivityLog(
                job_id=job.id,
                event_type="paused",
                message="Research job execution paused by researcher",
                created_at=utcnow(),
            )
            db.add(log)
            await db.commit()
            return True
        return False

    async def resume_job(self, db: AsyncSession, job_id: int) -> bool:
        """Resume a paused research job."""
        if job_id in _paused_job_ids:
            _paused_job_ids.remove(job_id)

        job = await db.get(ResearchJob, job_id)
        if job and job.status == "paused":
            job.status = "running"
            log = ResearchActivityLog(
                job_id=job.id,
                event_type="resumed",
                message="Research job resumed by researcher",
                created_at=utcnow(),
            )
            db.add(log)
            await db.commit()

            # Launch task if not active
            if job_id not in _active_jobs or _active_jobs[job_id].done():
                task = asyncio.create_task(self.run_job_worker(job.id))
                _active_jobs[job_id] = task
            return True
        return False

    async def cancel_job(self, db: AsyncSession, job_id: int) -> bool:
        """Cancel and terminate a running or paused research job."""
        if job_id in _paused_job_ids:
            _paused_job_ids.remove(job_id)

        if job_id in _active_jobs:
            task = _active_jobs.pop(job_id)
            if not task.done():
                task.cancel()

        job = await db.get(ResearchJob, job_id)
        if job and job.status in ("pending", "running", "paused"):
            job.status = "cancelled"
            job.completed_at = utcnow()
            log = ResearchActivityLog(
                job_id=job.id,
                event_type="cancelled",
                message="Research job cancelled by researcher",
                created_at=utcnow(),
            )
            db.add(log)
            await db.commit()
            return True
        return False

    async def run_job_worker(self, job_id: int, db_session: Optional[AsyncSession] = None):
        """Asynchronous worker that discovers, enriches, verifies, and stages companies."""
        if db_session is not None:
            await self._run_job_worker_core(job_id, db_session)
        else:
            async with AsyncSessionLocal() as db:
                await self._run_job_worker_core(job_id, db)

    async def _run_job_worker_core(self, job_id: int, db: AsyncSession):
        job = await db.get(ResearchJob, job_id)
        if not job:
            return

        try:
            job.status = "running"
            await db.commit()

            params = job.query_params or {}
            country = params.get("country", "United States")
            state = params.get("state", "Texas")
            city = params.get("city", "Austin")
            industry = params.get("industry", "Web Design Agencies")
            keywords = params.get("keywords", [])
            target_count = int(params.get("target_count", 50))
            enable_seed_fallback = bool(params.get("enable_seed_fallback", True))

            log = ResearchActivityLog(
                job_id=job.id,
                event_type="started",
                message=f"Starting discovery for {city}, {state} ({industry}, target: {target_count}, seed_fallback={enable_seed_fallback})",
                created_at=utcnow(),
            )
            db.add(log)
            await db.commit()

            # Phase 3: Discover raw businesses
            discovered = await self.discovery_engine.discover_businesses(
                country=country,
                state=state,
                city=city,
                industry=industry,
                keywords=keywords,
                limit=target_count,
                enable_seed_fallback=enable_seed_fallback,
            )

            job.total_discovered = len(discovered)
            await db.commit()

            # Deduplication & Processing Loop
            for item in discovered:
                # Check pause / cancel requests
                if job.id in _paused_job_ids:
                    job.status = "paused"
                    await db.commit()
                    return

                company_name = item.get("name", "").strip()
                website = item.get("website", "").strip()
                domain = extract_canonical_domain(website or item.get("domain"))

                if not company_name:
                    continue

                # 1. Deduplicate against existing research staged companies in this job
                exist_staged = await db.execute(
                    select(ResearchCompany).where(
                        ResearchCompany.job_id == job.id,
                        or_(
                            func.lower(ResearchCompany.name) == company_name.lower(),
                            ResearchCompany.domain == domain if domain else False,
                        ),
                    )
                )
                if exist_staged.scalar_one_or_none():
                    continue

                # 2. Corroborate against active CRM Leads
                existing_lead = None
                if domain:
                    crm_res = await db.execute(
                        select(Lead).where(func.lower(Lead.website).contains(domain))
                    )
                    existing_lead = crm_res.scalar_one_or_none()
                if not existing_lead:
                    crm_res = await db.execute(
                        select(Lead).where(func.lower(Lead.company) == company_name.lower())
                    )
                    existing_lead = crm_res.scalar_one_or_none()

                # Phase 4: Crawl official website & extract contacts
                enriched = await self.crawler.enrich_company(
                    website_url=website or f"https://{domain}",
                    company_name=company_name,
                    preloaded_seed=item,
                )

                # Create ResearchCompany record
                rc = ResearchCompany(
                    job_id=job.id,
                    name=company_name,
                    domain=domain,
                    website=enriched.get("website") or website,
                    phone=enriched.get("phone") or item.get("phone", ""),
                    address=enriched.get("address") or item.get("address", ""),
                    city=item.get("city") or city,
                    state=item.get("state") or state,
                    country=item.get("country") or country,
                    category=item.get("category") or industry,
                    description=enriched.get("description") or item.get("description", ""),
                    socials={
                        **enriched.get("socials", {}),
                        "title": enriched.get("title", ""),
                        "website_evidence": enriched.get("website_evidence", ""),
                        "headings": enriched.get("headings", []),
                    },
                    source=item.get("source", "overture_maps"),
                    source_id=item.get("source_id"),
                    review_status="pending",
                    assigned_to=params.get("assigned_to", "admin"),
                    existing_lead_id=existing_lead.id if existing_lead else None,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                db.add(rc)
                await db.flush()

                # Phase 5: Email Verification for each extracted contact
                staged_contacts = []
                for c_data in enriched.get("contacts", []):
                    em = c_data.get("email")
                    v_status = "missing"
                    v_details = {}

                    if em:
                        try:
                            v_res = await verify_single_email(
                                email=em,
                                website=rc.website,
                                check_smtp=False,
                            )
                            v_status = v_res.status
                            v_details = v_res.to_dict()
                        except Exception as ve_err:
                            logger.debug("Verification error on %s: %s", em, ve_err)
                            v_status = "unknown"
                            v_details = {"error": str(ve_err)}

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
                    db.add(contact)
                    staged_contacts.append({
                        "email": em,
                        "email_verification_status": v_status,
                        "name": contact.name,
                        "role": contact.role,
                    })

                # Phase 11: Calculate Explainable ICP Score with Website Evidence
                company_meta = {
                    "name": rc.name,
                    "domain": rc.domain,
                    "website": rc.website,
                    "category": rc.category,
                    "description": rc.description,
                    "title": enriched.get("title", ""),
                    "website_evidence": enriched.get("website_evidence", ""),
                    "headings": enriched.get("headings", []),
                    "city": rc.city,
                    "state": rc.state,
                    "country": rc.country,
                    "phone": rc.phone,
                    "socials": rc.socials,
                }
                icp_score, icp_reasons = calculate_icp_score(
                    company=company_meta,
                    contacts=staged_contacts,
                    target_city=city,
                    target_state=state,
                    target_country=country,
                    target_industry=industry,
                )
                rc.icp_score = icp_score
                rc.icp_reasons = icp_reasons
                if "icp_classification" in company_meta:
                    rc.socials = {
                        **(rc.socials or {}),
                        "icp_classification": company_meta["icp_classification"],
                        "business_model_label": company_meta.get("business_model_label", ""),
                    }

                # Update running job totals
                job.unique_companies += 1
                job.emails_found += sum(1 for c in staged_contacts if c.get("email"))
                job.verified_valid += sum(
                    1 for c in staged_contacts
                    if c.get("email_verification_status") in ("valid", "domain_validated")
                )

                await db.commit()

            # Mark Job Completed
            job.status = "completed"
            job.completed_at = utcnow()
            log = ResearchActivityLog(
                job_id=job.id,
                event_type="completed",
                message=(
                    f"Research completed: {job.unique_companies} companies staged, "
                    f"{job.emails_found} emails discovered, {job.verified_valid} verified active"
                ),
                created_at=utcnow(),
            )
            db.add(log)
            await db.commit()

        except asyncio.CancelledError:
            job.status = "cancelled"
            job.completed_at = utcnow()
            await db.commit()
        except Exception as e:
            logger.exception("Error running research job %s: %s", job_id, e)
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = utcnow()
            await db.commit()
        finally:
            _active_jobs.pop(job_id, None)

    async def promote_contact_to_lead(
        self,
        db: AsyncSession,
        contact_id: int,
    ) -> Dict[str, Any]:
        """Promote an approved staged ResearchContact into an active CRM Lead (Phase 8)."""
        contact = await db.get(ResearchContact, contact_id)
        if not contact:
            return {"ok": False, "error": "Research contact not found"}

        company = await db.get(ResearchCompany, contact.company_id)
        if not company:
            return {"ok": False, "error": "Parent research company not found"}

        # Strict Rule: Must have email or phone to be promoted
        clean_email = (contact.email or "").strip().lower()
        if not clean_email:
            return {
                "ok": False,
                "error": "Cannot import contact without a verified email address",
                "reason": "missing_email",
            }

        # Deduplication against active CRM Leads
        existing_res = await db.execute(
            select(Lead).where(func.lower(Lead.email) == clean_email)
        )
        existing_lead = existing_res.scalar_one_or_none()
        if existing_lead:
            company.promoted_to_lead_id = existing_lead.id
            company.review_status = "approved"
            await db.commit()
            return {
                "ok": True,
                "already_exists": True,
                "lead_id": existing_lead.id,
                "message": f"Contact '{clean_email}' already exists in CRM (Lead #{existing_lead.id})",
            }

        # Create active CRM Lead
        lead = Lead(
            email=clean_email,
            name=contact.name or f"{contact.first_name} {contact.last_name}".strip(),
            company=company.name,
            phone=contact.phone or company.phone,
            website=company.website,
            industry=company.category,
            city=company.city,
            country=company.country,
            lead_source="Prospect Research",
            notes=(
                f"Discovered via Weblinx Research Engine.\n"
                f"Title: {contact.role}\n"
                f"ICP Score: {company.icp_score}/100\n"
                f"Source: {company.source} ({company.source_id or 'web'})\n"
                f"Provenance: {contact.field_provenance.get('email', {}).get('snippet', '')}"
            ),
            pipeline_status="prospect",
            status="active",
            email_verification_status=contact.email_verification_status or "domain_validated",
            email_verification_result=contact.email_verification_details,
            created_at=utcnow(),
        )
        db.add(lead)
        await db.flush()

        # Link research company back to CRM Lead
        company.promoted_to_lead_id = lead.id
        company.review_status = "approved"

        # Log promotion
        log = ResearchActivityLog(
            job_id=company.job_id,
            company_id=company.id,
            event_type="promoted",
            message=f"Promoted {contact.name} ({clean_email}) to active CRM Lead #{lead.id}",
            created_at=utcnow(),
        )
        db.add(log)
        await db.commit()

        return {
            "ok": True,
            "imported": True,
            "lead_id": lead.id,
            "company_name": company.name,
            "email": clean_email,
            "message": f"Successfully imported '{clean_email}' as Lead #{lead.id}",
        }

    async def bulk_promote_contacts(
        self,
        db: AsyncSession,
        contact_ids: List[int],
    ) -> Dict[str, Any]:
        """Bulk promote selected research contacts into active CRM Leads (Phase 8)."""
        summary = {
            "total_requested": len(contact_ids),
            "imported": 0,
            "already_exists": 0,
            "missing_email": 0,
            "failed": 0,
            "lead_ids": [],
            "messages": [],
        }

        for cid in contact_ids:
            try:
                res = await self.promote_contact_to_lead(db, cid)
                if res.get("imported"):
                    summary["imported"] += 1
                    summary["lead_ids"].append(res.get("lead_id"))
                elif res.get("already_exists"):
                    summary["already_exists"] += 1
                    summary["lead_ids"].append(res.get("lead_id"))
                elif res.get("reason") == "missing_email":
                    summary["missing_email"] += 1
                else:
                    summary["failed"] += 1
                if res.get("message"):
                    summary["messages"].append(res["message"])
            except Exception as e:
                logger.error("Failed to promote contact %s: %s", cid, e)
                summary["failed"] += 1

        return summary
