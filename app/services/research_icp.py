"""Weblinx Outreach OS - Explainable ICP Matching & Service Verification Engine

Evaluates discovered businesses using verified official website evidence rather
than trusting raw open-data / Overture category labels alone.

Classifies companies into distinct business models:
1. Exact ICP Match: Bespoke client-service agencies (web design, custom web development, UI/UX, SEO, digital marketing).
2. Adjacent Partner: IT consultancies, digital transformation firms, enterprise systems integrators (e.g. Perfaware, Mindsphere).
3. SaaS / Product Company: Proprietary software products, self-serve tools, contract intelligence (e.g. SpendRule).
4. Other Industry: Physical facilities, storage/shredding (e.g. Safesite), automotive, churches, preschools, medical devices (Q-optics).
5. Needs Manual Review: Unreachable websites, parked domains, or insufficient commercial evidence.

Configurable per Research Job with explainable audit reason strings.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Universal non-commercial public institutions (disqualified unless explicitly targeted)
INSTITUTIONAL_NON_COMMERCIAL_CATEGORIES = {
    "church", "christian_place_of_worship", "place_of_worship", "religious_organization",
    "religious_school", "elementary_school", "middle_school", "high_school", "school",
    "preschool", "park", "historic_site", "community_center", "auditorium",
    "social_or_community_service", "cemetery", "crematorium",
}


def classify_business_service(
    company_name: str,
    website: str,
    domain: str,
    raw_category: str,
    title: str = "",
    description: str = "",
    website_evidence: str = "",
    headings: Optional[List[str]] = None,
    target_industry: Optional[str] = None,
) -> Tuple[str, str, int, str]:
    """Verify actual business services using official website evidence.

    Returns:
        (icp_classification, business_model_label, service_score, audit_reason)
    """
    headings = headings or []
    cat_norm = raw_category.lower().strip()
    evidence_blob = f"{company_name} {title} {description} {' '.join(headings)} {website_evidence} {raw_category}".lower()
    target_norm = (target_industry or "").lower().strip()

    # Determine targeted domain
    is_targeting_web = not target_norm or any(kw in target_norm for kw in ("web", "digital", "agency", "software", "marketing", "seo", "design"))
    is_targeting_contractors = bool(target_norm) and any(kw in target_norm for kw in ("contractor", "hvac", "roofing", "plumb", "electric", "trade"))
    is_targeting_restaurants = bool(target_norm) and any(kw in target_norm for kw in ("restaurant", "coffee", "cafe", "food", "dining", "hospitality"))
    is_targeting_gyms = bool(target_norm) and any(kw in target_norm for kw in ("gym", "fitness", "wellness", "workout", "crossfit", "yoga"))

    # -------------------------------------------------------------------------
    # 1. NON-COMMERCIAL / INSTITUTIONAL OVERRIDE (CHURCHES, SCHOOLS, PARKS)
    # -------------------------------------------------------------------------
    is_inst_keyword = any(
        w in evidence_blob for w in ("church", "baptist", "ministry", "worship", "pastor", "sermon", "congregation", "chapel", "parish", "cemetery")
    )
    if is_inst_keyword or cat_norm in INSTITUTIONAL_NON_COMMERCIAL_CATEGORIES:
        return (
            "Other Industry",
            "Non-Commercial Public / Religious Facility",
            0,
            f"Disqualified: Entity '{company_name}' is a non-commercial public / institutional facility (Classification: Other Industry - Non-Commercial Facility).",
        )

    # -------------------------------------------------------------------------
    # 2. JOB TARGET: RESTAURANTS & HOSPITALITY
    # -------------------------------------------------------------------------
    if is_targeting_restaurants:
        if any(k in evidence_blob for k in ("coffee", "cafe", "restaurant", "dining", "bistro", "bakery", "food", "bar", "grill")):
            return (
                "Exact ICP Match",
                "Restaurant & Food Service Facility",
                35,
                f"High industry match: {target_industry or 'Restaurants & Coffee Shops'} (Classification: Exact ICP Match - Restaurant & food service facility).",
            )
        else:
            return (
                "Other Industry",
                "Non-Hospitality Commercial Entity",
                0,
                f"Disqualified: Business category '{raw_category}' does not match target vertical '{target_industry}' (Classification: Other Industry).",
            )

    # -------------------------------------------------------------------------
    # 3. JOB TARGET: GYMS & FITNESS
    # -------------------------------------------------------------------------
    if is_targeting_gyms:
        if any(k in evidence_blob for k in ("gym", "fitness", "workout", "crossfit", "athletics", "training", "yoga")):
            return (
                "Exact ICP Match",
                "Fitness Club & Gym Facility",
                35,
                f"High industry match: {target_industry or 'Gyms & Fitness Centers'} (Classification: Exact ICP Match - Fitness club & gym facility).",
            )
        else:
            return (
                "Other Industry",
                "Non-Fitness Commercial Entity",
                0,
                f"Disqualified: Business category '{raw_category}' does not match target vertical '{target_industry}' (Classification: Other Industry).",
            )

    # -------------------------------------------------------------------------
    # 4. JOB TARGET: CONTRACTORS & TRADES
    # -------------------------------------------------------------------------
    if is_targeting_contractors:
        if any(k in evidence_blob for k in ("contractor", "hvac", "air conditioning", "plumbing", "roofing", "electrician", "duct")):
            return (
                "Exact ICP Match",
                "Commercial Trades & Contracting Service",
                35,
                f"High industry match: {target_industry or 'Commercial Contractors & HVAC'} (Classification: Exact ICP Match - Commercial trades & contracting service).",
            )
        else:
            return (
                "Other Industry",
                "Non-Contracting Business",
                0,
                f"Disqualified: Business category '{raw_category}' does not match target vertical '{target_industry}' (Classification: Other Industry).",
            )

    # -------------------------------------------------------------------------
    # 5. JOB TARGET: WEB DEVELOPMENT & DIGITAL AGENCIES (AND GENERAL B2B)
    # -------------------------------------------------------------------------
    # 5A. Disqualify physical/unrelated operations regardless of Overture labels
    # - Physical Records & Media Storage / Shredding (Safesite)
    if any(k in evidence_blob for k in ("records storage", "off-site records", "media storage", "document shredding", "climate controlled facilities", "storage & shredding", "secure records storage")):
        return (
            "Other Industry",
            "Physical Records Storage & Shredding Facility",
            0,
            "Disqualified: Business is a physical records storage and shredding facility rather than a digital web agency (Classification: Other Industry - Physical records storage and shredding facility).",
        )

    # - Surgical, Medical & Dental Equipment (Q-optics)
    if any(k in evidence_blob for k in ("surgical loupes", "dental loupes", "ergonomic loupes", "headlights", "optics manufacturer", "custom magnification")):
        return (
            "Other Industry",
            "Medical & Dental Surgical Equipment Manufacturer",
            0,
            "Disqualified: Business is a medical and dental surgical equipment manufacturer rather than a digital web agency (Classification: Other Industry - Medical equipment manufacturer).",
        )

    # - Automotive, Used Cars, Rental & Glass Repair (Any Cars, Weber Glass)
    if any(k in evidence_blob for k in ("used cars", "dealership", "car sales", "vehicle sales", "rent a car", "windshield repair", "auto glass", "any cars", "anycar", "exotic vehicle", "luxury vehicle", "vehicle specialist")):
        if not any(k in evidence_blob for k in ("fleet service", "commercial tire", "bestdrive", "conlan")):
            return (
                "Other Industry",
                "Automotive Sales & Vehicle Services",
                0,
                "Disqualified: Business is an automotive sales, rental, or repair facility (Classification: Other Industry - Automotive Sales & Vehicle Services).",
            )

    # - Preschools & Childcare
    if any(k in evidence_blob for k in ("preschool", "childcare", "daycare", "infants", "toddlers", "early childhood", "child development", "elementary_school", "school")):
        return (
            "Other Industry",
            "Preschool & Child Development Center",
            0,
            "Disqualified: Business is a preschool, school, or childcare facility (Classification: Other Industry - Preschool & Childcare).",
        )

    # - T-Shirt Printing & Custom Apparel
    if cat_norm == "t_shirt_printing_service" or any(k in evidence_blob for k in ("t-shirt printing", "screen printing", "embroidery", "custom apparel", "promotional products")):
        return (
            "Other Industry",
            "Commercial Screen Printing & Apparel Store",
            0,
            "Disqualified: Business is a commercial screen printing and merchandise shop (Classification: Other Industry - Apparel & Screen Printing).",
        )

    # - Tax Prep & Mortgage Brokers
    if any(k in evidence_blob for k in ("tax preparation", "tax prep", "tax return", "magic tax", "tax fs", "mortgage", "mortgage broker", "home loans", "loan officer")):
        return (
            "Other Industry",
            "Tax Preparation & Mortgage Services",
            0,
            "Disqualified: Business is a tax filing or mortgage brokerage operation (Classification: Other Industry - Tax Prep & Mortgage).",
        )

    # - Defunct / Inactive Businesses
    if any(k in evidence_blob for k in ("no longer in operation", "no longer in active operation", "permanently closed")):
        return (
            "Other Industry",
            "Defunct / Closed Commercial Entity",
            0,
            "Disqualified: Official website indicates business is no longer in operation (Classification: Other Industry - Defunct Operation).",
        )

    # - Real Estate Agents & Property Development
    if any(k in evidence_blob for k in ("realtor", "real estate agent", "property management", "commercial leasing", "real estate development")) and not any(w in evidence_blob for w in ("web development", "software development", "digital agency")):
        return (
            "Other Industry",
            "Real Estate Investment & Property Development",
            0,
            "Disqualified: Business is a real estate brokerage or property development firm (Classification: Other Industry - Real Estate).",
        )

    # - Civic, Social & Community Organizations
    if cat_norm in ("social_or_community_service", "civic_organization") or any(k in evidence_blob for k in ("community development foundation", "civic organization", "food pantry")):
        return (
            "Other Industry",
            "Civic & Community Nonprofit Organization",
            0,
            "Disqualified: Entity is a community nonprofit or civic foundation (Classification: Other Industry - Civic Organization).",
        )

    # - Restaurant Franchise Operators & Coffee Shops & Convenience Stores
    if any(k in evidence_blob for k in ("coffee", "cafe", "restaurant", "pizza hut", "denny's", "convenience store", "convenience_store")):
        target_clause = f"does not align with target vertical '{target_industry}'" if target_industry else "excluded from B2B outreach"
        return (
            "Other Industry",
            "Consumer Retail / Food Service Operation",
            0,
            f"Disqualified: Business category '{raw_category}' {target_clause} (Classification: Other Industry - Consumer Retail / Food Service Operation).",
        )

    # - Trades / Contractors when targeting Web Agencies
    if bool(target_industry) and any(k in evidence_blob for k in ("hvac", "roofing", "plumbing", "air conditioning", "duct cleaning")):
        return (
            "Other Industry",
            "Commercial Contracting & Trades Service",
            0,
            f"Disqualified: Business category '{raw_category}' does not align with target vertical '{target_industry}' (Classification: Other Industry - Commercial Contracting & Trades Service).",
        )

    # Disqualify general B2C when target is None (B2B default mode)
    if not target_industry:
        b2c_categories = {
            "coffee_shop", "convenience_store", "restaurant", "cafe", "fast_food_restaurant",
            "bar", "gas_station", "grocery_store", "supermarket", "clothing_store",
            "shoe_store", "beauty_salon", "hair_salon", "nail_salon", "laundromat",
            "dry_cleaner", "pharmacy", "movie_theater", "bowling_alley", "dentist",
        }
        if cat_norm in b2c_categories:
            return (
                "Other Industry",
                "Consumer Retail / Food Service Operation",
                0,
                f"Disqualified: Consumer retail category '{raw_category}' excluded from B2B outreach (Classification: Other Industry - Consumer Retail).",
            )

    # 5B. SaaS & Proprietary Software Products (SpendRule, Freshtech CRM)
    is_saas_product = any(k in evidence_blob for k in (
        "contract intelligence", "saas platform", "software platform", "ai-powered platform",
        "crm platform", "crm software", "turn complex contracts into enforceable controls",
        "raises $", "techcrunch", "book a demo", "request demo", "terminal operating system",
        "health tech platform", "healthcare analytics", "platform that", "subscription pricing",
    ))
    if is_saas_product and not any(k in evidence_blob for k in ("web design agency", "digital marketing agency", "our agency")):
        product_label = "Healthcare Contract Intelligence SaaS Platform" if "contract" in evidence_blob else "Proprietary Software Product / SaaS Platform"
        return (
            "SaaS / Product Company",
            product_label,
            5,
            f"Alternative business model: Proprietary software product ({product_label}) rather than a client-service web development agency (Classification: SaaS / Product Company - Proprietary software product).",
        )

    # 5C. Exact ICP Match: Client-Service Web & Digital Agencies
    is_agency_exact = any(k in evidence_blob for k in (
        "web design", "web development", "website design", "custom website", "web design agency",
        "digital agency", "ux design", "ui/ux", "creative agency", "branding and web",
        "wordpress development", "webflow agency", "digital marketing agency", "seo agency",
        "web design studio", "custom web application agency", "digital experience agency",
    )) or (
        cat_norm in ("web_designer", "advertising_agency", "marketing_agency")
    ) or (
        "web" in cat_norm and "design" in cat_norm
    )

    if is_agency_exact:
        return (
            "Exact ICP Match",
            "Client-Service Web & Digital Agency",
            35,
            f"High industry match: {target_industry or 'Web Development Agencies'} (Classification: Exact ICP Match - Client-service web design, custom development, and digital marketing agency).",
        )

    # 5D. Adjacent Partner: IT Consulting & Enterprise Digital Transformation
    is_adjacent_it = any(k in evidence_blob for k in (
        "digital transformation", "salesforce partner", "it consulting", "technology consulting",
        "enterprise integration", "systems integration", "managed it services", "cloud migration",
        "custom software solutions", "it solutions", "omnichannel commerce", "qa & performance testing",
    )) or (
        cat_norm in ("software_development", "it_service_and_computer_repair", "business_consulting")
        and any(w in evidence_blob for w in ("consulting", "solutions", "enterprise", "integration", "systems", "partner"))
    )

    if is_adjacent_it:
        adj_label = "Salesforce & Enterprise Digital Transformation Consultancy" if "salesforce" in evidence_blob else "IT Solutions & Enterprise Systems Consultancy"
        return (
            "Adjacent Partner",
            adj_label,
            20,
            f"Adjacent industry match: {adj_label} (Classification: Adjacent Partner - Operating adjacent to web design agency profile).",
        )

    # 5E. Default B2B Commercial Vertical (e.g. Continental BestDrive fleet services when target is None)
    if not target_industry and any(k in evidence_blob for k in ("commercial", "tire dealer", "tire_dealer", "bestdrive", "conlan", "automotive repair", "b2b", "fleet", "contractor", "hvac")):
        return (
            "Adjacent Partner",
            "Commercial Fleet & B2B Services",
            20,
            "High industry match: Commercial Fleet & B2B Services (Classification: Adjacent Partner - Commercial business vertical operating in target state).",
        )

    # 5F. Unreachable websites / Parked domains
    is_unreachable = bool(website_evidence) and any(marker in website_evidence.lower() for marker in ("[website unreachable", "connection timeout", "dns failure", "failed to fetch"))
    if is_unreachable:
        return (
            "Needs Manual Review",
            "Unverified Online Presence",
            10,
            "Classification: Needs Manual Review - Official website unreachable, parked, or provides insufficient business service documentation.",
        )

    # 5G. Ambiguous Technology / Services (Needs Manual Review)
    if any(k in evidence_blob for k in ("software", "digital", "technology", "consulting", "solutions")):
        return (
            "Needs Manual Review",
            "Unconfirmed Technology Service Provider",
            12,
            "Classification: Needs Manual Review - Technology entity with ambiguous business model evidence.",
        )

    return (
        "Other Industry",
        "Unclassified Commercial Operation",
        0,
        f"Disqualified: Business category '{raw_category}' and website text show no alignment with target vertical (Classification: Other Industry).",
    )


def calculate_icp_score(
    company: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    target_city: Optional[str] = "Austin",
    target_state: Optional[str] = "Texas",
    target_country: Optional[str] = "United States",
    target_industry: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """Compute an explainable 0-100 ICP score and audit reasons based on verified website evidence."""
    score = 0
    reasons: List[str] = []

    raw_category = (company.get("category") or "").strip().lower()
    raw_desc = (company.get("description") or "").strip()
    website = (company.get("website") or "").strip()
    domain = (company.get("domain") or "").strip()
    title = (company.get("title") or "").strip()
    website_evidence = (company.get("website_evidence") or "").strip()
    headings = company.get("headings") or []

    # -------------------------------------------------------------------------
    # 0. VERIFY ACTUAL BUSINESS SERVICES & BUSINESS MODEL CLASSIFICATION
    # -------------------------------------------------------------------------
    icp_class, model_label, service_pts, class_reason = classify_business_service(
        company_name=company.get("name") or "",
        website=website,
        domain=domain,
        raw_category=raw_category,
        title=title,
        description=raw_desc,
        website_evidence=website_evidence,
        headings=headings,
        target_industry=target_industry,
    )

    # Attach classification to company dict for caller persistence
    company["icp_classification"] = icp_class
    company["business_model_label"] = model_label
    reasons.append(class_reason)

    if icp_class == "Other Industry":
        # Hard stop for completely unrelated businesses
        return 0, reasons

    score += service_pts

    # -------------------------------------------------------------------------
    # 1. GEOGRAPHIC RELEVANCE (Up to 25 pts)
    # -------------------------------------------------------------------------
    c_city = (company.get("city") or "").lower()
    c_state = (company.get("state") or "").lower()
    c_country = (company.get("country") or "").lower()

    target_city_norm = (target_city or "").strip().lower()
    target_state_norm = (target_state or "texas").strip().lower()

    if target_city_norm and target_city_norm in c_city:
        score += 25
        reasons.append(f"Exact geographic match: Located directly in {target_city.capitalize()}")
    elif target_state_norm in c_state or "tx" in c_state:
        score += 15
        reasons.append(f"Regional match: Located within target state ({target_state or 'Texas'})")
    elif "united states" in c_country or "usa" in c_country:
        score += 10
        reasons.append("National match: Located within United States")
    else:
        reasons.append("Geographic caveat: Outside target metropolitan market")

    # -------------------------------------------------------------------------
    # 2. VERIFIED REACHABLE BUSINESS EMAIL & DOMAIN RELATIONSHIP (Up to 25 pts)
    # -------------------------------------------------------------------------
    has_decision_maker_email = False
    has_department_email = False
    has_unverified_email = False
    best_email = None

    for c in contacts:
        em = c.get("email")
        st = (c.get("email_verification_status") or c.get("deliverability_status") or c.get("status") or "").lower()
        role = (c.get("role") or "").lower()
        prov_email = c.get("field_provenance", {}).get("email", {})
        rel = prov_email.get("relationship", "direct_domain_match")

        if em and st in ("valid", "domain_validated", "verified"):
            if rel == "third_party_vendor_platform":
                continue

            best_email = em
            if any(t in role for t in ("founder", "ceo", "president", "director", "partner", "owner", "executive", "creative director")):
                has_decision_maker_email = True
                break
            else:
                has_department_email = True
        elif em:
            has_unverified_email = True

    if has_decision_maker_email:
        score += 25
        reasons.append(f"Decision maker identified: Verified executive business email ({best_email})")
    elif has_department_email:
        score += 18
        reasons.append(f"Active outreach readiness: Direct departmental business email verified ({best_email})")
    elif has_unverified_email or any(c.get("email") for c in contacts):
        score += 8
        reasons.append("Contact reachable: Public business email extracted (requires delivery verification)")
    else:
        reasons.append("Missing email: No verified direct business email published on official website")

    # -------------------------------------------------------------------------
    # 3. VERIFIED DIGITAL FOOTPRINT & DIRECT COMMERCIAL PHONE (Up to 15 pts)
    # -------------------------------------------------------------------------
    has_phone = bool(company.get("phone"))
    has_website = bool(company.get("website"))
    domain_val = (company.get("domain") or "").lower()

    is_shared_platform = any(
        sp in domain_val for sp in ("linktr.ee", "wordpress.com", "hub.biz", "facebook.com", "moneygram.com")
    )

    if has_website and has_phone and not is_shared_platform:
        score += 15
        reasons.append("Verified commercial presence: Dedicated company domain and direct commercial phone")
    elif has_website and not is_shared_platform:
        score += 8
        reasons.append("Active web presence: Dedicated corporate website verified")
    elif is_shared_platform:
        score += 3
        reasons.append("Third-party hosted profile: Business website hosted on shared platform / portal")

    final_score = min(100, max(0, score))
    return final_score, reasons
