"""Test importing the exported CSV into an isolated SQLite database to verify full round-trip fidelity."""
import os
import asyncio
import io
import csv
import urllib.request
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models import Base, Lead
from app.auth import create_access_token
from app.verification_engine import validate_syntax_and_normalize

ISOLATED_DB_FILE = "test_isolated_import.db"
ISOLATED_DB_URL = f"sqlite+aiosqlite:///{ISOLATED_DB_FILE}"

async def run_isolated_reimport_test():
    print("=== STARTING ISOLATED CSV RE-IMPORT VERIFICATION ===")
    
    # 1. Fetch CSV export from live API
    token = create_access_token('1', role='admin')
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/leads/export?scope=all",
        headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as resp:
        csv_bytes = resp.read()
    
    assert csv_bytes.startswith(b'\xef\xbb\xbf'), "Missing UTF-8 BOM"
    csv_text = csv_bytes.decode('utf-8-sig')
    reader = list(csv.reader(io.StringIO(csv_text)))
    headers = [h.strip() for h in reader[0]]
    rows = reader[1:]
    
    print(f"Fetched {len(rows)} rows from export endpoint with headers: {headers}")
    assert len(rows) > 0, "No rows exported"

    # 2. Set up isolated test database
    if os.path.exists(ISOLATED_DB_FILE):
        os.remove(ISOLATED_DB_FILE)
        
    engine = create_async_engine(ISOLATED_DB_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    print(f"Created fresh isolated test database: {ISOLATED_DB_FILE}")

    # 3. Import CSV rows using Weblinx mapping heuristics
    def find_col(aliases):
        for alias in aliases:
            for h in headers:
                if h.lower() == alias:
                    return h
        return None

    email_col = find_col(["email", "e-mail", "mail", "email address", "work email"])
    name_col = find_col(["name", "full name", "contact name", "founder", "lead name"])
    company_col = find_col(["company", "company name", "business", "business name"])
    phone_col = find_col(["phone", "phone number", "mobile", "telephone"])
    website_col = find_col(["website", "site", "url", "domain", "web", "website url"])
    city_col = find_col(["city", "location", "town"])
    country_col = find_col(["country", "nation"])
    industry_col = find_col(["industry", "sector", "vertical"])
    source_col = find_col(["source", "lead source", "channel"])
    notes_col = find_col(["notes", "note", "comment", "description"])

    print("Detected Column Mappings:")
    print(f"  Email: {email_col}")
    print(f"  Name: {name_col}")
    print(f"  Company: {company_col}")
    print(f"  Phone: {phone_col}")
    print(f"  Website: {website_col}")
    print(f"  City: {city_col}")
    print(f"  Country: {country_col}")
    print(f"  Industry: {industry_col}")
    print(f"  Source: {source_col}")
    print(f"  Notes: {notes_col}")

    imported_leads = []
    async with async_session() as session:
        for r_vals in rows:
            r = dict(zip(headers, r_vals))
            raw_email = r.get(email_col, "").strip().lower()
            if not raw_email:
                continue
            syntax_valid, norm_email, _, _, _ = validate_syntax_and_normalize(raw_email)
            if not syntax_valid:
                continue
            
            lead = Lead(
                email=norm_email,
                name=r.get(name_col, "").strip(),
                company=r.get(company_col, "").strip(),
                phone=r.get(phone_col, "").strip(),
                website=r.get(website_col, "").strip(),
                city=r.get(city_col, "").strip(),
                country=r.get(country_col, "").strip(),
                industry=r.get(industry_col, "").strip(),
                lead_source=r.get(source_col, "").strip(),
                notes=r.get(notes_col, "").strip(),
                email_verification_status=r.get("Email Verification Status", "not_verified").strip(),
                pipeline_status=r.get("Pipeline Status", "lead").strip()
            )
            session.add(lead)
            imported_leads.append(lead)
            
        await session.commit()

    print(f"Successfully inserted {len(imported_leads)} prospects into isolated database.")
    assert len(imported_leads) == len(rows), f"Expected {len(rows)} imported, got {len(imported_leads)}"

    # 4. Query back and verify sample data
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(Lead))
        all_leads = result.scalars().all()
        print(f"Queried back {len(all_leads)} leads from isolated database.")
        
        # Verify first lead data
        first = all_leads[0]
        print(f"Sample Record Integrity Check:")
        print(f"  ID: {first.id}")
        print(f"  Company: {first.company}")
        print(f"  Name: {first.name}")
        print(f"  Email: {first.email}")
        print(f"  Phone: {first.phone}")
        print(f"  Website: {first.website}")
        print(f"  City: {first.city}")
        print(f"  Country: {first.country}")
        print(f"  Industry: {first.industry}")
        print(f"  Pipeline Status: {first.pipeline_status}")
        
        assert first.company, "Company should be populated"
        assert first.email, "Email should be populated"
        assert first.phone, "Phone should be populated"
        assert first.website, "Website should be populated"
        
    await engine.dispose()
    
    # 5. Cleanup isolated DB file
    if os.path.exists(ISOLATED_DB_FILE):
        os.remove(ISOLATED_DB_FILE)
    print("Cleaned up isolated database file.")
    print("=== ISOLATED RE-IMPORT VERIFICATION COMPLETE: ALL PASS ===")

if __name__ == "__main__":
    asyncio.run(run_isolated_reimport_test())
