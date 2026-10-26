import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import AsyncSessionLocal
from app.models import Campaign, Inbox, CampaignInbox, QueueSlot, EmailLog, CampaignLead, SmtpAccount, Lead
from sqlalchemy import select, func

async def diag():
    async with AsyncSessionLocal() as s:
        print('=== 1. CAMPAIGN ===')
        res = await s.execute(select(Campaign).where(Campaign.id == 1))
        camp = res.scalar_one_or_none()
        if camp:
            print(f"Campaign: id={camp.id}, name={camp.name}, paused={camp.paused}, tz={camp.timezone}, "
                  f"hours={camp.sending_hours_start}-{camp.sending_hours_end}, days={camp.sending_days}")

        print('\n=== 2. INBOXES & SMTP ACCOUNTS ===')
        res = await s.execute(select(Inbox))
        for ib in res.scalars().all():
            print(f"Inbox: id={ib.id}, email={ib.email}, provider={ib.provider}, paused={ib.paused}, max_per_day={ib.max_emails_per_day}, wait_min={ib.wait_minutes_between}")
            smtp_res = await s.execute(select(SmtpAccount).where(SmtpAccount.inbox_id == ib.id))
            smtp = smtp_res.scalar_one_or_none()
            if smtp:
                print(f"  SMTP: host={smtp.smtp_host}, port={smtp.smtp_port}, user={smtp.smtp_username}, tls={smtp.smtp_use_tls}, ssl={smtp.smtp_use_ssl}, test_ok={smtp.last_test_ok}, last_tested={smtp.last_tested_at}")

        print('\n=== 3. CAMPAIGN_INBOX LINKS ===')
        ci_res = await s.execute(select(CampaignInbox).where(CampaignInbox.campaign_id == 1))
        for ci in ci_res.scalars().all():
            print(f"CampaignInbox: campaign_id={ci.campaign_id}, inbox_id={ci.inbox_id}")

        print('\n=== 4. QUEUE SLOTS ===')
        qs_count = await s.execute(select(func.count(QueueSlot.id)))
        print('Total QueueSlots in DB:', qs_count.scalar())
        qs_res = await s.execute(select(QueueSlot).order_by(QueueSlot.scheduled_date.asc()).limit(20))
        for q in qs_res.scalars().all():
            print(f"Slot: id={q.id}, cl_id={q.campaign_lead_id}, inbox_id={q.inbox_id}, seq={q.sequence_index}, sched={q.scheduled_date}, pos={q.position_in_day}")

        print('\n=== 5. EMAIL LOGS ===')
        el_res = await s.execute(select(EmailLog).order_by(EmailLog.id.asc()))
        logs = el_res.scalars().all()
        print('Total EmailLogs in DB:', len(logs))
        for el in logs:
            from_em = getattr(el, 'from_email', None)
            stat = getattr(el, 'status', None)
            print(f"EmailLog: id={el.id}, camp={el.campaign_id}, lead={el.lead_id}, inbox={el.inbox_id}, from={from_em}, subj={el.subject}, sent_at={el.sent_at}, status={stat}")

        print('\n=== 6. CAMPAIGN_LEAD SUMMARY ===')
        cl_res = await s.execute(select(CampaignLead).where(CampaignLead.campaign_id == 1))
        cls = cl_res.scalars().all()
        print(f"Total CampaignLeads: {len(cls)}")
        for cl in cls[:5]:
            print(f"CL: id={cl.id}, lead_id={cl.lead_id}, status={cl.enrollment_status}, paused={cl.sending_paused}, failure={cl.failure_reason}, bounce_type={cl.bounce_type}")

        print('\n=== 7. TABLE INFO & EMAIL LOG DETAILS ===')
        from sqlalchemy import text
        res = await s.execute(text("PRAGMA table_info(email_log)"))
        print("EmailLog columns:", [(r[1], r[2]) for r in res.fetchall()])
        res3 = await s.execute(text("SELECT * FROM email_log"))
        for row in res3.fetchall():
            print("Full EmailLog row:", row)

        res_tables = await s.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        print("All tables:", [r[0] for r in res_tables.fetchall()])

if __name__ == '__main__':
    asyncio.run(diag())
