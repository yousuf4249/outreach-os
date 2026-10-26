"""Native Self-Hosted Email Verification Engine.

Performs multi-stage email deliverability and syntax verification without external paid APIs:
1. RFC 5322 Syntax validation & Unicode IDNA normalization (via email-validator)
2. Common domain typo detection & suggestions
3. Offline disposable / throwaway email domain lookup (97,000+ domain dataset)
4. Separate role-based address detection (stored independently from technical deliverability)
5. DNS existence, MX record lookup, and Null MX (RFC 7505) detection
6. Optional respectful SMTP recipient verification & catch-all probing
7. Honest classification: never assumes an address is guaranteed deliverable.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app.deliverability import get_dns_resolver
from app.verification_data import (
    check_role_account,
    check_typo_suggestion,
    is_disposable_domain,
)

logger = logging.getLogger("quickly.verification_engine")

# ── Status Constants ────────────────────────────────────────────────────────
STATUS_VALID = "valid"                      # Handshake accepted + verified non-catch-all
STATUS_DOMAIN_VALIDATED = "domain_validated"# Syntax & MX verified; mailbox existence unconfirmed
STATUS_INVALID = "invalid"                  # Syntax failure, dead domain, Null MX, or disposable
STATUS_RISKY = "risky"                      # Identified deliverability risks (e.g. typo, suspicious structure)
STATUS_CATCH_ALL = "catch_all"              # Server accepts all addresses; individual mailbox unconfirmed
STATUS_UNKNOWN = "unknown"                  # Temporary DNS failure, greylisting (451), or timeout
STATUS_NOT_VERIFIED = "not_verified"        # Unverified

# Statuses that are confirmed safe for immediate outbound sending without review
SENDABLE_STATUSES = frozenset({STATUS_VALID, STATUS_DOMAIN_VALIDATED})

# Statuses strictly blocked from campaign queues
BLOCKED_STATUSES = frozenset({STATUS_INVALID})

# Statuses requiring explicit user review / approval before campaign dispatch
REVIEW_REQUIRED_STATUSES = frozenset({
    STATUS_UNKNOWN,
    STATUS_CATCH_ALL,
    STATUS_RISKY,
    STATUS_NOT_VERIFIED,
})


class VerificationResult:
    """Detailed verification outcome container."""

    def __init__(
        self,
        email: str,
        status: str,
        summary_reason: str,
        confidence: str = "medium",  # "high", "medium", "low"
        confidence_limitations: str = "",
        syntax_details: Optional[Dict[str, Any]] = None,
        domain_details: Optional[Dict[str, Any]] = None,
        disposable_details: Optional[Dict[str, Any]] = None,
        role_details: Optional[Dict[str, Any]] = None,
        typo_details: Optional[Dict[str, Any]] = None,
        smtp_details: Optional[Dict[str, Any]] = None,
        domain_mismatch_details: Optional[Dict[str, Any]] = None,
    ):
        self.email = email
        self.status = status
        self.summary_reason = summary_reason
        self.confidence = confidence
        self.confidence_limitations = confidence_limitations
        self.verified_at = datetime.now(timezone.utc).isoformat()
        self.syntax = syntax_details or {}
        self.domain = domain_details or {}
        self.disposable = disposable_details or {}
        self.role_based = role_details or {}
        self.typo = typo_details or {}
        self.smtp = smtp_details or {}
        self.domain_mismatch = domain_mismatch_details or {}

    @property
    def reason(self) -> str:
        return self.summary_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "status": self.status,
            "summary_reason": self.summary_reason,
            "reason": self.summary_reason,
            "confidence": self.confidence,
            "confidence_limitations": self.confidence_limitations,
            "verified_at": self.verified_at,
            "syntax": self.syntax,
            "domain": self.domain,
            "disposable": self.disposable,
            "role_based": self.role_based,
            "typo": self.typo,
            "smtp": self.smtp,
            "domain_mismatch": self.domain_mismatch,
        }


def extract_domain_from_url(url: Optional[str]) -> str:
    """Extract and normalize clean domain name from a website URL.
    
    Examples:
    - 'https://afire-media.com/about' -> 'afire-media.com'
    - 'http://www.afire-media.com' -> 'afire-media.com'
    - 'afire-media.com' -> 'afire-media.com'
    """
    if not url or not isinstance(url, str):
        return ""
    clean = url.strip()
    if not clean:
        return ""
    import urllib.parse
    if not (clean.startswith("http://") or clean.startswith("https://")):
        clean = "http://" + clean
    try:
        parsed = urllib.parse.urlparse(clean)
        hostname = (parsed.hostname or "").lower().strip()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return ""


def check_website_domain_mismatch(
    email_domain: str,
    website: Optional[str],
    email_status: str,
    local_part: str = "",
) -> Dict[str, Any]:
    """Identify if the email domain fails or is risky while the prospect's recorded website differs."""
    if not website or not email_domain:
        return {}

    website_domain = extract_domain_from_url(website)
    if not website_domain or website_domain.lower() == email_domain.lower():
        return {}

    # We flag mismatch if email is invalid, risky, or unknown
    if email_status in (STATUS_INVALID, STATUS_RISKY, STATUS_UNKNOWN):
        try:
            web_exists, web_has_mx, _, _, web_provider, _ = check_domain_dns_and_mx(
                website_domain, timeout=2.5
            )
        except Exception:
            web_exists, web_has_mx, web_provider = False, False, "Unknown"

        suggested_email = f"{local_part}@{website_domain}" if local_part else None

        advisory_msg = (
            f"Email domain '{email_domain}' failed DNS/MX checks, but the company website "
            f"uses '{website_domain}'"
        )
        if web_has_mx:
            advisory_msg += f" (active mail servers detected via {web_provider})."
        elif web_exists:
            advisory_msg += " (website domain exists in DNS)."
        else:
            advisory_msg += "."

        advisory_msg += f" Consider verifying if the contact's email address should be @{website_domain}."

        return {
            "has_mismatch": True,
            "email_domain": email_domain,
            "website_domain": website_domain,
            "website_exists": web_exists,
            "website_has_mx": web_has_mx,
            "website_provider": web_provider,
            "advisory": advisory_msg,
            "suggested_email": suggested_email,
        }
    return {}


def validate_syntax_and_normalize(email: str) -> Tuple[bool, str, str, str, str]:
    """Validate email syntax under RFC 5322 and IDNA rules.
    
    Returns (is_valid, normalized_email, local_part, domain, error_message).
    """
    if not email or not isinstance(email, str):
        return False, "", "", "", "Empty or non-string email address"

    raw = email.strip()
    if not raw or "@" not in raw:
        return False, raw, "", "", "Missing '@' separator in email address"

    try:
        # We perform our own DNS lookups in step 5, so check_deliverability=False
        validated = validate_email(raw, check_deliverability=False)
        local = validated.local_part
        domain = validated.domain
        # Standardize B2B prospect normalization: lowercased domain and ASCII local-part
        norm_email = f"{local.lower()}@{domain.lower()}"
        return True, norm_email, local, domain, ""
    except EmailNotValidError as e:
        return False, raw, "", "", str(e)
    except Exception as e:
        return False, raw, "", "", f"Syntax validation error: {str(e)}"


def check_domain_dns_and_mx(
    domain: str,
    timeout: float = 3.5,
) -> Tuple[bool, bool, bool, List[Dict[str, Any]], str, str]:
    """Perform authoritative DNS MX and Null MX lookups.
    
    Returns:
        (domain_exists, has_mx, is_null_mx, mx_records, detected_provider, error_message)
    """
    resolver = get_dns_resolver(timeout=timeout)
    clean_domain = domain.strip().lower()

    # 1. Query MX records
    mx_list: List[Dict[str, Any]] = []
    is_null_mx = False
    try:
        answers = resolver.resolve(clean_domain, "MX")
        for rdata in answers:
            host = rdata.exchange.to_text().rstrip(".")
            pref = rdata.preference
            # RFC 7505: Null MX is defined as priority 0 and target "."
            if pref == 0 and (host == "" or host == "."):
                is_null_mx = True
            mx_list.append({"priority": pref, "host": host})
    except dns.resolver.NXDOMAIN:
        return False, False, False, [], "None", "Domain does not exist in DNS (NXDOMAIN)"
    except dns.resolver.NoAnswer:
        mx_list = []
    except (dns.resolver.NoNameservers, dns.exception.Timeout) as e:
        return True, False, False, [], "Unknown", f"DNS query timed out for domain: {str(e)}"
    except Exception as e:
        return True, False, False, [], "Unknown", f"DNS lookup error: {str(e)}"

    if is_null_mx:
        return True, False, True, mx_list, "None", "RFC 7505 Null MX record published: domain explicitly declares it rejects all email"

    mx_list.sort(key=lambda x: x["priority"])

    # 2. RFC 5321 Fallback to A / AAAA record if no MX is published
    if not mx_list:
        try:
            a_answers = resolver.resolve(clean_domain, "A")
            if a_answers:
                mx_list.append({"priority": 0, "host": clean_domain, "is_fallback_a": True})
        except Exception:
            pass

    if not mx_list:
        return True, False, False, [], "None", "Domain exists but publishes no MX or A records to receive email"

    # Detect Provider
    hosts_lower = " ".join([m["host"].lower() for m in mx_list])
    if "google.com" in hosts_lower or "googlemail.com" in hosts_lower:
        provider = "Google Workspace"
    elif "outlook.com" in hosts_lower or "microsoft" in hosts_lower:
        provider = "Microsoft 365"
    elif "titan.email" in hosts_lower:
        provider = "Titan Mail"
    elif "zoho" in hosts_lower:
        provider = "Zoho Mail"
    elif "protonmail" in hosts_lower:
        provider = "ProtonMail"
    elif "secureserver.net" in hosts_lower:
        provider = "GoDaddy"
    else:
        provider = "Custom / Private Mail Server"

    return True, True, False, mx_list, provider, ""


async def respectful_smtp_probe(
    mx_host: str,
    target_email: str,
    helo_domain: str = "mail.weblinxsolution.com",
    probe_sender: str = "verify-probe@weblinxsolution.com",
    timeout: float = 4.0,
) -> Dict[str, Any]:
    """Perform a controlled, respectful SMTP handshake to evaluate recipient acceptance.
    
    Adheres strictly to remote server protections:
    - Never flood or retry aggressively
    - Sends clean QUIT
    - Interprets 4xx (greylisting/rate-limit) safely as unknown
    - Checks port 25 reachability gracefully (fails safely to unconfirmed)
    """
    result: Dict[str, Any] = {
        "attempted": True,
        "mx_host": mx_host,
        "connected": False,
        "smtp_code": None,
        "smtp_message": "",
        "catch_all_detected": None,
        "port_25_blocked": False,
        "error": None,
    }

    try:
        # Establish connection with strict timeout
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25),
            timeout=timeout,
        )
        result["connected"] = True
    except (asyncio.TimeoutError, ConnectionRefusedError, socket.error, OSError) as e:
        logger.info(f"SMTP connection to {mx_host}:25 unreachable or timed out: {e}")
        result["port_25_blocked"] = True
        result["error"] = f"Port 25 unreachable or timed out: {str(e)}"
        return result
    except Exception as e:
        result["error"] = str(e)
        return result

    async def _read_reply() -> Tuple[int, str]:
        line = await reader.readline()
        text = line.decode("utf-8", errors="replace").strip()
        code = int(text[:3]) if len(text) >= 3 and text[:3].isdigit() else 0
        return code, text

    async def _send_cmd(cmd: str) -> Tuple[int, str]:
        writer.write(f"{cmd}\r\n".encode("utf-8"))
        await writer.drain()
        return await _read_reply()

    try:
        # 1. Read greeting banner
        banner_code, banner_msg = await asyncio.wait_for(_read_reply(), timeout=timeout)
        if banner_code != 220:
            result["smtp_code"] = banner_code
            result["smtp_message"] = banner_msg
            return result

        # 2. Send EHLO
        ehlo_code, ehlo_msg = await asyncio.wait_for(_send_cmd(f"EHLO {helo_domain}"), timeout=timeout)
        if ehlo_code not in (250, 220):
            # Fallback to HELO
            await _send_cmd(f"HELO {helo_domain}")

        # 3. Send MAIL FROM
        mail_code, mail_msg = await asyncio.wait_for(_send_cmd(f"MAIL FROM:<{probe_sender}>"), timeout=timeout)
        if mail_code != 250:
            result["smtp_code"] = mail_code
            result["smtp_message"] = f"MAIL FROM rejected: {mail_msg}"
            return result

        # 4. Send RCPT TO for the real target address
        rcpt_code, rcpt_msg = await asyncio.wait_for(_send_cmd(f"RCPT TO:<{target_email}>"), timeout=timeout)
        result["smtp_code"] = rcpt_code
        result["smtp_message"] = rcpt_msg

        # 5. Catch-All probe if target was accepted
        if rcpt_code == 250:
            domain = target_email.split("@")[-1]
            synthetic_unlikely_box = f"random_check_probe_991823719@{domain}"
            rnd_code, _ = await asyncio.wait_for(_send_cmd(f"RCPT TO:<{synthetic_unlikely_box}>"), timeout=timeout)
            if rnd_code == 250:
                result["catch_all_detected"] = True
            elif rnd_code in (550, 551, 552, 553, 554):
                result["catch_all_detected"] = False

        # 6. Politely close connection
        try:
            await _send_cmd("QUIT")
        except Exception:
            pass

    except Exception as e:
        result["error"] = f"SMTP exchange error: {str(e)}"
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    return result


async def verify_single_email(
    email: str,
    website: Optional[str] = None,
    check_smtp: bool = False,
    dns_timeout: float = 3.5,
) -> VerificationResult:
    """Run the complete self-hosted verification pipeline for a single email address."""
    # ── Stage 1: Syntax & RFC Normalization ───────────────────────────────────
    is_valid_syntax, norm_email, local_part, domain, syntax_err = validate_syntax_and_normalize(email)

    def _finalize(res: VerificationResult) -> VerificationResult:
        if website and domain:
            res.domain_mismatch = check_website_domain_mismatch(domain, website, res.status, local_part)
        return res

    syntax_details = {
        "valid": is_valid_syntax,
        "normalized_email": norm_email,
        "local_part": local_part,
        "domain": domain,
        "error": syntax_err if not is_valid_syntax else None,
    }

    if not is_valid_syntax:
        return _finalize(VerificationResult(
            email=email,
            status=STATUS_INVALID,
            summary_reason=f"Invalid email syntax: {syntax_err}",
            confidence="high",
            confidence_limitations="RFC 5322 syntax failure is definitive.",
            syntax_details=syntax_details,
        ))

    # ── Stage 2: Common Domain Typo Detection ─────────────────────────────────
    suggested_domain = check_typo_suggestion(domain)
    typo_details = {
        "has_typo_suggestion": bool(suggested_domain),
        "has_typo_risk": bool(suggested_domain),
        "suggested_domain": suggested_domain,
        "suggestion": suggested_domain,
        "suggested_email": f"{local_part}@{suggested_domain}" if suggested_domain else None,
    }

    if suggested_domain:
        return _finalize(VerificationResult(
            email=norm_email,
            status=STATUS_RISKY,
            summary_reason=f"Suspected domain typo in '@{domain}': did you mean '@{suggested_domain}'?",
            confidence="high",
            confidence_limitations="Domain matches common mistyped variant of a major provider.",
            syntax_details=syntax_details,
            typo_details=typo_details,
        ))

    # ── Stage 3: Disposable Domain Detection ──────────────────────────────────
    is_disposable = is_disposable_domain(domain)
    disposable_details = {
        "is_disposable": is_disposable,
        "domain_checked": domain,
    }

    if is_disposable:
        return _finalize(VerificationResult(
            email=norm_email,
            status=STATUS_INVALID,
            summary_reason=f"Disposable / throwaway email provider detected ({domain})",
            confidence="high",
            confidence_limitations="Domain matched verified offline disposable database (97k+ domains).",
            syntax_details=syntax_details,
            disposable_details=disposable_details,
            typo_details=typo_details,
        ))

    # ── Stage 4: Role-Based Account Detection ─────────────────────────────────
    # Stored separately from deliverability status per instructions!
    is_role, role_category = check_role_account(local_part)
    role_details = {
        "is_role_account": is_role,
        "category": role_category,
        "role_category": role_category,
        "local_part": local_part,
    }

    # ── Stage 5: DNS Existence & MX / Null MX Evaluation ───────────────────────
    domain_exists, has_mx, is_null_mx, mx_records, provider, dns_err = check_domain_dns_and_mx(
        domain, timeout=dns_timeout
    )

    domain_details = {
        "domain": domain,
        "domain_exists": domain_exists,
        "has_mx": has_mx,
        "is_null_mx": is_null_mx,
        "mx_records": mx_records,
        "detected_provider": provider,
        "error": dns_err if dns_err else None,
    }

    if not domain_exists:
        return _finalize(VerificationResult(
            email=norm_email,
            status=STATUS_INVALID,
            summary_reason=f"Domain '{domain}' does not exist (NXDOMAIN)",
            confidence="high",
            confidence_limitations="DNS root/authoritative lookups confirmed domain is non-existent.",
            syntax_details=syntax_details,
            domain_details=domain_details,
            disposable_details=disposable_details,
            role_details=role_details,
            typo_details=typo_details,
        ))

    if is_null_mx:
        return _finalize(VerificationResult(
            email=norm_email,
            status=STATUS_INVALID,
            summary_reason="Domain published RFC 7505 Null MX (explicitly rejects all incoming mail)",
            confidence="high",
            confidence_limitations="Null MX is an authoritative standard declaration by domain owner.",
            syntax_details=syntax_details,
            domain_details=domain_details,
            disposable_details=disposable_details,
            role_details=role_details,
            typo_details=typo_details,
        ))

    if not has_mx:
        return _finalize(VerificationResult(
            email=norm_email,
            status=STATUS_INVALID,
            summary_reason=f"Domain '{domain}' has no valid mail exchange (MX) or A records configured",
            confidence="high",
            confidence_limitations="No mail server found to accept email.",
            syntax_details=syntax_details,
            domain_details=domain_details,
            disposable_details=disposable_details,
            role_details=role_details,
            typo_details=typo_details,
        ))

    # If typo was suspected, mark status as risky so sender can inspect
    if suggested_domain:
        return _finalize(VerificationResult(
            email=norm_email,
            status=STATUS_RISKY,
            summary_reason=f"Suspected domain typo: did you mean @{suggested_domain}?",
            confidence="medium",
            confidence_limitations="Domain exists in DNS, but resembles a common typo of a major provider.",
            syntax_details=syntax_details,
            domain_details=domain_details,
            disposable_details=disposable_details,
            role_details=role_details,
            typo_details=typo_details,
        ))

    # ── Stage 6: Optional SMTP Recipient & Catch-All Probe ────────────────────
    smtp_details: Dict[str, Any] = {"attempted": False}

    if check_smtp and mx_records:
        primary_mx = mx_records[0]["host"]
        smtp_details = await respectful_smtp_probe(primary_mx, norm_email)

        if smtp_details.get("port_25_blocked"):
            # Port 25 unreachable on host / firewall: do NOT classify as invalid!
            return _finalize(VerificationResult(
                email=norm_email,
                status=STATUS_DOMAIN_VALIDATED,
                summary_reason="Domain & MX verified active; mailbox unconfirmed (outbound port 25 blocked or filtered)",
                confidence="medium",
                confidence_limitations="Port 25 was filtered by the network; domain is verified ready to receive mail.",
                syntax_details=syntax_details,
                domain_details=domain_details,
                disposable_details=disposable_details,
                role_details=role_details,
                typo_details=typo_details,
                smtp_details=smtp_details,
            ))

        code = smtp_details.get("smtp_code")
        if code:
            if code in (550, 551, 552, 553, 554):
                # Mailbox definitively rejected by remote mail exchanger
                return _finalize(VerificationResult(
                    email=norm_email,
                    status=STATUS_INVALID,
                    summary_reason=f"Mailbox rejected by remote server (SMTP {code}: {smtp_details.get('smtp_message')})",
                    confidence="high",
                    confidence_limitations="Remote MTA returned a permanent 5xx mailbox-not-found error.",
                    syntax_details=syntax_details,
                    domain_details=domain_details,
                    disposable_details=disposable_details,
                    role_details=role_details,
                    typo_details=typo_details,
                    smtp_details=smtp_details,
                ))
            elif code in (450, 451, 452):
                # Greylisting or temporary throttling
                return _finalize(VerificationResult(
                    email=norm_email,
                    status=STATUS_UNKNOWN,
                    summary_reason=f"Mail server greylisted or throttled probe (SMTP {code})",
                    confidence="low",
                    confidence_limitations="Remote server asked to retry later (standard anti-spam greylisting).",
                    syntax_details=syntax_details,
                    domain_details=domain_details,
                    disposable_details=disposable_details,
                    role_details=role_details,
                    typo_details=typo_details,
                    smtp_details=smtp_details,
                ))
            elif code == 250:
                if smtp_details.get("catch_all_detected"):
                    return _finalize(VerificationResult(
                        email=norm_email,
                        status=STATUS_CATCH_ALL,
                        summary_reason=f"Domain '{domain}' has a Catch-All policy (accepts all addresses; individual mailbox unconfirmed)",
                        confidence="medium",
                        confidence_limitations="Server accepted arbitrary recipient address; delivery to this specific mailbox cannot be guaranteed.",
                        syntax_details=syntax_details,
                        domain_details=domain_details,
                        disposable_details=disposable_details,
                        role_details=role_details,
                        typo_details=typo_details,
                        smtp_details=smtp_details,
                    ))
                else:
                    return _finalize(VerificationResult(
                        email=norm_email,
                        status=STATUS_VALID,
                        summary_reason="Mailbox recipient accepted by remote server (SMTP 250 OK)",
                        confidence="high",
                        confidence_limitations="Server accepted RCPT TO command; actual delivery still subject to recipient anti-spam filtering.",
                        syntax_details=syntax_details,
                        domain_details=domain_details,
                        disposable_details=disposable_details,
                        role_details=role_details,
                        typo_details=typo_details,
                        smtp_details=smtp_details,
                    ))

    # ── Default Honest Classification (User Rule #1) ─────────────────────────
    # If mailbox probe is not performed or unconfirmed, DO NOT mark as "Valid"!
    # Use "domain_validated" with clear explanation.
    role_note = f" (Role account: {role_category})" if is_role else ""
    return _finalize(VerificationResult(
        email=norm_email,
        status=STATUS_DOMAIN_VALIDATED,
        summary_reason=f"Domain & MX active ({provider}); mailbox existence unconfirmed (no SMTP check performed){role_note}",
        confidence="medium",
        confidence_limitations="Syntax, domain existence, and MX records are verified. Mailbox-level existence has not been tested with SMTP.",
        syntax_details=syntax_details,
        domain_details=domain_details,
        disposable_details=disposable_details,
        role_details=role_details,
        typo_details=typo_details,
        smtp_details=smtp_details,
    ))
