"""Dataset loader and lookup utilities for email verification."""

import os
from functools import lru_cache
from typing import Optional, Set, Tuple

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_DISPOSABLE_FILE = os.path.join(_DATA_DIR, "disposable_domains.txt")

# Core fallback list of known disposable providers if file is missing
_FALLBACK_DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "10minutemail.com",
    "yopmail.com", "sharklasers.com", "trashmail.com", "dispostable.com",
    "getairmail.com", "nada.ltd", "mohmal.com", "burnermail.io", "maildrop.cc",
    "mytemp.email", "temp-mail.org", "fakeinbox.com", "crazymailing.com",
}

# Standard role prefixes and category mappings
ROLE_CATEGORIES = {
    "administrative": {
        "admin", "administrator", "root", "sysadmin", "postmaster",
        "hostmaster", "webmaster", "security", "noc", "master",
    },
    "general": {
        "info", "contact", "hello", "hi", "office", "mail", "inbox",
        "team", "general", "inquiries", "desk", "frontdesk", "help",
    },
    "sales_marketing": {
        "sales", "marketing", "business", "bd", "partners", "partnership",
        "press", "media", "growth", "leads", "revenue",
    },
    "support_service": {
        "support", "customerservice", "service", "care", "customercare",
        "tech", "helpdesk", "orders",
    },
    "finance_billing": {
        "billing", "finance", "accounting", "invoice", "invoices",
        "accounts", "pay", "payments",
    },
    "hr_recruiting": {
        "hr", "careers", "jobs", "recruiting", "talent", "hiring",
        "people", "work",
    },
    "legal_compliance": {
        "legal", "compliance", "privacy", "dpo", "abuse", "dmca",
    },
}

ALL_ROLE_PREFIXES: Set[str] = {prefix for group in ROLE_CATEGORIES.values() for prefix in group}

# Common domain typos mapped to canonical domain
COMMON_DOMAIN_TYPOS = {
    "gamil.com": "gmail.com",
    "gmial.com": "gmail.com",
    "gmaill.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmaik.com": "gmail.com",
    "gmal.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gemail.com": "gmail.com",
    "hotmial.com": "hotmail.com",
    "hotmaill.com": "hotmail.com",
    "hotmai.com": "hotmail.com",
    "hotmal.com": "hotmail.com",
    "outlok.com": "outlook.com",
    "outloo.com": "outlook.com",
    "outlookk.com": "outlook.com",
    "yaho.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "yaho.co": "yahoo.com",
    "iclod.com": "icloud.com",
    "iclou.com": "icloud.com",
    "icould.com": "icloud.com",
    "prtonmail.com": "protonmail.com",
    "protonmai.com": "protonmail.com",
    "yhoo.com": "yahoo.com",
    "iclud.com": "icloud.com",
}


@lru_cache(maxsize=1)
def load_disposable_domains() -> Set[str]:
    """Load the comprehensive set of disposable email domains into an in-memory set."""
    domains: Set[str] = set()
    if os.path.exists(_DISPOSABLE_FILE):
        try:
            with open(_DISPOSABLE_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    dom = line.strip().lower()
                    if dom and not dom.startswith("#"):
                        domains.add(dom)
        except Exception:
            domains.update(_FALLBACK_DISPOSABLE)
    else:
        domains.update(_FALLBACK_DISPOSABLE)
    return frozenset(domains)


def is_disposable_domain(domain: str) -> bool:
    """Return True if the domain is a known disposable/throwaway provider."""
    if not domain:
        return False
    d = domain.strip().lower()
    disposable_set = load_disposable_domains()
    if d in disposable_set:
        return True
    # Check parent domain (e.g. sub.mailinator.com)
    parts = d.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in disposable_set:
            return True
    return False


def check_role_account(local_part: str) -> Tuple[bool, Optional[str]]:
    """Check if the email local-part matches a known role or department address.
    
    Returns (is_role, category_name).
    """
    if not local_part:
        return False, None
    clean = local_part.strip().lower()
    
    # Direct match (e.g. 'info', 'support')
    for category, prefixes in ROLE_CATEGORIES.items():
        if clean in prefixes:
            return True, category

    # Delimited match (e.g. 'sales.team', 'info-uk', 'billing_dept')
    for sep in (".", "-", "_", "+"):
        if sep in clean:
            first_segment = clean.split(sep)[0]
            for category, prefixes in ROLE_CATEGORIES.items():
                if first_segment in prefixes:
                    return True, category

    return False, None


def check_typo_suggestion(domain: str) -> Optional[str]:
    """Return suggested canonical domain if a common domain typo is detected."""
    if not domain:
        return None
    return COMMON_DOMAIN_TYPOS.get(domain.strip().lower())
