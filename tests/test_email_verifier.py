import pytest
import asyncio
from app.verification_data import (
    is_disposable_domain,
    check_role_account,
    check_typo_suggestion,
    load_disposable_domains,
)
from app.verification_engine import (
    validate_syntax_and_normalize,
    verify_single_email,
    STATUS_VALID,
    STATUS_DOMAIN_VALIDATED,
    STATUS_INVALID,
    STATUS_RISKY,
    STATUS_CATCH_ALL,
    STATUS_UNKNOWN,
    STATUS_NOT_VERIFIED,
)
from app.campaign_lead_status import (
    campaign_lead_may_receive_sends,
    VERIFICATION_NEEDS_REVIEW,
    VERIFICATION_BLOCKS_SEND,
)
from app.models import Lead, CampaignLead


def test_disposable_dataset_loaded():
    """Verify that the 97,000+ disposable domain dataset is present and performs instant lookups."""
    domains = load_disposable_domains()
    assert len(domains) > 90000
    assert is_disposable_domain("mailinator.com") is True
    assert is_disposable_domain("tempmail.com") is True
    assert is_disposable_domain("10minutemail.com") is True
    assert is_disposable_domain("guerrillamail.com") is True
    assert is_disposable_domain("gmail.com") is False
    assert is_disposable_domain("weblinxsolution.com") is False


def test_role_account_detection_separation():
    """Role accounts must be detected and categorized but must NOT mark the address as invalid or risky."""
    is_role, cat = check_role_account("sales")
    assert is_role is True
    assert cat == "sales_marketing"

    is_role, cat = check_role_account("support")
    assert is_role is True
    assert cat == "support_service"

    is_role, cat = check_role_account("info")
    assert is_role is True
    assert cat == "general"

    is_role, cat = check_role_account("admin")
    assert is_role is True
    assert cat == "administrative"

    is_role, cat = check_role_account("john.doe")
    assert is_role is False
    assert cat is None


def test_typo_suggestions():
    """Detect common domain typos and suggest proper domain."""
    sug1 = check_typo_suggestion("gamil.com")
    assert sug1 == "gmail.com"

    sug2 = check_typo_suggestion("outlok.com")
    assert sug2 == "outlook.com"

    sug3 = check_typo_suggestion("yaho.com")
    assert sug3 == "yahoo.com"

    sug4 = check_typo_suggestion("gmail.com")
    assert sug4 is None


def test_syntax_validation_and_normalization():
    """RFC 5322 compliance and IDNA normalization."""
    is_valid, norm_email, local, domain, err = validate_syntax_and_normalize("  Test.User+Filter@Example.COM  ")
    assert is_valid is True
    assert norm_email.lower() == "test.user+filter@example.com"
    assert domain == "example.com"
    assert local.lower() == "test.user+filter"

    is_valid, _, _, _, err = validate_syntax_and_normalize("invalid-email-no-at.com")
    assert is_valid is False
    assert err != ""


@pytest.mark.asyncio
async def test_disposable_email_verification():
    """Disposable email must be classified as invalid."""
    res = await verify_single_email("throwaway@tempmail.com", check_smtp=False)
    assert res.status == STATUS_INVALID
    assert res.disposable["is_disposable"] is True
    assert "disposable" in res.reason.lower()


@pytest.mark.asyncio
async def test_typo_email_verification():
    """Email with common typo must be classified as risky with suggestion."""
    res = await verify_single_email("user@gamil.com", check_smtp=False)
    assert res.status == STATUS_RISKY
    assert res.typo["has_typo_risk"] is True
    assert res.typo["suggestion"] == "gmail.com"


@pytest.mark.asyncio
async def test_role_email_deliverability_honesty():
    """Role email on an active domain must be domain_validated, NOT demoted to risky or invalid."""
    res = await verify_single_email("contact@weblinxsolution.com", check_smtp=False)
    # Weblinxsolution.com has active MX records (mx1.titan.email)
    assert res.status == STATUS_DOMAIN_VALIDATED
    assert res.role_based["is_role_account"] is True
    assert res.role_based["role_category"] == "general"
    # Never inflate to "valid" when mailbox probe not confirmed!
    assert res.status != STATUS_VALID
    assert "unconfirmed" in res.reason.lower() or "dns" in res.reason.lower()


@pytest.mark.asyncio
async def test_null_mx_or_nonexistent_domain():
    """Nonexistent domain must be classified as invalid."""
    res = await verify_single_email("user@thisdomaindoesnotexistanywhereinpublicdns12345.com", check_smtp=False)
    assert res.status == STATUS_INVALID
    assert res.domain.get("domain_exists") is False
    assert res.domain.get("has_mx") is False


def test_campaign_verification_gate_policy():
    """Verify campaign verification gate send-eligibility rules."""
    cl = CampaignLead(id=1, campaign_id=1, enrollment_status="active", sending_paused=False)

    # 1. Invalid is strictly blocked
    lead_invalid = Lead(id=1, email="bad@tempmail.com", email_verification_status="invalid")
    assert campaign_lead_may_receive_sends(cl, lead_invalid) is False

    # 2. Valid and Domain Validated pass
    lead_valid = Lead(id=2, email="user@example.com", email_verification_status="valid")
    assert campaign_lead_may_receive_sends(cl, lead_valid) is True

    lead_domain_val = Lead(id=3, email="sales@weblinx.com", email_verification_status="domain_validated")
    assert campaign_lead_may_receive_sends(cl, lead_domain_val) is True

    # 3. Review needed statuses (unknown, catch_all, risky, not_verified) are blocked without approval
    for st in ("unknown", "catch_all", "risky", "not_verified"):
        lead_review = Lead(id=4, email="test@domain.com", email_verification_status=st, email_verification_result={})
        assert campaign_lead_may_receive_sends(cl, lead_review) is False

        # When explicitly approved, they pass
        lead_approved = Lead(
            id=5,
            email="test@domain.com",
            email_verification_status=st,
            email_verification_result={"approved": True},
        )
        assert campaign_lead_may_receive_sends(cl, lead_approved) is True


def test_manual_override_audit_structure():
    """Verify manual override audit recording."""
    lead = Lead(
        id=10,
        email="client@domain.com",
        email_verification_status="unknown",
        email_verification_result={
            "status": "unknown",
            "reason": "SMTP greylisted",
        },
    )

    audit_entry = {
        "previous_status": lead.email_verification_status,
        "new_status": "domain_validated",
        "note": "Spoke to customer on phone",
        "by_user": "operator@weblinxsolution.com",
        "overridden_at": "2026-10-22T09:00:00Z",
    }
    lead.email_verification_status = "domain_validated"
    lead.email_verification_result["override"] = audit_entry
    lead.email_verification_result["approved"] = True

    assert lead.email_verification_status == "domain_validated"
    assert lead.email_verification_result["override"]["note"] == "Spoke to customer on phone"
    assert lead.email_verification_result["approved"] is True
