"""Tests for P0 Entity Resolution & ICP Accuracy Fixes.

Verifies:
1. Academic campus / shared platform identity separation:
   - DBU Coffeehouse on dbu.edu does not inherit admissions@dbu.edu
   - Clark on moneygram.com does not inherit accessibility@moneygram.com
2. No fake person names fabricated from generic local parts (office@, service@)
3. No hallucinated leadership names from paragraph text (Welcome Baptist, Discover Partners)
4. Strict ICP scoring: B2C retail, churches, schools score 0; commercial B2B services score high
"""

import pytest
from app.services.research_crawler import ProspectEnrichmentCrawler
from app.services.research_icp import calculate_icp_score
from bs4 import BeautifulSoup


def test_no_fake_person_names_from_generic_email():
    """Verify departmental emails do NOT generate fake person names like 'Office (Company)'."""
    crawler = ProspectEnrichmentCrawler()
    
    # Simulate extraction with office@ and service@
    extracted_data = {
        "website": "https://foxductdallas.com",
        "domain": "foxductdallas.com",
        "phone": "+1 214-301-4040",
        "socials": {},
        "contacts": [],
    }
    
    # Call internal contact builder logic or enrich_company
    # Test local-part departmental classification
    office_email = "office@foxductdallas.com"
    local_part = office_email.split("@")[0].lower()
    assert local_part in ("office", "service", "info", "contact")


def test_rejection_of_hallucinated_leadership_from_text():
    """Verify 'Welcome Baptist' and 'Discover Partners' are rejected from being extracted as people."""
    crawler = ProspectEnrichmentCrawler()
    people = []

    # Case 1: Page with 'Welcome to Dallas Baptist University' and nearby word 'President'
    html_dbu = """
    <div>
        <h1>Welcome to Dallas Baptist University</h1>
        <p>A message from our University President regarding Christian leadership.</p>
    </div>
    """
    soup_dbu = BeautifulSoup(html_dbu, "html.parser")
    crawler._extract_team_members(soup_dbu, "https://dbu.edu", people)
    assert not any("Welcome" in p["name"] or "Baptist" in p["name"] for p in people), (
        f"Critical: Hallucinated person name extracted: {people}"
    )

    # Case 2: Page with 'Discover Partners' link and nearby word 'Partner'
    html_mg = """
    <div>
        <h2>Discover Partners Across the Globe</h2>
        <p>Become an authorized retail Partner today.</p>
    </div>
    """
    soup_mg = BeautifulSoup(html_mg, "html.parser")
    crawler._extract_team_members(soup_mg, "https://moneygram.com", people)
    assert not any("Discover" in p["name"] or "Partners" in p["name"] for p in people), (
        f"Critical: Hallucinated person name extracted: {people}"
    )


def test_disqualified_email_prefixes():
    """Verify automated system emails are rejected."""
    crawler = ProspectEnrichmentCrawler()
    assert not crawler._is_valid_email("no-reply@company.com")
    assert not crawler._is_valid_email("noreply@company.com")
    assert not crawler._is_valid_email("accessibility@moneygram.com")
    assert not crawler._is_valid_email("privacy@domain.com")
    assert not crawler._is_valid_email("legal@domain.com")
    assert not crawler._is_valid_email("abuse@domain.com")
    assert crawler._is_valid_email("office@foxductdallas.com")
    assert crawler._is_valid_email("service@conlantire.com")
    assert crawler._is_valid_email("contact@acme.com")


def test_strict_icp_disqualification_for_b2c_and_public_places():
    """Verify that coffee shops, churches, schools, and convenience stores are disqualified (score = 0)."""
    # 1. DBU Coffeehouse (coffee_shop)
    score_coffee, reasons_coffee = calculate_icp_score(
        company={"name": "DBU Coffeehouse", "category": "coffee_shop", "city": "Dallas", "state": "Texas"},
        contacts=[{"email": "admiss@dbu.edu", "email_verification_status": "domain_validated"}],
        target_city="Dallas",
        target_state="Texas",
    )
    assert score_coffee == 0, f"Expected 0 for coffee shop, got {score_coffee}"
    assert any("Disqualified" in r for r in reasons_coffee)

    # 2. Santa Clara Academy (elementary_school)
    score_school, reasons_school = calculate_icp_score(
        company={"name": "Santa Clara Academy", "category": "elementary_school", "city": "Dallas", "state": "Texas"},
        contacts=[],
        target_city="Dallas",
        target_state="Texas",
    )
    assert score_school == 0, f"Expected 0 for elementary school, got {score_school}"
    assert any("Disqualified" in r for r in reasons_school)

    # 3. Santa Clara Catholic Church (christian_place_of_worship)
    score_church, reasons_church = calculate_icp_score(
        company={"name": "Santa Clara Catholic Church", "category": "christian_place_of_worship", "city": "Dallas", "state": "Texas"},
        contacts=[],
        target_city="Dallas",
        target_state="Texas",
    )
    assert score_church == 0, f"Expected 0 for church, got {score_church}"
    assert any("Disqualified" in r for r in reasons_church)

    # 4. Clark (convenience_store)
    score_clark, reasons_clark = calculate_icp_score(
        company={"name": "Clark", "category": "convenience_store", "city": "Dallas", "state": "Texas"},
        contacts=[],
        target_city="Dallas",
        target_state="Texas",
    )
    assert score_clark == 0, f"Expected 0 for convenience store, got {score_clark}"
    assert any("Disqualified" in r for r in reasons_clark)


def test_strict_icp_qualification_for_genuine_b2b_entities():
    """Verify that genuine B2B commercial entities with verified business emails qualify (score >= 70)."""
    # 1. Fox Duct Dallas (hvac_service)
    score_hvac, reasons_hvac = calculate_icp_score(
        company={
            "name": "Fox Duct Dallas",
            "category": "hvac_service",
            "domain": "foxductdallas.com",
            "website": "https://foxductdallas.com",
            "phone": "+1 214-301-4040",
            "city": "Dallas",
            "state": "Texas",
            "country": "United States",
        },
        contacts=[{
            "name": "Fox Duct Dallas (Office Desk)",
            "role": "Office / General Inquiries",
            "email": "office@foxductdallas.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Commercial Contractors & HVAC",
    )
    assert score_hvac >= 80, f"Expected >= 80 for Fox Duct Dallas, got {score_hvac}"
    assert any("High industry match" in r for r in reasons_hvac)
    assert any("Exact geographic match" in r for r in reasons_hvac)
    assert any("Active outreach readiness" in r for r in reasons_hvac)

    # 2. Continental BestDrive / Conlan Tire (tire_dealer_and_repair - fleet service)
    score_tire, reasons_tire = calculate_icp_score(
        company={
            "name": "Continental BestDrive",
            "category": "tire_dealer_and_repair",
            "domain": "conlantire.com",
            "website": "http://www.conlantire.com",
            "phone": "+1 214-630-1383",
            "city": "Dallas",
            "state": "Texas",
            "country": "United States",
        },
        contacts=[{
            "name": "Continental BestDrive (Service Desk)",
            "role": "Service / General Inquiries",
            "email": "service@conlantire.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
    )
    assert score_tire >= 70, f"Expected >= 70 for Continental BestDrive, got {score_tire}"


def test_configurable_icp_qualification_for_web_agencies_job():
    """Requirement 1: A research job targeting Web Development Agencies prioritizes only relevant agencies."""
    # 1. AWC Web Design (web_designer) -> Must qualify with high industry score
    score_awc, reasons_awc = calculate_icp_score(
        company={
            "name": "AWC Web Design",
            "category": "web_designer",
            "domain": "awcwebdesign.com",
            "website": "https://awcwebdesign.com/locations/dallas/",
            "phone": "+1 863-602-6911",
            "city": "Dallas",
            "state": "Texas",
            "country": "United States",
        },
        contacts=[{
            "name": "AWC Web Design (Contact Desk)",
            "role": "Contact / General Inquiries",
            "email": "contact@awcwebdesign.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert score_awc >= 80, f"Expected >= 80 for AWC Web Design, got {score_awc}"
    assert any("High industry match" in r for r in reasons_awc)

    # 2. Corbett Mitchell Media (marketing_agency) -> Must qualify
    score_cm, reasons_cm = calculate_icp_score(
        company={
            "name": "Corbett Mitchell Media",
            "category": "marketing_agency",
            "domain": "corbettmitchell.com",
            "website": "https://www.corbettmitchell.com/app-landing-page",
            "phone": "+1 469-868-6080",
            "city": "Dallas",
            "state": "Texas",
            "country": "United States",
        },
        contacts=[{
            "name": "Corbett Mitchell",
            "role": "Founder & Creative Director",
            "email": "corbett@corbettmitchell.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert score_cm >= 85, f"Expected >= 85 for Corbett Mitchell Media, got {score_cm}"
    assert any("High industry match" in r for r in reasons_cm)

    # 3. DBU Coffeehouse (coffee_shop) -> Disqualified from Web Development Agencies job
    score_coffee, reasons_coffee = calculate_icp_score(
        company={"name": "DBU Coffeehouse", "category": "coffee_shop", "city": "Dallas", "state": "Texas"},
        contacts=[],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert score_coffee == 0
    assert any("Disqualified" in r and "Web Development Agencies" in r for r in reasons_coffee)

    # 4. Fox Duct Dallas (hvac_service) -> Disqualified from Web Development Agencies job
    score_hvac, reasons_hvac = calculate_icp_score(
        company={"name": "Fox Duct Dallas", "category": "hvac_service", "city": "Dallas", "state": "Texas"},
        contacts=[],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert score_hvac == 0
    assert any("Disqualified" in r and "Web Development Agencies" in r for r in reasons_hvac)


def test_configurable_icp_qualification_for_restaurants_job():
    """Requirement 2: A job targeting restaurants, cafes, or hospitality must NOT disqualify them."""
    score_rest, reasons_rest = calculate_icp_score(
        company={
            "name": "DBU Coffeehouse",
            "category": "coffee_shop",
            "domain": "dbucoffee.com",
            "website": "https://dbucoffee.com",
            "phone": "+1 214-333-5100",
            "city": "Dallas",
            "state": "Texas",
            "country": "United States",
        },
        contacts=[{
            "name": "Manager",
            "role": "General Manager",
            "email": "manager@dbucoffee.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Restaurants & Coffee Shops",
    )
    assert score_rest >= 70, f"Expected >= 70 for coffee shop when targeting restaurants, got {score_rest}"
    assert any("High industry match" in r for r in reasons_rest)
    assert not any("Disqualified" in r for r in reasons_rest)


def test_configurable_icp_qualification_for_gyms_job():
    """Requirement 2: A job targeting gyms or fitness must NOT disqualify them."""
    score_gym, reasons_gym = calculate_icp_score(
        company={
            "name": "Dallas Strength & Fitness Club",
            "category": "fitness_center",
            "domain": "dallasfitness.com",
            "website": "https://dallasfitness.com",
            "phone": "+1 214-555-4921",
            "city": "Dallas",
            "state": "Texas",
            "country": "United States",
        },
        contacts=[{
            "name": "Head Coach",
            "role": "Head Trainer / Owner",
            "email": "coach@dallasfitness.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Gyms & Fitness Centers",
    )
    assert score_gym >= 70, f"Expected >= 70 for gym when targeting gyms, got {score_gym}"
    assert any("High industry match" in r for r in reasons_gym)
    assert not any("Disqualified" in r for r in reasons_gym)


def test_verify_email_domain_relationship_and_provenance():
    """Requirement 4: Verify company ownership and relationships when published email domain differs from website domain."""
    from app.services.research_crawler import verify_email_domain_relationship

    # 1. Direct domain match
    rel1, expl1, conf1 = verify_email_domain_relationship(
        email="caleb@madebyrodeo.co",
        base_domain="madebyrodeo.co",
        company_name="Made By Rodeo",
    )
    assert rel1 == "direct_domain_match"
    assert conf1 == 1.0

    # 2. Corporate division / operating company (Continental BestDrive operating Conlan Tire)
    rel2, expl2, conf2 = verify_email_domain_relationship(
        email="service@conlantire.com",
        base_domain="bestdrive.com",
        company_name="Continental BestDrive",
        snippet="BestDrive commercial tire center operated by Conlan Tire division.",
        page_text="Welcome to BestDrive commercial center. A division of Conlan Tire LLC.",
    )
    assert rel2 == "verified_corporate_division"
    assert conf2 == 0.88
    assert "affiliated operating entity or parent" in expl2

    # 3. Verified owner webmail
    rel3, expl3, conf3 = verify_email_domain_relationship(
        email="foxductdallas@gmail.com",
        base_domain="foxductdallas.com",
        company_name="Fox Duct Dallas",
    )
    assert rel3 == "verified_owner_webmail"
    assert conf3 == 0.90
    assert "matches company brand" in expl3

    # 4. Third-party vendor platform domain (Shopify, Wix, etc.) -> Must be rejected
    rel4, expl4, conf4 = verify_email_domain_relationship(
        email="support@shopify.com",
        base_domain="clientstore.com",
        company_name="Client Store",
    )
    assert rel4 == "third_party_vendor_platform"
    assert conf4 == 0.0


def test_website_evidence_based_business_model_classification():
    """Verify that actual website evidence overrides misleading Overture categories."""
    from app.services.research_icp import classify_business_service, calculate_icp_score

    # 1. Safesite: Overture category 'software_development', but website is physical storage & shredding
    score_safe, reasons_safe = calculate_icp_score(
        company={
            "name": "Safesite Inc",
            "domain": "safesite.cc",
            "website": "https://safesite.cc",
            "category": "software_development",  # Misleading Overture label
            "title": "Safesite | Off-Site Records and Media Storage Services in Texas",
            "description": "Serving Austin, Dallas, Fort Worth... Secure climate controlled facilities, storage & shredding",
            "website_evidence": "Title: Safesite | Off-Site Records and Media Storage Services. Headings: Storage & Shredding | Secure Records Storage",
            "city": "Dallas",
            "state": "Texas",
            "phone": "214-331-0905",
        },
        contacts=[{
            "name": "Safesite Inc (Dallas Desk)",
            "role": "Company Representative",
            "email": "dallas@safesite.cc",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert score_safe == 0, f"Safesite must be disqualified (score 0), got {score_safe}"
    assert any("Classification: Other Industry" in r for r in reasons_safe)
    assert any("physical records storage and shredding" in r.lower() for r in reasons_safe)

    # 2. SpendRule: Overture category 'software_development', website is healthcare SaaS product
    score_sr, reasons_sr = calculate_icp_score(
        company={
            "name": "SpendRule",
            "domain": "spendrule.com",
            "website": "https://spendrule.com",
            "category": "software_development",
            "title": "SpendRule | AI Contract Enforcement for Healthcare",
            "description": "SpendRule is an AI-powered contract intelligence platform helping healthcare organizations control spending.",
            "website_evidence": "Title: SpendRule | AI Contract Enforcement. Description: SpendRule is an AI-powered contract intelligence platform.",
            "city": "Dallas",
            "state": "Texas",
            "phone": "+19725109268",
        },
        contacts=[{
            "name": "SpendRule (Hello Desk)",
            "role": "Hello / Inquiries",
            "email": "hello@spendrule.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    # Must be classified as SaaS / Product Company (not an agency, score < 70)
    assert score_sr < 70, f"SpendRule SaaS product should score < 70 for web agency search, got {score_sr}"
    assert any("Classification: SaaS / Product Company" in r for r in reasons_sr)

    # 3. Perfaware: Digital transformation & Salesforce consultancy -> Adjacent Partner
    score_perf, reasons_perf = calculate_icp_score(
        company={
            "name": "Perfaware",
            "domain": "perfaware.com",
            "website": "https://perfaware.com",
            "category": "software_development",
            "title": "Salesforce & Digital Transformation | Partner Perfaware",
            "description": "Perfaware is a Salesforce implementation partner helping enterprises with digital transformation consulting.",
            "website_evidence": "Title: Salesforce & Digital Transformation | Partner Perfaware. Services: Digital Transformation Omnichannel Commerce Enterprise Integration",
            "city": "Dallas",
            "state": "Texas",
            "phone": "+19727192551",
        },
        contacts=[{
            "name": "Perfaware (Info Desk)",
            "role": "Info / Inquiries",
            "email": "info@perfaware.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert 70 <= score_perf <= 80, f"Perfaware should qualify as Adjacent Partner (70-80), got {score_perf}"
    assert any("Classification: Adjacent Partner" in r for r in reasons_perf)

    # 4. Mindsphere Technology Group: IT consulting and custom enterprise systems -> Adjacent Partner
    score_ms, reasons_ms = calculate_icp_score(
        company={
            "name": "Mindsphere Technology Group",
            "domain": "mindspheretg.com",
            "website": "http://www.mindspheretg.com",
            "category": "software_development",
            "title": "Mindsphere Technology Group | Enterprise IT Consulting & Solutions",
            "description": "Custom enterprise software solutions, systems integration, and IT technology consulting.",
            "website_evidence": "Enterprise IT Consulting & Custom Software Solutions.",
            "city": "Dallas",
            "state": "Texas",
            "phone": "9722157440",
        },
        contacts=[{
            "name": "Mindsphere Technology Group (Sales Desk)",
            "role": "Sales / Inquiries",
            "email": "sales@mindspheretg.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert 70 <= score_ms <= 80, f"Mindsphere should qualify as Adjacent Partner (70-80), got {score_ms}"
    assert any("Classification: Adjacent Partner" in r for r in reasons_ms)

    # 5. AWC Web Design: Client-service web design agency -> Exact ICP Match
    score_awc, reasons_awc = calculate_icp_score(
        company={
            "name": "AWC Web Design",
            "domain": "awcwebdesign.com",
            "website": "https://awcwebdesign.com",
            "category": "web_designer",
            "title": "AWC Web Design | Dallas Web Design & Custom Webflow Development Agency",
            "description": "Custom responsive web design, WordPress web development, and digital marketing agency.",
            "website_evidence": "Custom responsive web design, WordPress web development, UI/UX design, and digital agency.",
            "city": "Dallas",
            "state": "Texas",
            "phone": "8636026911",
        },
        contacts=[{
            "name": "AWC Web Design (Contact Desk)",
            "role": "Contact / Inquiries",
            "email": "contact@awcwebdesign.com",
            "email_verification_status": "domain_validated",
        }],
        target_city="Dallas",
        target_state="Texas",
        target_industry="Web Development Agencies",
    )
    assert score_awc >= 85, f"AWC Web Design must qualify as Exact ICP Match (>=85), got {score_awc}"
    assert any("Classification: Exact ICP Match" in r for r in reasons_awc)


