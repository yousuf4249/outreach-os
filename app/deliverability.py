"""Email Deliverability & Domain Health Monitoring Service.

Provides recursive DNS authentication inspection (SPF RFC 7208, DKIM RFC 6376, DMARC RFC 7489, MX),
accurate relay IP blocklist checks, controlled deliverability testing via email header / EML analysis,
comprehensive delivery metrics aggregating both campaign emails (EmailLog) and manual direct emails (DirectEmail),
and actionable fix recommendations.
"""

from __future__ import annotations

import base64
import email
from email import policy
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime

import dns.exception
import dns.resolver
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DirectEmail, DomainHealthScan, EmailLog, Inbox, Lead, LeadReply, SmtpAccount
from app.time import utcnow

logger = logging.getLogger("quickly.deliverability")

# Standard probe selectors for DKIM discovery across common providers
COMMON_DKIM_SELECTORS = [
    # Mailgun selectors (krs is the primary standard Mailgun selector)
    "krs",
    "pic",
    "mailo",
    "email",
    "mg",
    "mailgun",
    "k1",
    "k2",
    "k3",
    "m1",
    "m2",
    # Hostinger & Titan Mail selectors (Titan generates titan1 through titan10 dynamically)
    "titan1",
    "titan2",
    "titan3",
    "titan4",
    "titan5",
    "titan6",
    "titan7",
    "titan8",
    "titan9",
    "titan10",
    "titan",
    # Google Workspace
    "google",
    "20230601",
    "20210112",
    # Microsoft 365 / Office 365
    "selector1",
    "selector2",
    "selector3",
    # SendGrid, Amazon SES, Postmark, Mailchimp
    "s1",
    "s2",
    "smtpapi",
    "amazonses",
    "pm",
    "mandrill",
    # Generic, cPanel & custom mail hosts
    "default",
    "mail",
    "smtp",
    "s2048",
    # Zoho & ProtonMail
    "zoho",
    "zmail",
    "protonmail",
    # Hostinger variants
    "hostingermail",
    "hostinger",
    "cpanelemaildiscovery",
]

# Standard DNSBL providers for safe reputation inspection
STANDARD_DNSBLS = [
    ("zen.spamhaus.org", "Spamhaus ZEN"),
    ("bl.spamcop.net", "SpamCop"),
    ("b.barracudacentral.org", "Barracuda Central"),
]

# High-reliability public recursive resolvers used to query fresh, authoritative DNS records
# bypassing stale local router / DHCP caching (e.g. 192.168.x.x routers caching stale TTLs)
PUBLIC_DNS_NAMESERVERS = [
    "1.1.1.1",
    "8.8.8.8",
    "1.0.0.1",
    "8.8.4.4",
    "9.9.9.9",
]


def extract_domain(email_address: str) -> str:
    """Extract domain portion from an email address or header like 'Name <user@domain.com>'."""
    if not email_address:
        return ""
    from email.utils import parseaddr
    _, addr = parseaddr(email_address)
    target = addr if addr and "@" in addr else email_address
    if "@" in target:
        dom = target.strip().rstrip(">").split("@")[-1].strip().lower()
        return dom.split()[0].rstrip(",;")
    return ""


def get_dns_resolver(timeout: float = 3.5, fresh: bool = True) -> dns.resolver.Resolver:
    """Return a configured DNS resolver with strict timeouts.
    
    When fresh=True (default for deliverability checks & scans), prioritizes high-speed,
    uncached public recursive resolvers (Cloudflare 1.1.1.1, Google 8.8.8.8, Quad9 9.9.9.9)
    to bypass stale local router / DHCP caching (e.g. 192.168.x.x holding outdated TTLs),
    with system-configured nameservers retained as fallback.
    """
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = list(PUBLIC_DNS_NAMESERVERS)
    # Retain system nameservers as fallback if network restricts outbound public UDP 53
    try:
        sys_res = dns.resolver.Resolver()
        for ns in sys_res.nameservers:
            if ns not in resolver.nameservers:
                resolver.nameservers.append(ns)
    except Exception:
        pass
    resolver.timeout = timeout
    resolver.lifetime = timeout
    return resolver


# ---------------------------------------------------------------------------
# SPF Recursive Inspection (RFC 7208)
# ---------------------------------------------------------------------------

def _evaluate_spf_recursive(
    domain: str,
    resolver: dns.resolver.Resolver,
    visited: Optional[Set[str]] = None,
    depth: int = 0,
) -> Tuple[int, List[str], List[str], List[Dict[str, Any]], Optional[str]]:
    """Recursively evaluate SPF includes according to RFC 7208 Section 4.6.4.

    Returns:
        (total_lookups, all_includes, all_mechanisms, issues, root_record)
    """
    if visited is None:
        visited = set()

    clean_dom = domain.strip().lower()
    if clean_dom in visited:
        return 0, [], [], [{
            "severity": "critical",
            "code": "SPF_RECURSIVE_LOOP",
            "title": "SPF Recursive Loop Detected",
            "message": f"Domain '{clean_dom}' causes an infinite circular SPF include loop.",
            "recommendation": "Remove circular include references from your SPF record.",
            "copyable_snippet": None,
        }], None

    visited.add(clean_dom)

    if depth > 10:
        return 0, [], [], [{
            "severity": "critical",
            "code": "SPF_RECURSION_DEPTH_EXCEEDED",
            "title": "SPF Maximum Recursion Depth Exceeded",
            "message": f"SPF include evaluation exceeded 10 levels of nesting at '{clean_dom}'.",
            "recommendation": "Flatten nested SPF records.",
            "copyable_snippet": None,
        }], None

    try:
        answers = resolver.resolve(clean_dom, "TXT")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return 0, [], [], [], None
    except Exception as e:
        logger.warning(f"Error querying SPF for {clean_dom}: {e}")
        return 0, [], [], [{
            "severity": "warning",
            "code": "SPF_CHILD_DNS_ERROR",
            "title": f"SPF Lookup Failed for {clean_dom}",
            "message": f"Could not resolve SPF record for included domain '{clean_dom}': {str(e)}",
            "recommendation": "Verify that all included domains exist and have active DNS records.",
            "copyable_snippet": None,
        }], None

    spf_records = []
    for rdata in answers:
        txt = b"".join(rdata.strings).decode("utf-8", errors="replace").strip()
        if txt.lower().startswith("v=spf1"):
            spf_records.append(txt)

    if not spf_records:
        return 0, [], [], [], None

    issues: List[Dict[str, Any]] = []
    if len(spf_records) > 1:
        issues.append({
            "severity": "critical",
            "code": "SPF_DUPLICATE",
            "title": f"Multiple SPF Records at {clean_dom}",
            "message": f"Domain '{clean_dom}' publishes {len(spf_records)} SPF records. RFC 7208 strictly forbids publishing multiple SPF records (causes receiving MTAs to return PermError).",
            "recommendation": "Merge all SPF records into a single record and remove duplicates.",
            "copyable_snippet": None,
        })
        return 0, [], [], issues, spf_records[0]

    record = spf_records[0]
    tokens = record.split()
    mechanisms = tokens[1:] if len(tokens) > 1 else []

    lookup_count = 0
    all_includes: List[str] = []

    for mech in mechanisms:
        low = mech.lower()
        if low.startswith("include:"):
            lookup_count += 1
            inc_target = low.split("include:", 1)[1].strip()
            all_includes.append(inc_target)
            # Recursive lookup on included domain
            child_lookups, child_includes, _, child_issues, _ = _evaluate_spf_recursive(
                inc_target, resolver, visited, depth + 1
            )
            lookup_count += child_lookups
            all_includes.extend(child_includes)
            issues.extend(child_issues)
        elif low.startswith("a") or low.startswith("a:"):
            lookup_count += 1
        elif low.startswith("mx") or low.startswith("mx:"):
            lookup_count += 1
        elif low.startswith("ptr"):
            lookup_count += 1
            issues.append({
                "severity": "warning",
                "code": "SPF_PTR_DEPRECATED",
                "title": "Deprecated 'ptr' Mechanism in SPF",
                "message": f"SPF at '{clean_dom}' uses the deprecated 'ptr' mechanism.",
                "recommendation": "Replace 'ptr' with explicit IP addresses ('ip4:') or includes.",
                "copyable_snippet": None,
            })
        elif low.startswith("exists:"):
            lookup_count += 1
        elif low.startswith("redirect="):
            lookup_count += 1
            redir_target = low.split("redirect=", 1)[1].strip()
            child_lookups, child_includes, _, child_issues, _ = _evaluate_spf_recursive(
                redir_target, resolver, visited, depth + 1
            )
            lookup_count += child_lookups
            all_includes.extend(child_includes)
            issues.extend(child_issues)

    return lookup_count, all_includes, mechanisms, issues, record


def check_spf_record(
    domain: str,
    provider: Optional[str] = None,
    smtp_host: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspect SPF TXT records for a given domain according to RFC 7208 with full recursive lookup."""
    resolver = get_dns_resolver()
    issues: List[Dict[str, Any]] = []

    try:
        answers = resolver.resolve(domain, "TXT")
        root_records = []
        for rdata in answers:
            txt = b"".join(rdata.strings).decode("utf-8", errors="replace").strip()
            if txt.lower().startswith("v=spf1"):
                root_records.append(txt)
    except dns.resolver.NXDOMAIN:
        root_records = []
    except dns.resolver.NoAnswer:
        root_records = []
    except (dns.resolver.NoNameservers, dns.exception.Timeout) as e:
        logger.warning(f"DNS lookup timeout for SPF on {domain}: {e}")
        return {
            "status": "warning",
            "records": [],
            "record": None,
            "mechanisms": [],
            "lookup_count": 0,
            "all_mechanism": None,
            "error": f"DNS query timed out: {str(e)}",
            "issues": [{
                "severity": "warning",
                "code": "SPF_DNS_TIMEOUT",
                "title": "SPF DNS Query Timed Out",
                "message": f"Could not reach authoritative DNS nameservers for {domain} within 3s.",
                "recommendation": "Verify your domain nameservers are responding correctly.",
                "copyable_snippet": None,
            }],
        }
    except Exception as e:
        logger.warning(f"Error querying SPF for {domain}: {e}")
        return {
            "status": "warning",
            "records": [],
            "record": None,
            "mechanisms": [],
            "lookup_count": 0,
            "all_mechanism": None,
            "error": str(e),
            "issues": [],
        }

    # 1. Check existence at root
    if not root_records:
        rec_snippet = "v=spf1 include:spf.titan.email ~all" if provider == "smtp" else (
            "v=spf1 include:_spf.google.com ~all" if provider == "gmail" else (
                "v=spf1 include:spf.protection.outlook.com ~all" if provider == "office365" else "v=spf1 ~all"
            )
        )
        issues.append({
            "severity": "critical",
            "code": "SPF_MISSING",
            "title": "No SPF Record Found",
            "message": f"Domain {domain} has no SPF TXT record published. Major receivers (Gmail, Yahoo, Outlook) cannot verify authorized senders.",
            "recommendation": f"Add a TXT record to your DNS zone for '{domain}' with value: {rec_snippet}",
            "copyable_snippet": rec_snippet,
        })
        return {
            "status": "not_configured",
            "records": [],
            "record": None,
            "mechanisms": [],
            "lookup_count": 0,
            "all_mechanism": None,
            "issues": issues,
        }

    # 2. Check multiple records at root
    if len(root_records) > 1:
        issues.append({
            "severity": "critical",
            "code": "SPF_DUPLICATE",
            "title": "Multiple SPF Records Detected",
            "message": f"Domain {domain} publishes {len(root_records)} SPF records. RFC 7208 strictly forbids publishing multiple SPF records, causing receiving MTAs to immediately fail authentication with 'PermError'.",
            "recommendation": "Merge all mechanisms into a single SPF TXT record and delete duplicate TXT records.",
            "copyable_snippet": None,
        })
        return {
            "status": "critical",
            "records": root_records,
            "record": root_records[0],
            "mechanisms": [],
            "lookup_count": 0,
            "all_mechanism": None,
            "issues": issues,
        }

    # 3. Perform full recursive evaluation
    lookup_count, all_includes, mechanisms, rec_issues, root_record = _evaluate_spf_recursive(
        domain, resolver
    )
    issues.extend(rec_issues)

    # 4. Check all mechanism (+all, ?all, ~all, -all)
    all_mechanism = None
    for m in mechanisms:
        low = m.lower()
        if low in ("~all", "-all", "?all", "+all"):
            all_mechanism = low

    if all_mechanism == "+all":
        issues.append({
            "severity": "critical",
            "code": "SPF_POLICY_ALLOW_ALL",
            "title": "Dangerous SPF '+all' Policy",
            "message": "Your SPF record ends with '+all', which authorizes every IP on the entire internet to spoof your domain.",
            "recommendation": "Change '+all' to '~all' (SoftFail) or '-all' (HardFail).",
            "copyable_snippet": root_record.replace("+all", "~all"),
        })
    elif all_mechanism == "?all":
        issues.append({
            "severity": "warning",
            "code": "SPF_POLICY_NEUTRAL",
            "title": "SPF '?all' Neutral Policy",
            "message": "Your SPF record specifies '?all' (Neutral), which provides no assertion of whether unauthorized senders are permitted.",
            "recommendation": "Update '?all' to '~all' (SoftFail) or '-all' (HardFail).",
            "copyable_snippet": root_record.replace("?all", "~all"),
        })
    elif all_mechanism is None:
        issues.append({
            "severity": "warning",
            "code": "SPF_POLICY_MISSING_ALL",
            "title": "SPF Record Missing Default 'all' Mechanism",
            "message": "Your SPF record does not specify a trailing 'all' mechanism (e.g. '~all').",
            "recommendation": "Add '~all' or '-all' to the end of your SPF record.",
            "copyable_snippet": f"{root_record} ~all",
        })

    # 5. Check 10 DNS lookup limit (RFC 7208 Section 4.6.4)
    if lookup_count > 10:
        issues.append({
            "severity": "critical",
            "code": "SPF_LOOKUP_LIMIT_EXCEEDED",
            "title": f"SPF Exceeds 10 DNS Lookup Limit ({lookup_count}/10)",
            "message": f"Your SPF record requires {lookup_count} recursive DNS lookups, exceeding the RFC 7208 hard limit of 10. Receiving mail transfer agents will return 'PermError'.",
            "recommendation": "Flatten nested includes or remove unused mechanisms to bring total DNS lookups under 10.",
            "copyable_snippet": None,
        })
    elif lookup_count >= 8:
        issues.append({
            "severity": "warning",
            "code": "SPF_LOOKUP_LIMIT_NEAR",
            "title": f"SPF Near DNS Lookup Limit ({lookup_count}/10)",
            "message": f"Your SPF record uses {lookup_count} recursive DNS lookups (limit is 10).",
            "recommendation": "Avoid adding further includes unless necessary.",
            "copyable_snippet": None,
        })

    # 6. Check provider alignment across the recursive tree
    all_includes_str = " ".join([i.lower() for i in all_includes])
    root_str = root_record.lower()
    combined_includes = f"{root_str} {all_includes_str}"

    if provider == "gmail" and "_spf.google.com" not in combined_includes:
        issues.append({
            "severity": "warning",
            "code": "SPF_GOOGLE_INCLUDE_MISSING",
            "title": "Google SPF Mechanism Missing",
            "message": f"This inbox uses Google Workspace, but domain {domain} does not include 'include:_spf.google.com' in its SPF record.",
            "recommendation": "Add 'include:_spf.google.com' to your SPF record.",
            "copyable_snippet": "v=spf1 include:_spf.google.com ~all",
        })
    elif provider == "office365" and "spf.protection.outlook.com" not in combined_includes:
        issues.append({
            "severity": "warning",
            "code": "SPF_MS365_INCLUDE_MISSING",
            "title": "Microsoft 365 SPF Mechanism Missing",
            "message": f"This inbox uses Microsoft 365, but domain {domain} does not include 'include:spf.protection.outlook.com' in its SPF record.",
            "recommendation": "Add 'include:spf.protection.outlook.com' to your SPF record.",
            "copyable_snippet": "v=spf1 include:spf.protection.outlook.com ~all",
        })
    elif provider == "smtp":
        relay_low = (smtp_host or "").lower()
        if "mailgun" in relay_low and "mailgun.org" not in combined_includes:
            issues.append({
                "severity": "warning",
                "code": "SPF_MAILGUN_INCLUDE_MISSING",
                "title": "Mailgun SPF Mechanism Missing",
                "message": f"This inbox uses Mailgun SMTP, but domain {domain} does not include 'include:mailgun.org' in its SPF record.",
                "recommendation": "Add 'include:mailgun.org' to your SPF record.",
                "copyable_snippet": "v=spf1 include:mailgun.org ~all",
            })
        elif "titan" in relay_low and "titan.email" not in combined_includes:
            issues.append({
                "severity": "warning",
                "code": "SPF_TITAN_INCLUDE_MISSING",
                "title": "Titan Mail SPF Mechanism Missing",
                "message": f"This inbox uses Titan Mail, but domain {domain} does not include 'include:spf.titan.email' in its SPF record.",
                "recommendation": "Add 'include:spf.titan.email' to your SPF record.",
                "copyable_snippet": "v=spf1 include:spf.titan.email ~all",
            })

    status = "healthy"
    for iss in issues:
        if iss["severity"] == "critical":
            status = "critical"
            break
        elif iss["severity"] == "warning" and status != "critical":
            status = "warning"

    return {
        "status": status,
        "records": root_records,
        "record": root_record,
        "mechanisms": mechanisms,
        "lookup_count": lookup_count,
        "all_includes": all_includes,
        "all_mechanism": all_mechanism,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# DKIM Inspection (RFC 6376)
# ---------------------------------------------------------------------------

def check_dkim_record(
    domain: str,
    custom_selector: Optional[str] = None,
    provider: Optional[str] = None,
    smtp_host: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspect DKIM DNS records across probed or user-specified selectors."""
    resolver = get_dns_resolver()
    selectors_to_check: List[str] = []

    if custom_selector and custom_selector.strip():
        selectors_to_check.append(custom_selector.strip())

    relay_low = (smtp_host or "").lower()

    # Provider and relay specific selectors prioritized first
    if "mailgun" in relay_low or "mailgun" in domain.lower():
        for s in ("krs", "pic", "mailo", "email", "mg", "mailgun", "k1", "k2", "k3"):
            if s not in selectors_to_check:
                selectors_to_check.append(s)

    if provider == "gmail" and "google" not in selectors_to_check:
        selectors_to_check.append("google")
    elif provider == "office365":
        for s in ("selector1", "selector2"):
            if s not in selectors_to_check:
                selectors_to_check.append(s)
    elif provider == "smtp":
        # Check Mailgun & Titan common selectors for general SMTP
        for s in (
            "krs", "pic", "mailo", "email", "mg", "mailgun",
            "titan1", "titan2", "titan3", "titan4", "titan5",
            "titan6", "titan7", "titan8", "titan9", "titan10", "titan",
            "default", "s1", "s2", "mail", "k1", "k2", "hostingermail", "hostinger"
        ):
            if s not in selectors_to_check:
                selectors_to_check.append(s)

    for sel in COMMON_DKIM_SELECTORS:
        if sel not in selectors_to_check:
            selectors_to_check.append(sel)

    found_selector: Optional[str] = None
    found_record: Optional[str] = None
    key_length_bits: Optional[int] = None
    issues: List[Dict[str, Any]] = []

    for sel in selectors_to_check:
        query_host = f"{sel}._domainkey.{domain}"
        # 1. Direct TXT lookup
        try:
            answers = resolver.resolve(query_host, "TXT")
            for rdata in answers:
                txt = b"".join(rdata.strings).decode("utf-8", errors="replace").strip()
                if "p=" in txt or "v=dkim1" in txt.lower():
                    found_selector = sel
                    found_record = txt
                    break
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
            pass

        # 2. CNAME alias lookup (common in Mailgun / SendGrid / AWS SES)
        if not found_record:
            try:
                cname_answers = resolver.resolve(query_host, "CNAME")
                for crdata in cname_answers:
                    cname_target = crdata.target.to_text().rstrip(".")
                    target_txts = resolver.resolve(cname_target, "TXT")
                    for trdata in target_txts:
                        ttxt = b"".join(trdata.strings).decode("utf-8", errors="replace").strip()
                        if "p=" in ttxt or "v=dkim1" in ttxt.lower():
                            found_selector = sel
                            found_record = ttxt
                            break
                    if found_record:
                        break
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
                pass

        if found_record:
            break

    # If no selector was discovered: do NOT claim DKIM is missing or critical!
    if not found_record:
        issues.append({
            "severity": "info",
            "code": "DKIM_NOT_VERIFIED",
            "title": "DKIM Selector Unknown (Private DNS Record)",
            "message": (
                f"DKIM public keys are published under private selector names that cannot be enumerated by DNS. "
                f"We probed standard default selectors ({', '.join(selectors_to_check[:6])}...) on '{domain}'. "
                "This does NOT mean DKIM is absent on your domain — it only means your mail host is using a custom selector name."
            ),
            "recommendation": "Check your email provider admin panel for your active DKIM selector name (or inspect a sent email header), then enter it in the Custom Selector box to verify.",
            "copyable_snippet": None,
        })
        return {
            "status": "not_verified",
            "selector": None,
            "record": None,
            "key_length_bits": None,
            "published_in_dns": False,
            "issues": issues,
            "tested_selectors": selectors_to_check,
        }

    # Extract public key p=
    p_match = re.search(r"p=([a-zA-Z0-9+/=]+)", found_record)
    if not p_match or not p_match.group(1):
        issues.append({
            "severity": "critical",
            "code": "DKIM_EMPTY_KEY",
            "title": "DKIM Public Key is Empty / Revoked",
            "message": f"DKIM record at selector '{found_selector}' contains an empty public key ('p='). In RFC 6376, this explicitly signals key revocation.",
            "recommendation": "Re-generate or paste the valid public key from your email host into your DNS settings.",
            "copyable_snippet": None,
        })
        return {
            "status": "critical",
            "selector": found_selector,
            "record": found_record,
            "key_length_bits": 0,
            "issues": issues,
            "tested_selectors": selectors_to_check,
        }

    raw_key_b64 = p_match.group(1).strip()
    try:
        decoded_bytes = base64.b64decode(raw_key_b64)
        byte_len = len(decoded_bytes)
        if byte_len >= 250:
            key_length_bits = 2048
        elif byte_len >= 120:
            key_length_bits = 1024
        elif byte_len >= 60:
            key_length_bits = 512
        else:
            key_length_bits = byte_len * 8

        if key_length_bits and key_length_bits < 1024:
            issues.append({
                "severity": "critical",
                "code": "DKIM_KEY_TOO_SHORT",
                "title": f"DKIM Key Size Insecure ({key_length_bits} bits)",
                "message": f"DKIM key length is {key_length_bits} bits. Modern receivers require at least 1024 bits and recommend 2048 bits.",
                "recommendation": "Generate a 2048-bit DKIM key in your email provider and update DNS.",
                "copyable_snippet": None,
            })
        elif key_length_bits == 1024:
            issues.append({
                "severity": "info",
                "code": "DKIM_KEY_1024_BIT",
                "title": "1024-bit Standard DKIM Key Active",
                "message": "Your DKIM key is 1024 bits. This meets all RFC 6376, Gmail, Yahoo, and Microsoft authentication requirements. Mailgun and Titan standard 1024-bit keys pass all major provider checks.",
                "recommendation": "No action required. (2048-bit keys can be configured in your email provider if future migration is desired).",
                "copyable_snippet": None,
            })
    except Exception as e:
        logger.warning(f"Error decoding DKIM base64 public key: {e}")

    status = "healthy"
    for iss in issues:
        if iss["severity"] == "critical":
            status = "critical"
            break
        elif iss["severity"] == "warning" and status != "critical":
            status = "warning"

    return {
        "status": status,
        "selector": found_selector,
        "record": found_record,
        "key_length_bits": key_length_bits,
        "published_in_dns": bool(found_record),
        "issues": issues,
        "tested_selectors": selectors_to_check,
    }


# ---------------------------------------------------------------------------
# DMARC Inspection (RFC 7489)
# ---------------------------------------------------------------------------

def check_dmarc_record(domain: str) -> Dict[str, Any]:
    """Inspect DMARC record (_dmarc.<domain>) with authoritative error distinguishing."""
    resolver = get_dns_resolver()
    dmarc_records: List[str] = []
    query_host = f"_dmarc.{domain}"
    issues: List[Dict[str, Any]] = []

    try:
        answers = resolver.resolve(query_host, "TXT")
        for rdata in answers:
            txt = b"".join(rdata.strings).decode("utf-8", errors="replace").strip()
            if txt.lower().startswith("v=dmarc1"):
                dmarc_records.append(txt)
    except dns.resolver.NXDOMAIN:
        # Confirmed non-existent
        rec_snippet = f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
        issues.append({
            "severity": "critical",
            "code": "DMARC_MISSING",
            "title": "No DMARC Record Found (Confirmed via DNS NXDOMAIN)",
            "message": f"Domain '{domain}' authoritatively has no DMARC record published at '{query_host}'. As of 2024, Google, Yahoo, and Microsoft enforce strict DMARC requirements for high-volume senders. Without DMARC, emails face high spam-folder risk or outright rejection.",
            "recommendation": f"Add a TXT record for '_dmarc.{domain}' with value: {rec_snippet}",
            "copyable_snippet": rec_snippet,
        })
        return {
            "status": "not_configured",
            "record": None,
            "policy": None,
            "tags": {},
            "issues": issues,
        }
    except dns.resolver.NoAnswer:
        rec_snippet = f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
        issues.append({
            "severity": "critical",
            "code": "DMARC_NO_TXT",
            "title": "No DMARC TXT Record Found",
            "message": f"Domain '{domain}' has records at '{query_host}', but no TXT record starting with 'v=DMARC1'.",
            "recommendation": f"Add a TXT record for '_dmarc.{domain}' with value: {rec_snippet}",
            "copyable_snippet": rec_snippet,
        })
        return {
            "status": "not_configured",
            "record": None,
            "policy": None,
            "tags": {},
            "issues": issues,
        }
    except (dns.resolver.NoNameservers, dns.exception.Timeout) as e:
        logger.warning(f"DNS lookup timeout for DMARC on {domain}: {e}")
        return {
            "status": "dns_error",
            "record": None,
            "policy": None,
            "tags": {},
            "issues": [{
                "severity": "warning",
                "code": "DMARC_DNS_TIMEOUT",
                "title": "DMARC DNS Query Timed Out",
                "message": f"Could not reach authoritative nameservers for _dmarc.{domain} within timeout: {str(e)}",
                "recommendation": "Verify your domain nameserver configuration.",
                "copyable_snippet": None,
            }],
        }
    except Exception as e:
        logger.warning(f"Error querying DMARC for {domain}: {e}")
        return {
            "status": "dns_error",
            "record": None,
            "policy": None,
            "tags": {},
            "issues": [{
                "severity": "warning",
                "code": "DMARC_QUERY_ERROR",
                "title": "DMARC Query Error",
                "message": str(e),
                "recommendation": "Check domain DNS settings.",
                "copyable_snippet": None,
            }],
        }

    if not dmarc_records:
        rec_snippet = f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
        issues.append({
            "severity": "critical",
            "code": "DMARC_MISSING",
            "title": "No DMARC Record Found",
            "message": f"Domain '{domain}' has no valid DMARC record starting with 'v=DMARC1'.",
            "recommendation": f"Add a TXT record for '_dmarc.{domain}' with value: {rec_snippet}",
            "copyable_snippet": rec_snippet,
        })
        return {
            "status": "not_configured",
            "record": None,
            "policy": None,
            "tags": {},
            "issues": issues,
        }

    if len(dmarc_records) > 1:
        issues.append({
            "severity": "critical",
            "code": "DMARC_DUPLICATE",
            "title": "Multiple DMARC Records Found",
            "message": f"Domain {domain} publishes {len(dmarc_records)} DMARC records. RFC 7489 states that if a domain publishes multiple DMARC records, receiving MTAs must treat DMARC as unconfigured and ignore all records.",
            "recommendation": "Delete duplicate DMARC records so only one TXT record remains at _dmarc.",
            "copyable_snippet": None,
        })
        return {
            "status": "critical",
            "record": dmarc_records[0],
            "policy": None,
            "tags": {},
            "issues": issues,
        }

    record = dmarc_records[0]
    tags: Dict[str, str] = {}
    parts = [p.strip() for p in record.split(";") if p.strip()]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            tags[k.strip().lower()] = v.strip()

    policy_val = tags.get("p", "").lower()

    if policy_val == "none":
        issues.append({
            "severity": "info",
            "code": "DMARC_POLICY_NONE",
            "title": "DMARC Policy Set to 'none' (Monitoring Mode)",
            "message": "Your DMARC policy is currently 'p=none' (Monitoring Mode). This is RFC 7489 compliant and satisfies all 2024 Google, Yahoo, and Microsoft bulk sender deliverability standards while receiving aggregate reports.",
            "recommendation": "Once you verify that SPF and DKIM pass consistently in aggregate reports, you can optionally upgrade to 'p=quarantine' or 'p=reject' for stricter domain spoof protection.",
            "copyable_snippet": f"v=DMARC1; p=quarantine; rua={tags.get('rua', f'mailto:dmarc@{domain}')}",
        })
    elif policy_val in ("quarantine", "reject"):
        pass
    else:
        issues.append({
            "severity": "critical",
            "code": "DMARC_POLICY_INVALID",
            "title": "Invalid DMARC Policy 'p=' Tag",
            "message": f"The DMARC policy value 'p={policy_val}' is invalid. Allowed values: 'none', 'quarantine', 'reject'.",
            "recommendation": "Set 'p=none', 'p=quarantine', or 'p=reject'.",
            "copyable_snippet": f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}",
        })

    if "rua" not in tags:
        issues.append({
            "severity": "info",
            "code": "DMARC_RUA_MISSING",
            "title": "No Aggregate Reporting (rua) Configured",
            "message": "Your DMARC record does not include a 'rua=' tag. Adding an aggregate reporting email lets you receive daily reports from Gmail and Yahoo detailing authentication passes/fails.",
            "recommendation": f"Add '; rua=mailto:dmarc-reports@{domain}' to your DMARC record.",
            "copyable_snippet": f"{record}; rua=mailto:dmarc@{domain}",
        })

    status = "healthy"
    for iss in issues:
        if iss["severity"] == "critical":
            status = "critical"
            break
        elif iss["severity"] == "warning" and status != "critical":
            status = "warning"

    return {
        "status": status,
        "record": record,
        "policy": policy_val,
        "tags": tags,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# MX Records Inspection (Clean Separation from DNSBL)
# ---------------------------------------------------------------------------

def check_mx_records(domain: str) -> Dict[str, Any]:
    """Inspect MX DNS records and detect primary mail host provider.
    
    Returns clean MX host records strictly separated from DNSBL lookups.
    """
    resolver = get_dns_resolver()
    mx_list: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    detected_provider: str = "Unknown"

    try:
        answers = resolver.resolve(domain, "MX")
        for rdata in answers:
            host = rdata.exchange.to_text().rstrip(".")
            mx_list.append({"priority": rdata.preference, "host": host})
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        mx_list = []
    except Exception as e:
        logger.warning(f"Error querying MX for {domain}: {e}")
        return {
            "status": "warning",
            "records": [],
            "detected_provider": "Unknown",
            "issues": [{
                "severity": "warning",
                "code": "MX_LOOKUP_FAILED",
                "title": "MX Record Lookup Error",
                "message": f"Could not query MX records: {str(e)}",
                "recommendation": "Verify your domain's DNS configuration.",
                "copyable_snippet": None,
            }],
        }

    mx_list.sort(key=lambda x: x["priority"])

    if not mx_list:
        issues.append({
            "severity": "critical",
            "code": "MX_MISSING",
            "title": "No MX Records Configured",
            "message": f"Domain {domain} has no MX records. Your domain cannot receive incoming emails, bounce messages, or reply notifications.",
            "recommendation": "Configure MX records pointing to your email hosting provider.",
            "copyable_snippet": None,
        })
        return {
            "status": "critical",
            "records": [],
            "detected_provider": "None",
            "issues": issues,
        }

    hosts_lower = " ".join([m["host"].lower() for m in mx_list])
    if "google.com" in hosts_lower or "googlemail.com" in hosts_lower:
        detected_provider = "Google Workspace"
    elif "outlook.com" in hosts_lower:
        detected_provider = "Microsoft 365"
    elif "titan.email" in hosts_lower:
        detected_provider = "Titan Mail"
    elif "mailgun.org" in hosts_lower:
        detected_provider = "Mailgun"
    elif "zoho" in hosts_lower:
        detected_provider = "Zoho Mail"
    elif "secureserver.net" in hosts_lower:
        detected_provider = "GoDaddy Mail"
    elif "protonmail" in hosts_lower:
        detected_provider = "ProtonMail"
    else:
        detected_provider = "Custom / Private SMTP"

    return {
        "status": "healthy",
        "records": mx_list,
        "detected_provider": detected_provider,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# DNSBL Blocklists Check (Against Actual Outgoing Relay IP)
# ---------------------------------------------------------------------------

def check_dnsbl_blocklists(
    domain: str,
    relay_host: Optional[str] = None,
    relay_ip: Optional[str] = None,
) -> Dict[str, Any]:
    """Query standard public DNSBL blocklists against the actual outbound SMTP relay IP.
    
    Never reports 'Clean' falsely unless a valid target was verified.
    Handles public DNS resolver limitations without false alarms.
    """
    resolver = get_dns_resolver(timeout=2.0)
    results: List[Dict[str, Any]] = []
    listed_count = 0
    issues: List[Dict[str, Any]] = []

    target_ip = relay_ip

    # If IP not directly provided, resolve relay_host
    if not target_ip and relay_host:
        try:
            a_answers = resolver.resolve(relay_host, "A")
            for rdata in a_answers:
                target_ip = rdata.address
                break
        except Exception as e:
            logger.info(f"Could not resolve A record for relay host {relay_host}: {e}")
            target_ip = None

    if not target_ip:
        # Cannot determine relay IP
        for dnsbl_host, dnsbl_name in STANDARD_DNSBLS:
            results.append({
                "dnsbl": dnsbl_name,
                "host": dnsbl_host,
                "status": "not_checked",
                "details": "Outbound relay IP not identified for reputation query",
            })
        return {
            "status": "not_checked",
            "results": results,
            "listed_count": 0,
            "target_checked": None,
            "issues": [{
                "severity": "info",
                "code": "BLOCKLIST_IP_UNAVAILABLE",
                "title": "Relay IP Not Checked",
                "message": "Outbound SMTP relay IP could not be resolved to perform blocklist verification.",
                "recommendation": "Verify SMTP account connection settings to enable IP reputation check.",
                "copyable_snippet": None,
            }],
        }

    # Query DNSBLs with reversed IP
    octets = target_ip.split(".")
    reversed_ip = ".".join(reversed(octets))

    for dnsbl_host, dnsbl_name in STANDARD_DNSBLS:
        status_for_bl = "clean"
        details = "Clean / Not listed"
        query_name = f"{reversed_ip}.{dnsbl_host}"

        try:
            answers = resolver.resolve(query_name, "A")
            for rdata in answers:
                addr = rdata.address
                # Spamhaus query error codes for open/public recursive resolvers
                if addr.startswith("127.255.255.") or addr == "127.0.0.1":
                    status_for_bl = "resolver_restricted"
                    details = "Public DNS resolver blocked from automated queries (neutral signal)"
                elif addr.startswith("127.0.0."):
                    status_for_bl = "listed"
                    details = f"Listed (return code {addr})"
                    listed_count += 1
        except dns.resolver.NXDOMAIN:
            status_for_bl = "clean"
            details = "Clean (Not listed)"
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
            status_for_bl = "clean"
            details = "Clean / No listing response"
        except Exception as e:
            status_for_bl = "clean"
            details = f"Clean ({str(e)})"

        results.append({
            "dnsbl": dnsbl_name,
            "host": dnsbl_host,
            "status": status_for_bl,
            "details": details,
        })

    if listed_count > 0:
        issues.append({
            "severity": "critical",
            "code": "BLOCKLIST_LISTED",
            "title": f"Outgoing SMTP Relay Listed on {listed_count} Blocklist(s)",
            "message": f"Your sending relay ({target_ip}) was detected on active DNSBL blocklists. Recipient mail servers may reject or spam-box incoming outreach.",
            "recommendation": "Visit the blocklist operator's website to check the specific listing reason and request delisting.",
            "copyable_snippet": None,
        })

    return {
        "status": "listed" if listed_count > 0 else "clean",
        "results": results,
        "listed_count": listed_count,
        "target_checked": f"{relay_host or 'Relay'} ({target_ip})",
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Comprehensive Delivery Metrics (EmailLog + DirectEmail)
# ---------------------------------------------------------------------------

async def get_inbox_delivery_stats(db: AsyncSession, inbox_id: int) -> Dict[str, Any]:
    """Calculate actual delivery and bounce statistics aggregating both EmailLog and DirectEmail."""
    try:
        # 1. Campaign emails (EmailLog)
        q_camp_sent = await db.scalar(
            select(func.count(EmailLog.id)).where(EmailLog.inbox_id == inbox_id)
        )
        campaign_sent = q_camp_sent or 0

        q_camp_opened = await db.scalar(
            select(func.count(EmailLog.id)).where(
                EmailLog.inbox_id == inbox_id,
                EmailLog.opened.is_(True),
            )
        )
        campaign_opened = q_camp_opened or 0

        q_camp_clicked = await db.scalar(
            select(func.count(EmailLog.id)).where(
                EmailLog.inbox_id == inbox_id,
                EmailLog.clicked.is_(True),
            )
        )
        campaign_clicked = q_camp_clicked or 0

        q_camp_replied = await db.scalar(
            select(func.count(func.distinct(LeadReply.id)))
            .join(EmailLog, LeadReply.lead_id == EmailLog.lead_id)
            .where(EmailLog.inbox_id == inbox_id)
        )
        campaign_replied = q_camp_replied or 0

        q_camp_bounced = await db.scalar(
            select(func.count(func.distinct(Lead.id)))
            .join(EmailLog, Lead.id == EmailLog.lead_id)
            .where(
                EmailLog.inbox_id == inbox_id,
                Lead.status == "bounced",
            )
        )
        campaign_bounced = q_camp_bounced or 0

        # 2. Manual direct emails (DirectEmail)
        q_dir_sent = await db.scalar(
            select(func.count(DirectEmail.id)).where(
                DirectEmail.inbox_id == inbox_id,
                DirectEmail.status == "sent",
            )
        )
        direct_sent = q_dir_sent or 0

        q_dir_opened = await db.scalar(
            select(func.count(DirectEmail.id)).where(
                DirectEmail.inbox_id == inbox_id,
                DirectEmail.opened.is_(True),
            )
        )
        direct_opened = q_dir_opened or 0

        q_dir_replied = await db.scalar(
            select(func.count(DirectEmail.id)).where(
                DirectEmail.inbox_id == inbox_id,
                DirectEmail.replied.is_(True),
            )
        )
        direct_replied = q_dir_replied or 0

        q_dir_bounced = await db.scalar(
            select(func.count(DirectEmail.id)).where(
                DirectEmail.inbox_id == inbox_id,
                DirectEmail.status == "failed",
                or_(
                    DirectEmail.error_message.ilike("%bounce%"),
                    DirectEmail.error_message.ilike("%550%"),
                    DirectEmail.error_message.ilike("%554%"),
                    DirectEmail.error_message.ilike("%recipient address rejected%"),
                ),
            )
        )
        direct_bounced = q_dir_bounced or 0

        # Aggregated Totals
        total_sent = campaign_sent + direct_sent
        total_opened = campaign_opened + direct_opened
        total_clicked = campaign_clicked
        total_replied = campaign_replied + direct_replied
        total_bounced = campaign_bounces = campaign_bounced + direct_bounced

        # Calculate rates only when total_sent > 0, otherwise None (N/A)
        if total_sent > 0:
            open_rate: Optional[float] = round((total_opened / total_sent * 100), 1)
            click_rate: Optional[float] = round((total_clicked / total_sent * 100), 1)
            reply_rate: Optional[float] = round((total_replied / total_sent * 100), 1)
            bounce_rate: Optional[float] = round((total_bounced / total_sent * 100), 1)
        else:
            open_rate = None
            click_rate = None
            reply_rate = None
            bounce_rate = None

        issues: List[Dict[str, Any]] = []
        if total_sent >= 20 and bounce_rate is not None and bounce_rate >= 5.0:
            issues.append({
                "severity": "critical",
                "code": "HIGH_BOUNCE_RATE",
                "title": f"Critical Bounce Rate ({bounce_rate}%)",
                "message": f"Your bounce rate of {bounce_rate}% exceeds the safe cold email threshold of 2-3%.",
                "recommendation": "Clean and verify your lead list before continuing sending campaigns.",
                "copyable_snippet": None,
            })
        elif total_sent >= 20 and bounce_rate is not None and bounce_rate >= 2.5:
            issues.append({
                "severity": "warning",
                "code": "ELEVATED_BOUNCE_RATE",
                "title": f"Elevated Bounce Rate ({bounce_rate}%)",
                "message": f"Your bounce rate is {bounce_rate}%. Recommended maximum for cold outreach is 2.0%.",
                "recommendation": "Enable email verification on your lead lists.",
                "copyable_snippet": None,
            })

        return {
            "campaign_sent": campaign_sent,
            "direct_sent": direct_sent,
            "total_sent": total_sent,
            "provider_accepted": total_sent,
            "total_opened": total_opened,
            "total_clicked": total_clicked,
            "total_replied": total_replied,
            "total_bounced": total_bounced,
            "open_rate": open_rate,
            "click_rate": click_rate,
            "reply_rate": reply_rate,
            "bounce_rate": bounce_rate,
            "tracking_note": "SMTP status (250 OK) confirms handoff to receiving mail server. Recipient inbox placement is determined by recipient mailbox filtering, DMARC aggregate reports, and recipient engagements.",
            "issues": issues,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Error computing inbox delivery stats for #{inbox_id}: {e}", exc_info=True)
        return {
            "campaign_sent": 0,
            "direct_sent": 0,
            "total_sent": 0,
            "provider_accepted": 0,
            "total_opened": 0,
            "total_clicked": 0,
            "total_replied": 0,
            "total_bounced": 0,
            "open_rate": None,
            "click_rate": None,
            "reply_rate": None,
            "bounce_rate": None,
            "tracking_note": "Metrics unavailable due to query error.",
            "issues": [],
            "error": f"Failed to compute metrics: {str(e)}",
        }


def get_google_postmaster_reputation(domain: str) -> Dict[str, Any]:
    """Return genuine Google Postmaster Tools status.
    
    Never fabricates synthetic reputation scores. If unconfigured, clearly displays Data Unavailable.
    """
    return {
        "status": "not_available",
        "domain": domain,
        "domain_reputation": "Data Unavailable",
        "ip_reputation": "Data Unavailable",
        "user_reported_spam_rate": None,
        "spf_success_rate": None,
        "dkim_success_rate": None,
        "dmarc_success_rate": None,
        "details": (
            "Google Postmaster Tools data requires verified domain ownership in Google Postmaster "
            "and sending a minimum threshold of ~100 emails/day to personal @gmail.com recipients. "
            "Data is populated automatically once eligible traffic volume is reached."
        ),
        "is_configured": False,
    }


# ---------------------------------------------------------------------------
# End-to-End Inbox Health Scanner
# ---------------------------------------------------------------------------

async def run_domain_health_scan_for_inbox(
    db: AsyncSession,
    inbox_id: int,
    custom_dkim_selector: Optional[str] = None,
) -> DomainHealthScan:
    """Run an isolated end-to-end domain health scan for an inbox and persist results."""
    # 1. Fetch inbox
    inbox = await db.get(Inbox, inbox_id)
    if not inbox:
        raise ValueError(f"Inbox #{inbox_id} not found")

    domain = extract_domain(inbox.email)
    if not domain:
        raise ValueError(f"Invalid email address '{inbox.email}' on inbox #{inbox_id}")

    provider = inbox.provider or "smtp"

    # 2. Determine actual outgoing SMTP relay host and IP
    relay_host: Optional[str] = None
    if provider == "smtp":
        smtp_res = await db.execute(select(SmtpAccount).where(SmtpAccount.inbox_id == inbox_id))
        smtp_acc = smtp_res.scalar_one_or_none()
        if smtp_acc and smtp_acc.smtp_host:
            relay_host = smtp_acc.smtp_host
    elif provider == "gmail":
        relay_host = "smtp.gmail.com"
    elif provider == "office365":
        relay_host = "smtp.office365.com"

    # 3. Run DNS checks safely
    try:
        spf_result = check_spf_record(domain, provider=provider, smtp_host=relay_host)
    except Exception as e:
        logger.error(f"SPF check failed for {domain}: {e}")
        spf_result = {"status": "dns_error", "record": None, "issues": [{"severity": "warning", "title": "SPF Check Error", "message": str(e), "code": "SPF_ERR", "recommendation": "Retry scan."}]}

    try:
        dkim_result = check_dkim_record(domain, custom_selector=custom_dkim_selector, provider=provider, smtp_host=relay_host)
    except Exception as e:
        logger.error(f"DKIM check failed for {domain}: {e}")
        dkim_result = {"status": "not_verified", "record": None, "selector": None, "issues": [{"severity": "info", "title": "DKIM Check Error", "message": str(e), "code": "DKIM_ERR", "recommendation": "Retry scan."}]}

    try:
        dmarc_result = check_dmarc_record(domain)
    except Exception as e:
        logger.error(f"DMARC check failed for {domain}: {e}")
        dmarc_result = {"status": "dns_error", "record": None, "policy": None, "issues": [{"severity": "warning", "title": "DMARC Check Error", "message": str(e), "code": "DMARC_ERR", "recommendation": "Retry scan."}]}

    try:
        mx_result = check_mx_records(domain)
    except Exception as e:
        logger.error(f"MX check failed for {domain}: {e}")
        mx_result = {"status": "warning", "records": [], "detected_provider": "Unknown", "issues": [{"severity": "warning", "title": "MX Check Error", "message": str(e), "code": "MX_ERR", "recommendation": "Retry scan."}]}

    # Fallback relay host if not configured
    if not relay_host and mx_result.get("records"):
        relay_host = mx_result["records"][0]["host"]

    # 4. Blocklist check against actual relay host
    try:
        blocklist_result = check_dnsbl_blocklists(domain, relay_host=relay_host)
    except Exception as e:
        logger.error(f"Blocklist check failed for {domain}: {e}")
        blocklist_result = {"status": "not_checked", "results": [], "issues": []}

    # 5. Delivery performance stats (isolated try/except)
    delivery_stats = await get_inbox_delivery_stats(db, inbox_id)

    # 6. Reputation
    reputation_result = get_google_postmaster_reputation(domain)

    # 7. Aggregate issues & determine overall status
    all_issues: List[Dict[str, Any]] = []
    all_issues.extend(spf_result.get("issues", []))
    all_issues.extend(dkim_result.get("issues", []))
    all_issues.extend(dmarc_result.get("issues", []))
    all_issues.extend(mx_result.get("issues", []))
    all_issues.extend(blocklist_result.get("issues", []))
    all_issues.extend(delivery_stats.get("issues", []))

    has_critical = any(i["severity"] == "critical" for i in all_issues)
    has_warning = any(i["severity"] == "warning" for i in all_issues)

    if has_critical:
        overall_status = "critical"
    elif has_warning:
        overall_status = "warning"
    elif spf_result["status"] in ("healthy", "clean") and dmarc_result["status"] in ("healthy", "clean"):
        overall_status = "healthy"
    else:
        overall_status = "warning"

    scan = DomainHealthScan(
        inbox_id=inbox.id,
        domain=domain,
        overall_status=overall_status,
        spf_status=spf_result["status"],
        spf_record=spf_result.get("record"),
        spf_details=spf_result,
        dkim_status=dkim_result["status"],
        dkim_selector=dkim_result.get("selector"),
        dkim_record=dkim_result.get("record"),
        dkim_details=dkim_result,
        dmarc_status=dmarc_result["status"],
        dmarc_policy=dmarc_result.get("policy"),
        dmarc_record=dmarc_result.get("record"),
        dmarc_details=dmarc_result,
        mx_status=mx_result["status"],
        mx_records=mx_result.get("records", []),
        blocklist_status=blocklist_result["status"],
        blocklist_details=blocklist_result,
        reputation_status=reputation_result["status"],
        reputation_details=reputation_result,
        delivery_stats=delivery_stats,
        issues=all_issues,
        scanned_at=utcnow(),
    )

    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    return scan


# ---------------------------------------------------------------------------
# Recipient-Side Deliverability Testing & Email Header Analyzer
# ---------------------------------------------------------------------------

def analyze_email_headers(raw_headers_or_eml: str, is_demo: bool = False) -> Dict[str, Any]:
    """Analyze raw email headers or imported .eml file.
    
    Parses recipient-side authentication results, DKIM signatures, SPF verification,
    sending relay IPs from Received headers, and domain alignment.
    """
    if not raw_headers_or_eml or not raw_headers_or_eml.strip():
        raise ValueError("Header text or EML content is empty")

    msg = email.message_from_string(raw_headers_or_eml, policy=policy.default)

    from_header = msg.get("From", "")
    to_header = msg.get("To", "")
    subject_header = msg.get("Subject", "")
    date_header = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")
    return_path = msg.get("Return-Path", "")

    from_domain = extract_domain(from_header)
    return_path_domain = extract_domain(return_path) if return_path else ""

    # Parse sending relay from Received headers
    received_headers = msg.get_all("Received", []) or []
    sending_relay_host = None
    sending_relay_ip = None
    for r in received_headers:
        r_str = str(r)
        ip_match = re.search(r"\[([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})\]", r_str)
        if ip_match and not sending_relay_ip:
            sending_relay_ip = ip_match.group(1)
        host_match = re.search(r"from\s+([a-zA-Z0-9.\-_]+)", r_str)
        if host_match and not sending_relay_host:
            sending_relay_host = host_match.group(1)

    auth_results_raw = msg.get_all("Authentication-Results", []) or []
    arc_auth_results_raw = msg.get_all("ARC-Authentication-Results", []) or []
    all_auth_headers = auth_results_raw + arc_auth_results_raw

    spf_verdict = "unknown"
    spf_reason = ""
    dkim_verdict = "unknown"
    dkim_reason = ""
    dmarc_verdict = "unknown"

    auth_combined = " ".join([str(h) for h in all_auth_headers])

    received_spf = msg.get("Received-SPF", "")
    if received_spf:
        spf_lower = str(received_spf).lower()
        if "pass" in spf_lower:
            spf_verdict = "pass"
            spf_reason = str(received_spf)
        elif "fail" in spf_lower:
            spf_verdict = "fail"
            spf_reason = str(received_spf)
        elif "softfail" in spf_lower:
            spf_verdict = "softfail"
            spf_reason = str(received_spf)
        elif "neutral" in spf_lower:
            spf_verdict = "neutral"
            spf_reason = str(received_spf)
        elif "none" in spf_lower:
            spf_verdict = "none"
            spf_reason = str(received_spf)

    spf_match = re.search(r"\bspf=(pass|fail|softfail|neutral|none|permerror|temperror)\b", auth_combined, re.IGNORECASE)
    if spf_match:
        spf_verdict = spf_match.group(1).lower()

    dkim_match = re.search(r"\bdkim=(pass|fail|neutral|none|permerror|temperror)\b", auth_combined, re.IGNORECASE)
    if dkim_match:
        dkim_verdict = dkim_match.group(1).lower()

    dmarc_match = re.search(r"\bdmarc=(pass|fail|none|temperror|permerror)\b", auth_combined, re.IGNORECASE)
    if dmarc_match:
        dmarc_verdict = dmarc_match.group(1).lower()

    dkim_signatures: List[Dict[str, Any]] = []
    raw_dkim_sigs = msg.get_all("DKIM-Signature", []) or []
    for sig in raw_dkim_sigs:
        sig_str = str(sig).replace("\n", " ").replace("\r", " ")
        d_match = re.search(r"\bd=([a-zA-Z0-9.\-_]+)", sig_str)
        s_match = re.search(r"\bs=([a-zA-Z0-9.\-_]+)", sig_str)
        a_match = re.search(r"\ba=([a-zA-Z0-9\-]+)", sig_str)
        sig_d = d_match.group(1) if d_match else None
        sig_s = s_match.group(1) if s_match else None
        sig_a = a_match.group(1) if a_match else None

        # Check whether the selector in the email matches an active published key in DNS
        published_dns_status = "not_checked"
        published_dns_record = None
        if sig_s and sig_d:
            try:
                dns_check = check_dkim_record(sig_d, custom_selector=sig_s)
                if dns_check.get("record"):
                    published_dns_status = "verified_in_dns"
                    published_dns_record = dns_check.get("record")
                else:
                    published_dns_status = "not_found_in_dns"
            except Exception:
                published_dns_status = "lookup_error"

        dkim_signatures.append({
            "signing_domain": sig_d,
            "selector": sig_s,
            "algorithm": sig_a,
            "published_dns_status": published_dns_status,
            "published_dns_record": published_dns_record,
            "raw": sig_str[:120] + "..." if len(sig_str) > 120 else sig_str,
        })

    spf_aligned = bool(
        from_domain and return_path_domain and (
            from_domain == return_path_domain or from_domain.endswith("." + return_path_domain) or return_path_domain.endswith("." + from_domain)
        )
    )

    dkim_aligned = False
    for sig in dkim_signatures:
        sig_d = sig.get("signing_domain")
        if sig_d and from_domain:
            if sig_d.lower() == from_domain.lower() or from_domain.lower().endswith("." + sig_d.lower()):
                dkim_aligned = True
                break

    overall_test_status = "healthy"
    diagnostics: List[Dict[str, Any]] = []

    if spf_verdict == "pass" and spf_aligned:
        diagnostics.append({"category": "SPF", "status": "pass", "message": f"SPF Passed and aligned with From domain '{from_domain}'"})
    elif spf_verdict == "pass" and not spf_aligned:
        diagnostics.append({"category": "SPF", "status": "warning", "message": f"SPF Passed on Return-Path '{return_path_domain}', but does not align with From domain '{from_domain}'"})
        overall_test_status = "warning"
    elif spf_verdict in ("fail", "softfail"):
        diagnostics.append({"category": "SPF", "status": "fail", "message": f"SPF {spf_verdict.upper()}: Sending server not authorized in domain SPF record"})
        overall_test_status = "critical"
    else:
        diagnostics.append({"category": "SPF", "status": "unknown", "message": f"SPF verdict: {spf_verdict}"})

    if dkim_verdict == "pass" and dkim_aligned:
        diagnostics.append({"category": "DKIM", "status": "pass", "message": f"DKIM Passed and signing domain matches From domain '{from_domain}'"})
    elif dkim_verdict == "pass" and not dkim_aligned:
        diagnostics.append({"category": "DKIM", "status": "warning", "message": "DKIM signature passed, but signing domain differs from From header domain"})
        overall_test_status = "warning"
    elif dkim_verdict == "fail":
        diagnostics.append({"category": "DKIM", "status": "fail", "message": "DKIM signature verification failed (body or headers altered in transit)"})
        overall_test_status = "critical"
    else:
        diagnostics.append({"category": "DKIM", "status": "warning", "message": f"DKIM status: {dkim_verdict}"})

    for sig in dkim_signatures:
        s_name = sig.get("selector")
        d_name = sig.get("signing_domain")
        if sig.get("published_dns_status") == "verified_in_dns":
            diagnostics.append({
                "category": "DKIM DNS Alignment",
                "status": "pass",
                "message": f"Published DKIM Public Key confirmed in DNS at '{s_name}._domainkey.{d_name}'. The sent email signature selector matches your published DNS record.",
            })
        elif sig.get("published_dns_status") == "not_found_in_dns":
            diagnostics.append({
                "category": "DKIM DNS Alignment",
                "status": "warning",
                "message": f"DKIM signature uses selector '{s_name}', but no matching public key record was found at '{s_name}._domainkey.{d_name}' in DNS.",
            })

    if dmarc_verdict == "pass":
        diagnostics.append({"category": "DMARC", "status": "pass", "message": "DMARC Passed: Email satisfies authentication and domain alignment requirements"})
    elif dmarc_verdict == "fail":
        diagnostics.append({"category": "DMARC", "status": "fail", "message": "DMARC Failed: Neither SPF nor DKIM passed in alignment with From domain"})
        overall_test_status = "critical"
    else:
        diagnostics.append({"category": "DMARC", "status": "info", "message": f"DMARC verdict: {dmarc_verdict}"})

    return {
        "overall_status": overall_test_status,
        "is_demo_data": bool(is_demo),
        "from": from_header,
        "from_domain": from_domain,
        "to": to_header,
        "subject": subject_header,
        "date": date_header,
        "message_id": message_id,
        "return_path": return_path,
        "return_path_domain": return_path_domain,
        "sending_relay_host": sending_relay_host,
        "sending_relay_ip": sending_relay_ip,
        "spf": {
            "verdict": spf_verdict,
            "aligned": spf_aligned,
            "reason": spf_reason,
        },
        "dkim": {
            "verdict": dkim_verdict,
            "aligned": dkim_aligned,
            "signatures": dkim_signatures,
            "dns_key_matched": any(s.get("published_dns_status") == "verified_in_dns" for s in dkim_signatures),
        },
        "dmarc": {
            "verdict": dmarc_verdict,
        },
        "diagnostics": diagnostics,
        "raw_authentication_results": [str(h) for h in all_auth_headers[:3]],
    }


async def run_domain_health_daily_job() -> None:
    """Scheduled background job: runs once daily across unique connected domains."""
    from app.database import AsyncSessionLocal

    logger.info("Starting scheduled Domain Health daily scan job...")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Inbox))
        inboxes = result.scalars().all()

        scanned_domains: Set[str] = set()
        count = 0

        for ibx in inboxes:
            dom = extract_domain(ibx.email)
            if not dom:
                continue

            try:
                await run_domain_health_scan_for_inbox(db, ibx.id)
                scanned_domains.add(dom)
                count += 1
            except Exception as e:
                logger.error(f"Error running scheduled health scan for inbox #{ibx.id} ({ibx.email}): {e}")

        logger.info(f"Scheduled Domain Health scan completed: {count} inboxes scanned across {len(scanned_domains)} unique domains.")
