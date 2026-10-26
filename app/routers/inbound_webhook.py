"""Inbound Webhook API router for Cloudflare Email Routing & Email Workers.

Enables Weblinx Outreach OS to receive incoming emails without traditional IMAP
mailbox hosting. Handles HMAC-SHA256 signature verification, replay protection,
MIME parsing, attachment extraction, deduplication, thread matching, and
automated campaign stop-on-reply.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EmailAttachment, EmailLog, Inbox, SmtpMessage
from app.services.attachment_storage import attachment_storage
from app.smtp_utils import normalise_message_id, parse_mime_message
from app.unibox import _process_smtp_inbound_message

log = logging.getLogger("quickly.inbound_webhook")

router = APIRouter(prefix="/api/inbound", tags=["inbound-webhook"])

MAX_BODY_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB max inbound email size
REPLAY_WINDOW_SECONDS = 300  # 5 minutes replay attack window


async def _get_webhook_secret(db: AsyncSession) -> str:
    """Get the shared secret for HMAC verification from DB or environment."""
    try:
        from app.app_settings import get_setting
        db_secret = await get_setting(db, "cloudflare_inbound_webhook_secret")
        if db_secret and db_secret.strip():
            return db_secret.strip()
    except Exception:
        pass

    return (
        os.environ.get("CLOUDFLARE_INBOUND_WEBHOOK_SECRET")
        or os.environ.get("WEBHOOK_SECRET")
        or ""
    ).strip()


def _verify_hmac_signature(
    raw_body: bytes,
    timestamp: str,
    provided_signature: str,
    secret: str,
) -> bool:
    """Verify HMAC-SHA256 signature using constant-time comparison."""
    if not secret:
        # In development / test mode with no secret configured, allow through with warning
        log.warning("Inbound webhook: CLOUDFLARE_INBOUND_WEBHOOK_SECRET not set; signature check skipped.")
        return True

    if not provided_signature or not timestamp:
        return False

    # Check timestamp replay tolerance
    try:
        ts_float = float(timestamp)
        now = time.time()
        if abs(now - ts_float) > REPLAY_WINDOW_SECONDS:
            log.warning("Inbound webhook rejected: timestamp %s is outside tolerance (%s s)", timestamp, REPLAY_WINDOW_SECONDS)
            return False
    except (ValueError, TypeError):
        return False

    # Expected signature: HMAC_SHA256(secret, timestamp + "." + raw_body)
    data_to_sign = f"{timestamp}.".encode("utf-8") + raw_body
    expected = hmac.new(secret.encode("utf-8"), data_to_sign, hashlib.sha256).hexdigest()

    return secrets.compare_digest(provided_signature.lower().strip(), expected.lower().strip())


@router.post("/cloudflare")
async def receive_cloudflare_email(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
    x_webhook_timestamp: Optional[str] = Header(None, alias="X-Webhook-Timestamp"),
    x_webhook_event_id: Optional[str] = Header(None, alias="X-Webhook-Event-ID"),
    x_envelope_to: Optional[str] = Header(None, alias="X-Envelope-To"),
    x_envelope_from: Optional[str] = Header(None, alias="X-Envelope-From"),
    x_cf_spf: Optional[str] = Header(None, alias="X-Cf-Spf"),
    x_cf_dkim: Optional[str] = Header(None, alias="X-Cf-Dkim"),
    x_cf_dmarc: Optional[str] = Header(None, alias="X-Cf-Dmarc"),
):
    """Receive and process incoming RFC 822 email payload from Cloudflare Email Worker."""
    # 1. Size guard
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum allowed size (25MB)")

    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(status_code=400, detail="Empty email body received")

    # 2. Cryptographic signature verification
    secret = await _get_webhook_secret(db)
    if secret:
        is_valid = _verify_hmac_signature(
            raw_body=raw_body,
            timestamp=x_webhook_timestamp or "",
            provided_signature=x_webhook_signature or "",
            secret=secret,
        )
        if not is_valid:
            log.warning("Inbound webhook rejected: invalid HMAC signature from %s", request.client.host if request.client else "unknown")
            raise HTTPException(status_code=401, detail="Invalid webhook signature or expired timestamp")

    # 3. Parse MIME structure
    try:
        parsed = parse_mime_message(raw_body)
    except Exception as exc:
        log.error("Failed to parse inbound MIME email: %s", exc, exc_info=True)
        raise HTTPException(status_code=422, detail="Failed to parse RFC 822 MIME structure") from exc

    # 4. Resolve destination inbox
    candidate_recipients: list[str] = []
    if x_envelope_to:
        candidate_recipients.append(x_envelope_to.lower().strip())
    for addr in parsed.get("to") or []:
        if addr and addr.lower().strip() not in candidate_recipients:
            candidate_recipients.append(addr.lower().strip())

    inbox: Optional[Inbox] = None
    for cand in candidate_recipients:
        res = await db.execute(select(Inbox).where(Inbox.email == cand))
        match = res.scalar_one_or_none()
        if match:
            inbox = match
            break

    # If direct email didn't match, check for domain catch-all inbox
    if not inbox and candidate_recipients:
        domain_part = candidate_recipients[0].split("@")[-1] if "@" in candidate_recipients[0] else ""
        if domain_part:
            domain_res = await db.execute(
                select(Inbox).where(Inbox.email.like(f"%@{domain_part}")).limit(1)
            )
            inbox = domain_res.scalar_one_or_none()

    if not inbox:
        log.info(
            "Inbound email ignored: recipient(s) %s do not match any configured inbox",
            candidate_recipients,
        )
        return {"ok": True, "ignored": "inbox_not_found", "recipients": candidate_recipients}

    # 5. Deduplication by RFC Message-ID
    rfc_mid = parsed.get("message_id") or ""
    if rfc_mid:
        dup_res = await db.execute(
            select(SmtpMessage).where(
                SmtpMessage.inbox_id == inbox.id,
                SmtpMessage.rfc_message_id == rfc_mid,
            ).limit(1)
        )
        if dup_res.scalar_one_or_none() is not None:
            log.info("Inbound email duplicate ignored: %s in inbox %s", rfc_mid, inbox.id)
            return {"ok": True, "duplicate": True, "message_id": rfc_mid}

    # 6. Generate stable message primary key
    message_pk = f"wh:{x_webhook_event_id or uuid.uuid4().hex[:16]}"

    # 7. Thread resolution: match In-Reply-To or References to EmailLog or SmtpMessage
    candidates = [c for c in ([parsed.get("in_reply_to")] + list(parsed.get("references") or [])) if c]
    thread_key = ""
    if candidates:
        log_res = await db.execute(
            select(EmailLog.thread_id).where(
                EmailLog.inbox_id == inbox.id,
                EmailLog.message_id.in_(candidates),
            ).limit(1)
        )
        hit = log_res.scalar_one_or_none()
        if hit:
            thread_key = hit
        else:
            # Check SmtpMessage
            prev_msg_res = await db.execute(
                select(SmtpMessage.thread_key).where(
                    SmtpMessage.inbox_id == inbox.id,
                    SmtpMessage.rfc_message_id.in_(candidates),
                ).limit(1)
            )
            prev_hit = prev_msg_res.scalar_one_or_none()
            if prev_hit:
                thread_key = prev_hit

    if not thread_key:
        thread_key = parsed.get("message_id") or normalise_message_id(f"<{message_pk}@{inbox.email}>")

    # 8. Save attachments securely
    saved_attachments = []
    for att in parsed.get("attachments", []):
        try:
            stype, spath, ssize = attachment_storage.save_attachment(
                inbox_id=inbox.id,
                filename=att.get("filename"),
                content_type=att.get("content_type"),
                data=att.get("data", b""),
            )
            db_att = EmailAttachment(
                inbox_id=inbox.id,
                message_id=message_pk,
                filename=att.get("filename"),
                content_type=att.get("content_type"),
                size_bytes=ssize,
                storage_type=stype,
                storage_path=spath,
                content_id=att.get("content_id"),
            )
            db.add(db_att)
            saved_attachments.append({
                "filename": att.get("filename"),
                "size_bytes": ssize,
                "content_type": att.get("content_type"),
            })
        except Exception as e:
            log.warning("Failed to store attachment: %s", e)

    # 9. Ingest message, match lead, halt sequences on reply, and emit SSE events
    msg_row, created, touched = await _process_smtp_inbound_message(
        db,
        inbox=inbox,
        parsed=parsed,
        message_pk=message_pk,
        thread_key=thread_key,
    )

    await db.commit()

    log.info(
        "Inbound webhook processed message_id=%s thread_key=%s inbox_id=%s attachments=%d",
        message_pk,
        thread_key,
        inbox.id,
        len(saved_attachments),
    )

    return {
        "ok": True,
        "message_id": message_pk,
        "thread_key": thread_key,
        "inbox_id": inbox.id,
        "attachments_count": len(saved_attachments),
    }
