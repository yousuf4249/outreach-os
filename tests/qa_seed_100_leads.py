"""Seed 100 test prospects for testing 100+ prospect table scrolling and pagination."""

import asyncio
from app.database import AsyncSessionLocal
from app.models import Lead
from sqlalchemy import select, delete

TEST_PREFIX = "[QA-SCROLL-TEST]"

async def seed_leads(count=100):
    async with AsyncSessionLocal() as session:
        # Check if already present
        existing = (await session.execute(
            select(Lead).where(Lead.name.like(f"{TEST_PREFIX}%"))
        )).scalars().all()
        if len(existing) >= count:
            print(f"Already have {len(existing)} test leads.")
            return

        to_add = count - len(existing)
        print(f"Seeding {to_add} test leads with full columns...")
        stages = ["new", "contacted", "replied", "interested", "meeting_scheduled", "follow_up_scheduled"]
        cities = ["Austin", "Dallas", "New York", "San Francisco", "London", "Toronto"]
        industries = ["SaaS", "Healthcare", "Fintech", "E-commerce", "AI Automation"]

        new_leads = []
        for i in range(to_add):
            idx = len(existing) + i + 1
            l = Lead(
                email=f"qa_scroll_lead_{idx:03d}@example-qa.com",
                name=f"{TEST_PREFIX} Lead {idx:03d}",
                company=f"Company {idx:03d} Labs",
                phone=f"+1 (555) 010-{idx:04d}",
                website=f"https://company{idx:03d}.example.com",
                industry=industries[i % len(industries)],
                city=cities[i % len(cities)],
                country="United States" if i % 2 == 0 else "United Kingdom",
                lead_source="Outreach OS Inbound",
                pipeline_status=stages[i % len(stages)],
                email_verification_status="valid" if i % 3 == 0 else "domain_validated",
                notes=f"Test prospect record #{idx}",
                tags=["qa-test", f"batch-{(i // 20) + 1}"]
            )
            new_leads.append(l)

        session.add_all(new_leads)
        await session.commit()
        print(f"Successfully seeded {len(new_leads)} test leads.")

async def cleanup_leads():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(Lead).where(Lead.name.like(f"{TEST_PREFIX}%"))
        )
        await session.commit()
        print(f"Cleaned up {result.rowcount} test leads.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        asyncio.run(cleanup_leads())
    else:
        asyncio.run(seed_leads(100))
