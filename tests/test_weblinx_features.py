"""Comprehensive tests for Weblinx Outreach OS features."""
import pytest
import io
from fastapi import BackgroundTasks
from app.routers import leads as leads_router
from app.routers import templates as templates_router
from app.routers import suppression as suppression_router
from app.routers import analytics as analytics_router
from app.schemas import (
    LeadCreate,
    LeadUpdate,
    TemplateCreate,
    TemplateUpdate,
    SuppressionCreate,
    LeadBulkAssignCampaignRequest,
    LeadBulkPipelineStatusRequest,
)
from app.models import Lead, Campaign, CampaignLead, EmailLog, LeadReply, Inbox
from app.sender import render_body, get_lead_data, RenderContext
from app.routers.suppression import is_email_or_domain_suppressed
from tests.conftest import make_campaign, make_inbox, make_sequence, make_campaign_inbox, make_email_log


@pytest.mark.asyncio
async def test_sender_variable_substitution():
    """Verify that first_name, company_name, city, industry, etc. resolve correctly with fallbacks."""
    class MockLead:
        name = "Jordan Belfort"
        email = "jordan@stratton.com"
        company = "Stratton Oakmont"
        phone = "+1-555-0100"
        website = "https://stratton.com"
        industry = "Finance"
        city = "New York"
        country = "USA"
        lead_source = "Inbound"
        notes = "High value prospect"
        pipeline_status = "new"
        custom_data = {"custom_metric": "99%"}

    lead = MockLead()
    data = get_lead_data(lead)
    assert data["first_name"] == "Jordan"
    assert data["last_name"] == "Belfort"
    assert data["company_name"] == "Stratton Oakmont"
    assert data["city"] == "New York"
    assert data["custom_metric"] == "99%"

    # Test template rendering
    template = "Hi {{first_name}}, I saw {{company_name}} is leading {{industry}} in {{city}}. {{custom_metric}} growth! Missing: {{nonexistent | default_val}} and empty: {{unprovided}}"
    ctx = RenderContext()
    rendered = render_body(template, data, ctx)
    assert "Hi Jordan," in rendered
    assert "Stratton Oakmont" in rendered
    assert "Finance in New York" in rendered
    assert "99% growth!" in rendered
    assert "default_val" in rendered
    assert "empty: " in rendered


@pytest.mark.asyncio
async def test_direct_lead_creation_and_patch(session):
    """Verify creating a lead directly without requiring a campaign, and updating pipeline status."""
    bg = BackgroundTasks()
    lead_in = LeadCreate(
        email="sarah.connor@cyberdyne.com",
        name="Sarah Connor",
        company="Cyberdyne Systems",
        phone="+1-800-555-0199",
        website="https://cyberdyne.com",
        industry="Defense Tech",
        city="Los Angeles",
        country="USA",
        lead_source="Cold Outreach",
        notes="Key decision maker",
        pipeline_status="new",
        tags=["vip", "enterprise"],
        custom_data={"tier": "Tier 1"},
    )
    created = await leads_router.create_lead(lead_in, db=session)
    assert created.id is not None
    assert created.email == "sarah.connor@cyberdyne.com"
    assert created.name == "Sarah Connor"
    assert created.company == "Cyberdyne Systems"
    assert created.pipeline_status == "new"
    assert "vip" in created.tags

    # Patch lead pipeline status to meeting_scheduled
    patch_in = LeadUpdate(
        pipeline_status="meeting_scheduled",
        notes="Booked demo for Thursday",
    )
    updated = await leads_router.update_lead(created.id, patch_in, background_tasks=bg, db=session)
    assert updated.pipeline_status == "meeting_scheduled"
    assert updated.notes == "Booked demo for Thursday"


@pytest.mark.asyncio
async def test_templates_crud_and_preview(session):
    """Test Email Template creation, list, update, preview, duplicate, and delete."""
    # 1. Create
    tmpl_in = TemplateCreate(
        name="B2B SaaS Intro",
        subject="Quick question for {{first_name}} at {{company_name}}",
        body="Hi {{first_name}},\n\nNoticed {{company_name}} in {{city}}. Would love to connect regarding {{industry}} sales automation.\n\nBest,\nAlex",
        is_html=False,
        category="Cold Outreach",
    )
    tmpl = await templates_router.create_template(tmpl_in, db=session)
    assert tmpl.id is not None
    assert tmpl.name == "B2B SaaS Intro"

    # 2. Preview
    prev = await templates_router.preview_template(
        templates_router.TemplatePreviewRequest(
            subject=tmpl.subject,
            body=tmpl.body,
            sample_data={
                "first_name": "Elon",
                "company_name": "SpaceX",
                "city": "Hawthorne",
                "industry": "Aerospace",
            },
        )
    )
    assert prev["rendered_subject"] == "Quick question for Elon at SpaceX"
    assert "Noticed SpaceX in Hawthorne" in prev["rendered_body"]

    # 3. Duplicate
    dup = await templates_router.duplicate_template(tmpl.id, db=session)
    assert dup.name == "B2B SaaS Intro (Copy)"
    assert dup.id != tmpl.id

    # 4. List
    listed = await templates_router.list_templates(category=None, db=session)
    assert len(listed) >= 2

    # 5. Delete duplicate
    del_res = await templates_router.delete_template(dup.id, db=session)
    assert del_res["ok"] is True


@pytest.mark.asyncio
async def test_suppression_list_and_check(session):
    """Test adding email and domain suppressions and checking rejection."""
    # 1. Add email
    s1 = await suppression_router.add_suppression(
        SuppressionCreate(
            email_or_domain="do-not-email@competitor.com",
            reason="Competitor unsubscribe",
        ),
        db=session,
    )
    assert s1.id is not None

    # 2. Add domain
    s2 = await suppression_router.add_suppression(
        SuppressionCreate(
            email_or_domain="blockedcompany.com",
            reason="Company-wide opt-out",
        ),
        db=session,
    )
    assert s2.id is not None

    # 3. Check helper function
    assert await is_email_or_domain_suppressed(session, "do-not-email@competitor.com") is True
    assert await is_email_or_domain_suppressed(session, "employee@blockedcompany.com") is True
    assert await is_email_or_domain_suppressed(session, "valid@customer.com") is False


@pytest.mark.asyncio
async def test_bulk_campaign_and_status(session):
    """Test bulk assigning prospects to campaign and bulk pipeline status."""
    bg = BackgroundTasks()
    camp = await make_campaign(session, name="Weblinx Q4 Outreach")

    lead1 = await leads_router.create_lead(
        LeadCreate(email="l1@example.com", name="Lead One", company="Company 1"),
        db=session,
    )
    lead2 = await leads_router.create_lead(
        LeadCreate(email="l2@example.com", name="Lead Two", company="Company 2"),
        db=session,
    )

    # Bulk assign
    assign_res = await leads_router.bulk_assign_to_campaign(
        LeadBulkAssignCampaignRequest(lead_ids=[lead1.id, lead2.id], campaign_id=camp.id),
        background_tasks=bg,
        db=session,
    )
    assert assign_res["assigned"] == 2

    # Bulk status update
    status_res = await leads_router.bulk_update_pipeline_status(
        LeadBulkPipelineStatusRequest(lead_ids=[lead1.id, lead2.id], pipeline_status="contacted"),
        background_tasks=bg,
        db=session,
    )
    assert status_res["updated"] == 2


@pytest.mark.asyncio
async def test_dashboard_summary_real_metrics(session):
    """Verify central dashboard statistics are computed from real database rows."""
    camp = await make_campaign(session, name="Dashboard Camp")
    inbox = await make_inbox(session, email="sender@weblinxsolution.com")
    await make_campaign_inbox(session, camp.id, inbox.id)

    lead = await leads_router.create_lead(
        LeadCreate(email="prospect@target.com", name="Target Prospect", company="Target Inc", pipeline_status="meeting_scheduled"),
        db=session,
    )
    await make_email_log(session, lead_id=lead.id, campaign_id=camp.id, inbox_id=inbox.id)
    session.add(LeadReply(lead_id=lead.id, campaign_id=camp.id))
    await session.flush()

    data = await analytics_router.get_dashboard_summary(db=session)
    assert data["total_prospects"] >= 1
    assert data["total_inboxes"] >= 1
    assert data["active_campaigns"] >= 1
    assert data["emails_sent"] >= 1
    assert data["replies_received"] >= 1
    assert data["meetings_booked"] >= 1
    assert data["reply_rate"] > 0
    assert isinstance(data["recent_activity"], list)
    assert isinstance(data["campaign_performance"], list)
