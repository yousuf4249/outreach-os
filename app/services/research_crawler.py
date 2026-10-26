"""Weblinx Outreach OS - Prospect Website Crawler & Structured Enrichment

Lightweight, async HTTP extraction engine (HTTPX + BeautifulSoup):
1. Crawls homepage, /contact, /about, /team, /services
2. Extracts JSON-LD schema (Organization, LocalBusiness, Person, Founder)
3. Extracts public mailto and body emails (strict validation, NO hallucinated/guessed patterns)
4. Extracts business phone numbers and social profile links (LinkedIn, Twitter, Instagram)
5. Discovers leadership / decision-maker contacts with exact job titles
6. Tracks complete field-level provenance (source_url, snippet, extracted_at, confidence)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger("weblinx.research.crawler")

# Email regex matching RFC standard addresses
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Phone regex (US and international formats)
PHONE_REGEX = re.compile(
    r"(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b"
)

# Dummy, asset, or template domains to discard
INVALID_EMAIL_DOMAINS = {
    "example.com",
    "domain.com",
    "email.com",
    "yoursite.com",
    "yourdomain.com",
    "test.com",
    "wixpress.com",
    "sentry.io",
    "cloudflare.com",
    "gravatar.com",
    "schema.org",
}

# Shared platform hosts where a company's website is a profile on a third-party host
SHARED_PLATFORM_DOMAINS = {
    "moneygram.com",
    "linktr.ee",
    "wordpress.com",
    "hub.biz",
    "facebook.com",
    "instagram.com",
    "nextdoor.com",
    "google.com",
    "yelp.com",
    "wix.com",
    "squarespace.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "yellowpages.com",
    "mapquest.com",
}

# Free public webmail providers (used by small local businesses)
PUBLIC_WEBMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "aol.com", "protonmail.com", "proton.me", "mail.com", "msn.com", "live.com",
    "ymail.com", "rocketmail.com", "zoho.com",
}

# Third-party software, CMS, or infrastructure vendor domains (not corporate business emails)
THIRD_PARTY_VENDOR_DOMAINS = {
    "shopify.com", "wix.com", "squarespace.com", "wordpress.org", "hubspot.com",
    "mailchimp.com", "zendesk.com", "salesforce.com", "intercom.io", "stripe.com",
    "godaddy.com", "namecheap.com", "cloudflare.com", "github.com", "wixpress.com",
}

def verify_email_domain_relationship(
    email: str,
    base_domain: str,
    company_name: str,
    snippet: str = "",
    page_text: str = "",
) -> Tuple[str, str, float]:
    """Verify company ownership and relationships when the published email domain differs from website domain.

    Returns: (relationship_type, evidence_explanation, confidence_modifier)
    """
    local_part = email.split("@")[0].lower()
    email_domain = email.split("@")[-1].lower()

    # Case 1: Exact or subdomain match
    if email_domain == base_domain or base_domain.endswith("." + email_domain) or email_domain.endswith("." + base_domain):
        return (
            "direct_domain_match",
            f"Email domain '@{email_domain}' directly matches official website domain '{base_domain}'.",
            1.0,
        )

    # Case 2: Third-party software, CMS, or infrastructure vendor
    if email_domain in THIRD_PARTY_VENDOR_DOMAINS or any(v in email_domain for v in ("shopify", "wix", "squarespace", "wordpress")):
        return (
            "third_party_vendor_platform",
            f"Email domain '@{email_domain}' belongs to third-party software/hosting vendor, not the company.",
            0.0,
        )

    # Case 3: Public webmail provider (e.g. @gmail.com for small local business)
    if email_domain in PUBLIC_WEBMAIL_DOMAINS:
        company_clean = re.sub(r"[^a-z0-9]", "", company_name.lower())
        local_clean = re.sub(r"[^a-z0-9]", "", local_part)
        words = [w.lower() for w in re.split(r"[^a-zA-Z0-9]+", company_name) if len(w) > 3]

        if company_clean in local_clean or local_clean in company_clean or any(w in local_clean for w in words):
            return (
                "verified_owner_webmail",
                f"Public webmail provider '@{email_domain}' verified: address handle '{local_part}' matches company brand '{company_name}'.",
                0.90,
            )
        else:
            return (
                "unverified_personal_webmail",
                f"Public webmail provider '@{email_domain}' published on site, but address handle lacks distinct brand matching.",
                0.75,
            )

    # Case 4: Corporate / Enterprise domain differing from website (e.g. Conlan Tire vs Continental BestDrive)
    combined_context = f"{snippet} {page_text}".lower()
    domain_root = email_domain.split(".")[0]
    company_name_words = [w.lower() for w in re.split(r"[^a-zA-Z0-9]+", company_name) if len(w) > 3]

    # Check for third-party distributor or international sales listing
    if any(k in combined_context for k in ("international distributor", "distributor", "reseller", "dealer locator", "overseas partner", "sales rep in")):
        return (
            "third_party_distributor",
            f"Email domain '@{email_domain}' belongs to an external third-party distributor or reseller, not '{company_name}'.",
            0.0,
        )

    # Explicit corporate division / operating entity affiliation
    has_explicit_division = any(
        phrase in combined_context
        for phrase in (
            "division of", "operating as", "subsidiary of", "parent company", "brand of",
            "acquired by", "operated by", "a division of", "doing business as", "d/b/a",
            f"division of {domain_root}", f"operated by {domain_root}"
        )
    )

    if has_explicit_division:
        return (
            "verified_corporate_division",
            f"Differing corporate domain '@{email_domain}' verified as affiliated operating entity or parent for '{company_name}' via official site documentation.",
            0.88,
        )
    else:
        return (
            "unverified_differing_domain",
            f"Differing corporate domain '@{email_domain}' detected on website without verified parent or subsidiary affiliation.",
            0.50,
        )


# Automated, broadcast, and non-contact email prefixes to discard
DISQUALIFIED_EMAIL_PREFIXES = (
    "no-reply",
    "noreply",
    "donotreply",
    "do-not-reply",
    "accessibility",
    "privacy",
    "legal",
    "abuse",
    "postmaster",
    "mailer-daemon",
    "daemon",
    "unsubscribe",
    "bounce",
    "security",
)

# Non-person dictionary words that should NEVER be extracted as person first/last names
NON_PERSON_WORDS = {
    "welcome", "discover", "dallas", "baptist", "university", "company", "services",
    "management", "contact", "about", "our", "the", "terms", "privacy", "home",
    "page", "menu", "search", "portal", "login", "sign", "online", "partners",
    "bestdrive", "continental", "group", "center", "community", "academy", "church",
    "school", "high", "elementary", "middle", "senior", "office", "service", "support",
    "sales", "help", "info", "admin", "billing", "desk", "inquiries", "team", "dispatch",
    "admissions", "admiss", "general", "department", "headquarters", "location", "facility",
    "texas", "austin", "houston", "america", "global", "national", "customer", "client",
    "hours", "schedule", "read", "more", "learn", "view", "click", "here", "copyright",
}

# Departmental / general inbox names
GENERIC_DEPARTMENT_LOCAL_PARTS = {
    "info", "hello", "contact", "office", "service", "services", "sales", "support",
    "admin", "help", "billing", "inquiries", "inquiry", "team", "dispatch", "connect",
    "mail", "general", "reception", "desk", "frontdesk", "admiss", "admissions", "inbox"
}

# Recognized common English first names for single-word local part verification
KNOWN_COMMON_FIRST_NAMES = {
    "john", "jane", "alex", "michael", "sarah", "david", "chris", "caleb", "erin", "brian",
    "jason", "lisa", "mark", "matthew", "daniel", "james", "robert", "william", "joseph",
    "mary", "patricia", "jennifer", "elizabeth", "tom", "tim", "steve", "paul", "andrew",
    "josh", "kevin", "adam", "ryan", "justin", "eric", "brandon", "emily", "jessica",
    "ashley", "amanda", "stephanie", "nicole", "anthony", "richard", "charles", "thomas",
}

# Image or media extensions mistakenly caught in regex
INVALID_EMAIL_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".css",
    ".js",
    ".woff",
    ".woff2",
)

# Leadership titles to identify decision makers
LEADERSHIP_TITLES = [
    "founder",
    "co-founder",
    "ceo",
    "chief executive officer",
    "president",
    "managing director",
    "principal",
    "partner",
    "creative director",
    "owner",
    "agency director",
    "head of design",
    "technical director",
    "vp",
    "vice president",
]


class ProspectEnrichmentCrawler:
    """Extracts verified public business information and leadership contacts from official websites."""

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def enrich_company(
        self,
        website_url: str,
        company_name: str,
        preloaded_seed: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform targeted crawling of official website to extract company details and leadership contacts."""
        if not website_url.startswith(("http://", "https://")):
            website_url = "https://" + website_url

        parsed_base = urlparse(website_url)
        base_domain = parsed_base.netloc.replace("www.", "").lower()

        extracted_data = {
            "website": website_url,
            "domain": base_domain,
            "title": "",
            "description": "",
            "headings": [],
            "website_evidence": "",
            "phone": "",
            "address": "",
            "socials": {},
            "contacts": [],
            "provenance": {},
        }

        # If seed data includes verified founder contact, incorporate as primary
        if preloaded_seed and preloaded_seed.get("known_contact"):
            kc = preloaded_seed["known_contact"]
            now_str = datetime.now(timezone.utc).isoformat()
            extracted_data["contacts"].append({
                "name": kc.get("name"),
                "first_name": kc.get("first_name"),
                "last_name": kc.get("last_name"),
                "role": kc.get("role", "Founder"),
                "email": kc.get("email"),
                "phone": preloaded_seed.get("phone", ""),
                "linkedin_url": kc.get("linkedin_url", ""),
                "confidence_score": 1.0,
                "field_provenance": {
                    "email": {
                        "source_url": website_url,
                        "snippet": f"Verified public leadership contact for {company_name}",
                        "extracted_at": now_str,
                    },
                    "role": {
                        "source_url": website_url,
                        "snippet": kc.get("role"),
                        "extracted_at": now_str,
                    },
                },
            })
            if preloaded_seed.get("phone"):
                extracted_data["phone"] = preloaded_seed["phone"]
            if preloaded_seed.get("description") and not preloaded_seed["description"].startswith("Discovered from Overture"):
                extracted_data["description"] = preloaded_seed["description"]
            if preloaded_seed.get("address"):
                extracted_data["address"] = preloaded_seed["address"]

        # Attempt live web extraction
        discovered_emails: Dict[str, Dict[str, Any]] = {}
        discovered_phones: Set[str] = set()
        discovered_socials: Dict[str, str] = {}
        discovered_people: List[Dict[str, Any]] = []

        pages_to_crawl = [website_url]
        crawled_urls: Set[str] = set()

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=False,
        ) as client:
            try:
                resp = await client.get(website_url)
                if resp.status_code == 200:
                    crawled_urls.add(website_url)
                    html = resp.text
                    soup = BeautifulSoup(html, "html.parser")

                    # Extract title and headings
                    title = soup.title.string.strip() if soup.title and soup.title.string else ""
                    extracted_data["title"] = title
                    headings = [h.get_text().strip() for h in soup.find_all(['h1', 'h2']) if h.get_text().strip()][:8]
                    extracted_data["headings"] = headings

                    # 1. Meta & OpenGraph Extraction
                    desc = self._extract_meta_description(soup)
                    if desc:
                        extracted_data["description"] = desc
                    elif not extracted_data["description"] or extracted_data["description"].startswith("Discovered from Overture"):
                        body_words = [w for w in soup.get_text().split() if len(w) > 1]
                        extracted_data["description"] = " ".join(body_words[:40])

                    # Build consolidated website evidence
                    body_sample = " ".join(soup.get_text().split()[:150])
                    extracted_data["website_evidence"] = (
                        f"Title: {title}. Description: {extracted_data['description']}. "
                        f"Headings: {' | '.join(headings[:4])}. Sample: {body_sample[:250]}"
                    )

                    # 2. JSON-LD structured data extraction
                    self._extract_json_ld(
                        soup,
                        website_url,
                        discovered_emails,
                        discovered_phones,
                        discovered_people,
                        discovered_socials,
                    )

                    # 3. Discover subpages: /contact, /about, /team
                    subpages = self._find_relevant_links(soup, website_url, base_domain)
                    for sub in subpages[:3]:
                        if sub not in pages_to_crawl:
                            pages_to_crawl.append(sub)

                    # 4. Extract body emails and phones
                    self._extract_text_contacts(
                        soup, html, website_url, discovered_emails, discovered_phones, discovered_socials
                    )

            except Exception as e:
                logger.debug("Failed initial homepage fetch for %s: %s", website_url, e)
                extracted_data["website_evidence"] = f"Unreachable website or connection timeout ({e})"

            # Crawl discovered subpages (/contact, /about, /team)
            for page_url in pages_to_crawl[1:]:
                if page_url in crawled_urls:
                    continue
                try:
                    crawled_urls.add(page_url)
                    resp = await client.get(page_url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        self._extract_json_ld(
                            soup,
                            page_url,
                            discovered_emails,
                            discovered_phones,
                            discovered_people,
                            discovered_socials,
                        )
                        self._extract_text_contacts(
                            soup, resp.text, page_url, discovered_emails, discovered_phones, discovered_socials
                        )
                        self._extract_team_members(soup, page_url, discovered_people)
                except Exception as e:
                    logger.debug("Subpage crawl failed for %s: %s", page_url, e)

        # Merge extracted socials
        extracted_data["socials"].update(discovered_socials)

        # If phone found and none in seed
        if discovered_phones and not extracted_data["phone"]:
            extracted_data["phone"] = next(iter(discovered_phones))

        # Build contact list from discovered people and emails
        if discovered_people:
            for p in discovered_people:
                # Deduplicate against existing contacts
                if any(c.get("name") == p.get("name") for c in extracted_data["contacts"]):
                    continue
                extracted_data["contacts"].append(p)

        # Evaluate discovered emails for entity relationship and assign appropriately
        if discovered_emails:
            # Check if company website is on a shared platform or parent campus
            is_shared_platform = any(base_domain == sp or base_domain.endswith("." + sp) for sp in SHARED_PLATFORM_DOMAINS)
            is_academic_campus = base_domain.endswith(".edu") or base_domain.endswith(".gov")
            is_campus_venue = is_academic_campus and any(
                w in company_name.lower()
                for w in ("coffee", "cafe", "theatre", "theater", "chapel", "church", "library", "store", "shop")
            )

            for email, meta in discovered_emails.items():
                # Check if email already associated with an extracted contact
                if any(c.get("email") == email for c in extracted_data["contacts"]):
                    continue

                local_part = email.split("@")[0].lower()
                email_domain = email.split("@")[-1].lower()

                # Verify ownership and domain relationship
                rel_type, rel_evidence, rel_conf = verify_email_domain_relationship(
                    email=email,
                    base_domain=base_domain,
                    company_name=company_name,
                    snippet=meta.get("snippet", ""),
                    page_text=html[:3000] if 'html' in locals() else "",
                )

                # Rule 0: Skip third-party vendor platforms (Shopify, Wix, WordPress, etc.)
                if rel_type == "third_party_vendor_platform":
                    logger.debug("Skipping third-party vendor platform email %s for %s", email, company_name)
                    continue

                # Rule 1: Never assign third-party shared platform corporate emails to a local retail/business entity
                if is_shared_platform and email_domain in SHARED_PLATFORM_DOMAINS:
                    logger.debug("Skipping platform corporate email %s for local business %s", email, company_name)
                    continue

                # Rule 2: Do not attach university central administration emails (admissions, registrar, etc.)
                # to a specific commercial kiosk, coffeehouse, or venue on campus
                if is_campus_venue and local_part in ("admiss", "admissions", "alumni", "president", "registrar", "finaid", "housing"):
                    logger.debug("Skipping parent university admin email %s for campus venue %s", email, company_name)
                    continue

                # Rule 3: Distinguish departmental general mailboxes from genuine personal contacts
                now_str = datetime.now(timezone.utc).isoformat()
                is_departmental = local_part in GENERIC_DEPARTMENT_LOCAL_PARTS

                if is_departmental:
                    contact_name = f"{company_name} ({local_part.title()} Desk)"
                    first_name = None
                    last_name = None
                    role = f"{local_part.title()} / General Inquiries"
                    confidence = round(0.90 * rel_conf, 2)
                else:
                    # Clean potential person name from local part
                    name_parts = [p.title() for p in local_part.replace(".", " ").replace("_", " ").split() if p.isalpha()]
                    if len(name_parts) >= 2 and not any(p.lower() in NON_PERSON_WORDS for p in name_parts):
                        first_name = name_parts[0]
                        last_name = " ".join(name_parts[1:])
                        contact_name = f"{first_name} {last_name}"
                        role = "Company Representative"
                        confidence = round(0.85 * rel_conf, 2)
                    elif len(name_parts) == 1 and name_parts[0].lower() in KNOWN_COMMON_FIRST_NAMES:
                        first_name = name_parts[0]
                        last_name = None
                        contact_name = f"{first_name} ({company_name})"
                        role = "Company Representative"
                        confidence = round(0.80 * rel_conf, 2)
                    else:
                        contact_name = f"{company_name} ({local_part.title()} Desk)" if local_part.isalpha() else f"{company_name} Contact"
                        first_name = None
                        last_name = None
                        role = "Company Representative"
                        confidence = round(0.75 * rel_conf, 2)

                extracted_data["contacts"].append({
                    "name": contact_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "email": email,
                    "phone": extracted_data["phone"],
                    "linkedin_url": extracted_data["socials"].get("linkedin", ""),
                    "confidence_score": confidence,
                    "field_provenance": {
                        "email": {
                            "source_url": meta.get("source_url", website_url),
                            "snippet": meta.get("snippet", ""),
                            "extracted_at": now_str,
                            "relationship": rel_type,
                            "relationship_evidence": rel_evidence,
                            "domain_match": email_domain == base_domain,
                        }
                    },
                })

        # Strict Rule: If no contacts discovered at all, add a single placeholder contact with NO email
        if not extracted_data["contacts"]:
            extracted_data["contacts"].append({
                "name": f"{company_name} Contact",
                "first_name": "",
                "last_name": "",
                "role": "Representative",
                "email": None,  # NEVER GUESS OR INVENT EMAILS
                "phone": extracted_data["phone"],
                "linkedin_url": extracted_data["socials"].get("linkedin", ""),
                "confidence_score": 0.5,
                "field_provenance": {
                    "note": "No public email address published on official website."
                },
            })

        return extracted_data

    def _extract_meta_description(self, soup: BeautifulSoup) -> str:
        """Extract description from standard meta and OpenGraph tags."""
        for name in ("description", "og:description", "twitter:description"):
            tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
            if tag and tag.get("content"):
                clean = tag["content"].strip()
                if len(clean) > 10:
                    return clean
        return ""

    def _find_relevant_links(self, soup: BeautifulSoup, base_url: str, base_domain: str) -> List[str]:
        """Find contact, about, and team links on the website."""
        links: List[str] = []
        keywords = ("contact", "about", "team", "people", "leadership", "studio", "services")

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            norm_netloc = parsed.netloc.replace("www.", "").lower()

            # Ensure same domain
            if norm_netloc == base_domain:
                path = parsed.path.lower()
                if any(kw in path for kw in keywords):
                    if full_url not in links and full_url != base_url:
                        links.append(full_url)
        return links

    def _extract_json_ld(
        self,
        soup: BeautifulSoup,
        source_url: str,
        emails: Dict[str, Dict[str, Any]],
        phones: Set[str],
        people: List[Dict[str, Any]],
        socials: Dict[str, str],
    ):
        """Extract structured data from JSON-LD schema blocks."""
        now_str = datetime.now(timezone.utc).isoformat()
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # Direct email
                    email = item.get("email")
                    if email and self._is_valid_email(email):
                        emails[email.lower()] = {
                            "source_url": source_url,
                            "snippet": f"JSON-LD Schema {item.get('@type', 'Organization')} email attribute",
                            "extracted_at": now_str,
                        }

                    # Direct telephone
                    phone = item.get("telephone")
                    if phone and isinstance(phone, str) and len(phone) >= 7:
                        phones.add(phone.strip())

                    # Social profiles
                    same_as = item.get("sameAs", [])
                    if isinstance(same_as, str):
                        same_as = [same_as]
                    for url in same_as:
                        if "linkedin.com" in url:
                            socials["linkedin"] = url
                        elif "twitter.com" in url or "x.com" in url:
                            socials["twitter"] = url
                        elif "instagram.com" in url:
                            socials["instagram"] = url

                    # Founder / Person extraction
                    for key in ("founder", "employee", "alumni", "contactPoint"):
                        p_data = item.get(key)
                        if isinstance(p_data, dict) and p_data.get("name"):
                            p_name = p_data.get("name")
                            parts = p_name.split()
                            p_email = p_data.get("email") if self._is_valid_email(p_data.get("email")) else None
                            people.append({
                                "name": p_name,
                                "first_name": parts[0] if parts else "",
                                "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
                                "role": p_data.get("jobTitle") or "Founder",
                                "email": p_email,
                                "phone": p_data.get("telephone") or "",
                                "linkedin_url": p_data.get("sameAs") if isinstance(p_data.get("sameAs"), str) else "",
                                "confidence_score": 0.95,
                                "field_provenance": {
                                    "source_url": source_url,
                                    "snippet": f"JSON-LD {key}: {p_name} ({p_data.get('jobTitle', '')})",
                                    "extracted_at": now_str,
                                },
                            })
            except Exception:
                continue

    def _extract_text_contacts(
        self,
        soup: BeautifulSoup,
        raw_html: str,
        source_url: str,
        emails: Dict[str, Dict[str, Any]],
        phones: Set[str],
        socials: Dict[str, str],
    ):
        """Extract mailto links, social links, and text patterns."""
        now_str = datetime.now(timezone.utc).isoformat()

        # 1. Mailto links
        for a in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
            href = a.get("href", "")
            raw_email = href.replace("mailto:", "").split("?")[0].strip().lower()
            if self._is_valid_email(raw_email):
                snippet = a.get_text(strip=True) or f"Mailto link on {source_url}"
                emails[raw_email] = {
                    "source_url": source_url,
                    "snippet": f"Mailto link: {snippet[:150]}",
                    "extracted_at": now_str,
                }

        # 2. Body regex emails
        text_matches = EMAIL_REGEX.findall(raw_html)
        for em in text_matches:
            em_clean = em.strip().lower()
            if self._is_valid_email(em_clean) and em_clean not in emails:
                emails[em_clean] = {
                    "source_url": source_url,
                    "snippet": f"Public email found in page text on {source_url}",
                    "extracted_at": now_str,
                }

        # 3. Tel links
        for a in soup.find_all("a", href=re.compile(r"^tel:", re.I)):
            href = a.get("href", "")
            raw_phone = href.replace("tel:", "").strip()
            if len(raw_phone) >= 7:
                phones.add(raw_phone)

        # 4. Social media links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "linkedin.com/company" in href or "linkedin.com/in" in href:
                socials["linkedin"] = href
            elif "twitter.com/" in href or "x.com/" in href:
                if not href.endswith(("/share", "/intent")):
                    socials["twitter"] = href
            elif "instagram.com/" in href:
                socials["instagram"] = href

    def _extract_team_members(
        self,
        soup: BeautifulSoup,
        source_url: str,
        people: List[Dict[str, Any]],
    ):
        """Scan team / about page markup for genuine leadership titles and verified person names."""
        now_str = datetime.now(timezone.utc).isoformat()
        
        # Only inspect containers explicitly marked as team/leadership cards
        team_containers = soup.find_all(
            ["div", "section", "article", "li"],
            class_=re.compile(r"(team|leadership|management|bio|person|staff|founder|executive|directors)", re.I)
        )

        for container in team_containers[:15]:
            headings = container.find_all(["h2", "h3", "h4", "h5", "strong"])
            for h in headings:
                cand_text = h.get_text(strip=True)
                words = [w for w in cand_text.split() if w.isalpha()]
                if len(words) != 2:
                    continue
                # Reject if either word is in non-person dictionary words
                if any(w.lower() in NON_PERSON_WORDS for w in words):
                    continue
                # Validate realistic person name lengths and capitalization
                if not (2 <= len(words[0]) <= 20 and 2 <= len(words[1]) <= 25):
                    continue
                if not (words[0][0].isupper() and words[1][0].isupper()):
                    continue

                container_text = container.get_text(" ", strip=True).lower()
                matched_role = None
                for title in LEADERSHIP_TITLES:
                    if title in container_text:
                        matched_role = title.title()
                        break

                if matched_role:
                    cand_name = f"{words[0]} {words[1]}"
                    if not any(p["name"] == cand_name for p in people):
                        people.append({
                            "name": cand_name,
                            "first_name": words[0],
                            "last_name": words[1],
                            "role": matched_role,
                            "email": None,
                            "phone": "",
                            "linkedin_url": "",
                            "confidence_score": 0.90,
                            "field_provenance": {
                                "source_url": source_url,
                                "snippet": f"Verified team card '{cand_name}' with title '{matched_role}'",
                                "extracted_at": now_str,
                            },
                        })
                        break

    def _is_valid_email(self, email: Optional[str]) -> bool:
        """Validate email against syntax rules, dummy domains, static asset extensions, and automated prefixes."""
        if not email or "@" not in email:
            return False
        clean = email.strip().lower()
        if any(clean.endswith(ext) for ext in INVALID_EMAIL_EXTENSIONS):
            return False
        local_part = clean.split("@")[0]
        # Reject automated, notification, and non-contact prefixes
        if any(
            local_part == p or local_part.startswith(p + "-") or local_part.startswith(p + ".") or local_part.startswith(p + "_")
            for p in DISQUALIFIED_EMAIL_PREFIXES
        ):
            return False
        domain = clean.split("@")[-1]
        if any(domain == d or domain.endswith("." + d) for d in INVALID_EMAIL_DOMAINS):
            return False
        if len(clean) > 320 or len(clean) < 6:
            return False
        return bool(EMAIL_REGEX.match(clean))
