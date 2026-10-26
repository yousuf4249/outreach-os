"""Seed realistic agency and business prospects into local_dev.db if count is 0."""
import asyncio
from datetime import datetime
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import Lead

PROSPECTS = [
    {
        "company": "Austin Growth Partners",
        "name": "Marcus Vance",
        "email": "marcus.vance@austingrowth.io",
        "phone": "+1 (512) 555-0101",
        "website": "https://austingrowth.io",
        "industry": "B2B SaaS Growth",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "interested",
        "email_verification_status": "valid",
        "tags": ["austin-agency", "high-growth", "enterprise"],
        "notes": "Met at Austin Tech Week. Looking to scale cold outbound for Q4.",
        "custom_data": {"state": "TX", "founded": "2021", "team_size": "25-50"}
    },
    {
        "company": "South Congress Creative",
        "name": "Elena Torres",
        "email": "elena.torres@sococreative.com",
        "phone": "+1 (512) 555-0102",
        "website": "https://sococreative.com",
        "industry": "E-Commerce Creative",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Inbound Referral",
        "pipeline_status": "meeting_scheduled",
        "email_verification_status": "valid",
        "tags": ["d2c", "creative-studio", "priority"],
        "notes": "Full-funnel branding and UGC agency on South Congress.",
        "custom_data": {"state": "TX", "founded": "2019", "team_size": "15-20"}
    },
    {
        "company": "Silicon Hills Cloud Labs",
        "name": "David Chen",
        "email": "david.chen@siliconhillscloud.dev",
        "phone": "+1 (512) 555-0103",
        "website": "https://siliconhillscloud.dev",
        "industry": "Cloud Architecture",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Partner Network",
        "pipeline_status": "replied",
        "email_verification_status": "valid",
        "tags": ["aws", "devops", "fintech"],
        "notes": "Specializes in AWS migration for Series A/B startups in Austin.",
        "custom_data": {"state": "TX", "founded": "2020", "team_size": "10-25"}
    },
    {
        "company": "Barton Springs Digital",
        "name": "Sarah Jenkins",
        "email": "sarah@bartonspringsdigital.com",
        "phone": "+1 (512) 555-0104",
        "website": "https://bartonspringsdigital.com",
        "industry": "SEO & Performance Marketing",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "contacted",
        "email_verification_status": "domain_validated",
        "tags": ["performance", "seo", "local-biz"],
        "notes": "Performance marketing consultancy managing $2M+ monthly ad spend.",
        "custom_data": {"state": "TX", "founded": "2018", "team_size": "30"}
    },
    {
        "company": "Lone Star Automation Group",
        "name": "Travis Walker",
        "email": "travis@lonestarauto.io",
        "phone": "+1 (512) 555-0105",
        "website": "https://lonestarauto.io",
        "industry": "AI & Robotic Automation",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "new",
        "email_verification_status": "valid",
        "tags": ["ai", "automation", "enterprise"],
        "notes": "Enterprise RPA and Zapier/Make consulting.",
        "custom_data": {"state": "TX", "founded": "2022", "team_size": "12"}
    },
    {
        "company": "Apex Peak Media",
        "name": "Claire Dupont",
        "email": "claire@apexpeakmedia.co",
        "phone": "+1 (415) 555-0191",
        "website": "https://apexpeakmedia.co",
        "industry": "Digital Media & PR",
        "city": "San Francisco",
        "country": "United States",
        "lead_source": "LinkedIn Outreach",
        "pipeline_status": "interested",
        "email_verification_status": "valid",
        "tags": ["pr", "b2b", "media"],
        "notes": "B2B tech PR boutique representing early-stage founders.",
        "custom_data": {"state": "CA", "founded": "2021", "team_size": "18"}
    },
    {
        "company": "Bluebonnet Venture Studio",
        "name": "Wyatt Harris",
        "email": "wyatt@bluebonnetvs.com",
        "phone": "+1 (512) 555-0106",
        "website": "https://bluebonnetvs.com",
        "industry": "Venture Capital & Studio",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Executive Referral",
        "pipeline_status": "follow_up_scheduled",
        "email_verification_status": "valid",
        "tags": ["venture", "incubator", "tier-1"],
        "notes": "Co-founding 3 tech startups per year. Looking for lead-gen partners.",
        "custom_data": {"state": "TX", "founded": "2017", "portfolio_count": "14"}
    },
    {
        "company": "Capital City Webworks",
        "name": "Rachel Kim",
        "email": "rachel@capcityweb.io",
        "phone": "+1 (512) 555-0107",
        "website": "https://capcityweb.io",
        "industry": "Custom Web Solutions",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "new",
        "email_verification_status": "domain_validated",
        "tags": ["web-dev", "shopify", "nextjs"],
        "notes": "React/Next.js and headless Shopify development studio.",
        "custom_data": {"state": "TX", "founded": "2023", "team_size": "8"}
    },
    {
        "company": "Red River Data Systems",
        "name": "Nathanial Brody",
        "email": "nbrody@redriverdata.com",
        "phone": "+1 (512) 555-0108",
        "website": "https://redriverdata.com",
        "industry": "Data Engineering & Analytics",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "contacted",
        "email_verification_status": "valid",
        "tags": ["snowflake", "databricks", "big-data"],
        "notes": "Specializes in Snowflake data pipelines for mid-market healthcare.",
        "custom_data": {"state": "TX", "founded": "2019", "team_size": "35"}
    },
    {
        "company": "Hill Country Design Studio",
        "name": "Maya Lin",
        "email": "maya@hillcountrydesign.co",
        "phone": "+1 (512) 555-0109",
        "website": "https://hillcountrydesign.co",
        "industry": "UI/UX & Product Design",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Dribbble Inbound",
        "pipeline_status": "meeting_scheduled",
        "email_verification_status": "valid",
        "tags": ["design", "product", "figma"],
        "notes": "Top-tier design agency with clients across Texas and California.",
        "custom_data": {"state": "TX", "founded": "2020", "team_size": "14"}
    },
    {
        "company": "Congress Avenue Legal Tech",
        "name": "James O'Connor",
        "email": "james@congresslegaltech.com",
        "phone": "+1 (512) 555-0110",
        "website": "https://congresslegaltech.com",
        "industry": "LegalTech",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "replied",
        "email_verification_status": "valid",
        "tags": ["legal", "saas", "contract-ai"],
        "notes": "Contract analysis software for law firms and corporate legal teams.",
        "custom_data": {"state": "TX", "founded": "2022", "team_size": "20"}
    },
    {
        "company": "Zilker Brand Experience",
        "name": "Chloe Bennett",
        "email": "chloe@zilkerbx.com",
        "phone": "+1 (512) 555-0111",
        "website": "https://zilkerbx.com",
        "industry": "Experiential Marketing",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "interested",
        "email_verification_status": "valid",
        "tags": ["experiential", "events", "sxsw"],
        "notes": "SXSW activation leaders. High budget corporate brand activations.",
        "custom_data": {"state": "TX", "founded": "2016", "team_size": "28"}
    },
    {
        "company": "East Austin Web Studio",
        "name": "Tyler Scott",
        "email": "tyler@eastaustinstudio.io",
        "phone": "+1 (512) 555-0112",
        "website": "https://eastaustinstudio.io",
        "industry": "Creative Agency",
        "city": "Austin",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "new",
        "email_verification_status": "risky",
        "tags": ["indie", "creative", "boutique"],
        "notes": "Catch-all mailbox detected on initial DNS check.",
        "custom_data": {"state": "TX", "founded": "2023", "team_size": "6"}
    },
    {
        "company": "Highland Park Advisors",
        "name": "Arthur Pendelton",
        "email": "arthur@highlandadvisors.net",
        "phone": "+1 (214) 555-0188",
        "website": "https://highlandadvisors.net",
        "industry": "M&A Advisory",
        "city": "Dallas",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "contacted",
        "email_verification_status": "valid",
        "tags": ["finance", "m-and-a", "dallas"],
        "notes": "Lower middle-market M&A advisory firm.",
        "custom_data": {"state": "TX", "founded": "2015", "team_size": "16"}
    },
    {
        "company": "Galveston Bay Logistics Tech",
        "name": "Captain Robert Sterling",
        "email": "robert@galvestonbaytech.com",
        "phone": "+1 (713) 555-0177",
        "website": "https://galvestonbaytech.com",
        "industry": "Supply Chain & Logistics",
        "city": "Houston",
        "country": "United States",
        "lead_source": "Cold Outreach",
        "pipeline_status": "new",
        "email_verification_status": "domain_validated",
        "tags": ["logistics", "iot", "houston"],
        "notes": "IoT tracking hardware for port containers and regional drayage.",
        "custom_data": {"state": "TX", "founded": "2020", "team_size": "42"}
    }
]

async def seed_realistic():
    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count(Lead.id)))
        if count > 0:
            print(f"Database already has {count} leads. Not overwriting.")
            return

        print(f"Seeding {len(PROSPECTS)} realistic business & agency prospects...")
        for p in PROSPECTS:
            lead = Lead(
                company=p["company"],
                name=p["name"],
                email=p["email"],
                phone=p["phone"],
                website=p["website"],
                industry=p["industry"],
                city=p["city"],
                country=p["country"],
                lead_source=p["lead_source"],
                pipeline_status=p["pipeline_status"],
                email_verification_status=p["email_verification_status"],
                tags=p["tags"],
                notes=p["notes"],
                custom_data=p["custom_data"],
                email_verification_result={
                    "status": p["email_verification_status"],
                    "confidence": "high",
                    "reason": "Verified via DNS and active mailbox check"
                }
            )
            session.add(lead)
        await session.commit()
        print(f"Successfully committed {len(PROSPECTS)} realistic prospects to local_dev.db!")

if __name__ == "__main__":
    asyncio.run(seed_realistic())
