"""API router for Email Deliverability and Domain Health Monitoring."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deliverability import (
    analyze_email_headers,
    extract_domain,
    run_domain_health_scan_for_inbox,
)
from app.models import DomainHealthScan, Inbox

logger = logging.getLogger("quickly.deliverability_router")

router = APIRouter(prefix="/api/deliverability", tags=["deliverability"])


class ScanRequest(BaseModel):
    custom_dkim_selector: Optional[str] = Field(None, max_length=128)


class HeaderInspectRequest(BaseModel):
    raw_headers_or_eml: str = Field(..., min_length=10)
    is_demo: bool = False


def _scan_to_dict(scan: DomainHealthScan) -> Dict[str, Any]:
    """Convert DomainHealthScan ORM object to JSON serializable response."""
    return {
        "id": scan.id,
        "inbox_id": scan.inbox_id,
        "domain": scan.domain,
        "overall_status": scan.overall_status,
        "spf_status": scan.spf_status,
        "spf_record": scan.spf_record,
        "spf_details": scan.spf_details or {},
        "dkim_status": scan.dkim_status,
        "dkim_selector": scan.dkim_selector,
        "dkim_record": scan.dkim_record,
        "dkim_details": scan.dkim_details or {},
        "dmarc_status": scan.dmarc_status,
        "dmarc_policy": scan.dmarc_policy,
        "dmarc_record": scan.dmarc_record,
        "dmarc_details": scan.dmarc_details or {},
        "mx_status": scan.mx_status,
        "mx_records": scan.mx_records or [],
        "blocklist_status": scan.blocklist_status,
        "blocklist_details": scan.blocklist_details or {},
        "reputation_status": scan.reputation_status,
        "reputation_details": scan.reputation_details or {},
        "delivery_stats": scan.delivery_stats or {},
        "issues": scan.issues or [],
        "scanned_at": scan.scanned_at.isoformat() if scan.scanned_at else None,
        "created_at": scan.created_at.isoformat() if scan.created_at else None,
    }


@router.get("/inbox/{inbox_id}")
async def get_inbox_health(
    inbox_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the latest domain health scan for an inbox (or auto-scans if none exists)."""
    inbox = await db.get(Inbox, inbox_id)
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    res = await db.execute(
        select(DomainHealthScan)
        .where(DomainHealthScan.inbox_id == inbox_id)
        .order_by(desc(DomainHealthScan.scanned_at))
        .limit(1)
    )
    latest_scan = res.scalar_one_or_none()

    if not latest_scan:
        # Auto-run initial scan
        try:
            latest_scan = await run_domain_health_scan_for_inbox(db, inbox_id)
        except Exception as e:
            logger.error(f"Error running initial health scan for inbox #{inbox_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to scan domain health: {str(e)}")

    data = _scan_to_dict(latest_scan)
    data["inbox_email"] = inbox.email
    data["inbox_provider"] = inbox.provider
    return data


@router.post("/inbox/{inbox_id}/scan")
async def trigger_inbox_health_scan(
    inbox_id: int,
    payload: Optional[ScanRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger an on-demand live domain health scan for an inbox."""
    inbox = await db.get(Inbox, inbox_id)
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    custom_selector = payload.custom_dkim_selector if payload else None

    try:
        scan = await run_domain_health_scan_for_inbox(
            db, inbox_id=inbox_id, custom_dkim_selector=custom_selector
        )
    except Exception as e:
        logger.error(f"Error during on-demand scan for inbox #{inbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Health scan failed: {str(e)}")

    data = _scan_to_dict(scan)
    data["inbox_email"] = inbox.email
    data["inbox_provider"] = inbox.provider
    return data


@router.get("/inbox/{inbox_id}/history")
async def get_inbox_health_history(
    inbox_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve historical scans for an inbox."""
    inbox = await db.get(Inbox, inbox_id)
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    res = await db.execute(
        select(DomainHealthScan)
        .where(DomainHealthScan.inbox_id == inbox_id)
        .order_by(desc(DomainHealthScan.scanned_at))
        .limit(limit)
    )
    scans = res.scalars().all()
    return [_scan_to_dict(s) for s in scans]


@router.post("/inspect-headers")
async def inspect_email_headers(payload: HeaderInspectRequest):
    """Analyze raw email headers or imported .eml string to verify actual recipient-side deliverability."""
    try:
        report = analyze_email_headers(payload.raw_headers_or_eml, is_demo=payload.is_demo)
        return report
    except Exception as e:
        logger.warning(f"Failed to inspect email headers: {e}")
        raise HTTPException(status_code=400, detail=f"Could not parse email headers: {str(e)}")


@router.post("/upload-eml")
async def inspect_uploaded_eml(file: UploadFile = File(...)):
    """Analyze an uploaded .eml file."""
    try:
        content_bytes = await file.read()
        content_str = content_bytes.decode("utf-8", errors="replace")
        report = analyze_email_headers(content_str)
        return report
    except Exception as e:
        logger.warning(f"Failed to inspect uploaded .eml file: {e}")
        raise HTTPException(status_code=400, detail=f"Could not process .eml file: {str(e)}")


@router.post("/recheck-all")
async def trigger_recheck_all_inboxes(db: AsyncSession = Depends(get_db)):
    """Trigger fresh live domain health scans across all configured inboxes."""
    inboxes_res = await db.execute(select(Inbox).order_by(Inbox.id))
    inboxes = inboxes_res.scalars().all()
    results = []
    for ibx in inboxes:
        try:
            scan = await run_domain_health_scan_for_inbox(db, inbox_id=ibx.id)
            data = _scan_to_dict(scan)
            data["inbox_email"] = ibx.email
            results.append(data)
        except Exception as e:
            logger.error(f"Error scanning inbox #{ibx.id}: {e}")
            results.append({"inbox_id": ibx.id, "error": str(e)})
    return {"scanned_count": len(results), "results": results}


@router.get("/summary")
async def get_deliverability_summary(db: AsyncSession = Depends(get_db)):
    """Get system-wide email deliverability & domain health summary across all inboxes and domains."""
    inboxes_res = await db.execute(select(Inbox).order_by(Inbox.id))
    inboxes = inboxes_res.scalars().all()

    summary_list = []
    domains_status: Dict[str, str] = {}
    inbox_healthy_count = 0
    inbox_warning_count = 0
    inbox_critical_count = 0
    inbox_unknown_count = 0

    for ibx in inboxes:
        dom = extract_domain(ibx.email)
        # Fetch latest scan
        s_res = await db.execute(
            select(DomainHealthScan)
            .where(DomainHealthScan.inbox_id == ibx.id)
            .order_by(desc(DomainHealthScan.scanned_at))
            .limit(1)
        )
        scan = s_res.scalar_one_or_none()

        status = scan.overall_status if scan else "unknown"
        if status == "healthy":
            inbox_healthy_count += 1
        elif status == "warning":
            inbox_warning_count += 1
        elif status == "critical":
            inbox_critical_count += 1
        else:
            inbox_unknown_count += 1

        if dom:
            prev_status = domains_status.get(dom)
            if not prev_status or status == "critical" or (status == "warning" and prev_status != "critical"):
                domains_status[dom] = status

        summary_list.append({
            "inbox_id": ibx.id,
            "email": ibx.email,
            "domain": dom,
            "provider": ibx.provider,
            "overall_status": status,
            "spf_status": scan.spf_status if scan else "unknown",
            "dkim_status": scan.dkim_status if scan else "unknown",
            "dmarc_status": scan.dmarc_status if scan else "unknown",
            "blocklist_status": scan.blocklist_status if scan else "clean",
            "last_scanned_at": scan.scanned_at.isoformat() if scan and scan.scanned_at else None,
            "issues_count": len(scan.issues) if scan and scan.issues else 0,
        })

    # Domain aggregate counts
    domain_healthy_count = sum(1 for s in domains_status.values() if s == "healthy")
    domain_warning_count = sum(1 for s in domains_status.values() if s == "warning")
    domain_critical_count = sum(1 for s in domains_status.values() if s == "critical")
    domain_unknown_count = sum(1 for s in domains_status.values() if s not in ("healthy", "warning", "critical"))

    return {
        "total_inboxes": len(inboxes),
        "total_domains": len(domains_status),
        "healthy_domains_count": domain_healthy_count,
        "warning_domains_count": domain_warning_count,
        "critical_domains_count": domain_critical_count,
        # Backward compatibility for summary cards:
        "healthy_count": domain_healthy_count,
        "warning_count": domain_warning_count,
        "critical_count": domain_critical_count,
        "unknown_count": domain_unknown_count,
        "inbox_healthy_count": inbox_healthy_count,
        "inbox_warning_count": inbox_warning_count,
        "inbox_critical_count": inbox_critical_count,
        "inboxes": summary_list,
    }
