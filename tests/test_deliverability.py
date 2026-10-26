"""Comprehensive automated tests for Email Deliverability & Domain Health Monitoring."""

import base64
from unittest.mock import MagicMock, patch
import pytest

from app.deliverability import (
    analyze_email_headers,
    check_dkim_record,
    check_dmarc_record,
    check_dnsbl_blocklists,
    check_mx_records,
    check_spf_record,
    extract_domain,
    get_google_postmaster_reputation,
    get_inbox_delivery_stats,
    run_domain_health_scan_for_inbox,
)
from app.models import DirectEmail, DomainHealthScan, EmailLog, Inbox, Lead, SmtpAccount
from tests.conftest import make_inbox


class MockDNSAnswer:
    def __init__(self, strings):
        self.strings = [s.encode("utf-8") if isinstance(s, str) else s for s in strings]


class MockMXAnswer:
    def __init__(self, preference, exchange_str):
        self.preference = preference
        self.exchange = MagicMock()
        self.exchange.to_text.return_value = exchange_str


def test_extract_domain():
    assert extract_domain("info@weblinxsolution.com") == "weblinxsolution.com"
    assert extract_domain("Yousaf <yousaf@weblinxsolution.com>") == "weblinxsolution.com"
    assert extract_domain("   user@sub.domain.co.uk   ") == "sub.domain.co.uk"
    assert extract_domain("invalid-no-at-sign") == ""
    assert extract_domain("") == ""


def test_check_spf_valid():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        def side_effect(qname, rtype):
            dom = str(qname)
            if dom == "example.com":
                return [MockDNSAnswer(["v=spf1 include:_spf.google.com ~all"])]
            elif dom == "_spf.google.com":
                return [MockDNSAnswer(["v=spf1 ip4:35.190.247.0/24 ~all"])]
            return []

        mock_resolve.side_effect = side_effect
        result = check_spf_record("example.com", provider="gmail")
        assert result["status"] == "healthy"
        assert result["lookup_count"] >= 1
        assert result["all_mechanism"] == "~all"
        assert len([i for i in result["issues"] if i["severity"] == "critical"]) == 0


def test_check_spf_recursive_evaluation():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        def side_effect(qname, rtype):
            dom = str(qname)
            if dom == "root.com":
                return [MockDNSAnswer(["v=spf1 include:child.com ~all"])]
            elif dom == "child.com":
                return [MockDNSAnswer(["v=spf1 include:leaf.com ip4:1.2.3.4 ~all"])]
            elif dom == "leaf.com":
                return [MockDNSAnswer(["v=spf1 ip4:5.6.7.8 -all"])]
            return []

        mock_resolve.side_effect = side_effect
        result = check_spf_record("root.com")
        assert result["status"] == "healthy"
        # root -> child (1), child -> leaf (1) = 2 lookups
        assert result["lookup_count"] == 2
        assert "child.com" in result["all_includes"]
        assert "leaf.com" in result["all_includes"]


def test_check_spf_missing():
    import dns.resolver
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.side_effect = dns.resolver.NXDOMAIN
        result = check_spf_record("example.com")
        assert result["status"] == "not_configured"
        assert result["record"] is None
        assert any(i["code"] == "SPF_MISSING" for i in result["issues"])


def test_check_spf_duplicate_violation():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = [
            MockDNSAnswer(["v=spf1 include:_spf.google.com ~all"]),
            MockDNSAnswer(["v=spf1 include:spf.titan.email ~all"]),
        ]
        result = check_spf_record("example.com")
        assert result["status"] == "critical"
        assert any(i["code"] == "SPF_DUPLICATE" for i in result["issues"])


def test_check_spf_lookup_limit_exceeded():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        # 11 lookup mechanisms
        mechs = " ".join([f"include:spf{i}.example.com" for i in range(11)])
        mock_resolve.return_value = [MockDNSAnswer([f"v=spf1 {mechs} ~all"])]
        result = check_spf_record("example.com")
        assert result["status"] == "critical"
        assert result["lookup_count"] >= 11
        assert any(i["code"] == "SPF_LOOKUP_LIMIT_EXCEEDED" for i in result["issues"])


def test_check_spf_allow_all_policy():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = [MockDNSAnswer(["v=spf1 include:_spf.google.com +all"])]
        result = check_spf_record("example.com")
        assert result["status"] == "critical"
        assert any(i["code"] == "SPF_POLICY_ALLOW_ALL" for i in result["issues"])


def test_check_dkim_record_discovery():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        dummy_key = base64.b64encode(b"0" * 260).decode("utf-8")
        mock_resolve.return_value = [MockDNSAnswer([f"v=DKIM1; k=rsa; p={dummy_key}"])]
        result = check_dkim_record("example.com", custom_selector="titan1")
        assert result["status"] == "healthy"
        assert result["selector"] == "titan1"
        assert result["key_length_bits"] == 2048


def test_check_dkim_not_verified_when_selector_unknown():
    import dns.resolver
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.side_effect = dns.resolver.NXDOMAIN
        result = check_dkim_record("example.com")
        assert result["status"] == "not_verified"
        assert result["selector"] is None
        assert any(i["code"] == "DKIM_NOT_VERIFIED" for i in result["issues"])


def test_check_dkim_empty_revoked_key():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = [MockDNSAnswer(["v=DKIM1; k=rsa; p="])]
        result = check_dkim_record("example.com", custom_selector="s1")
        assert result["status"] == "critical"
        assert any(i["code"] == "DKIM_EMPTY_KEY" for i in result["issues"])


def test_check_dmarc_valid_and_missing():
    import dns.resolver
    # Missing DMARC
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.side_effect = dns.resolver.NXDOMAIN
        result = check_dmarc_record("example.com")
        assert result["status"] == "not_configured"
        assert any(i["code"] == "DMARC_MISSING" for i in result["issues"])

    # DMARC with p=none (warning: monitoring only)
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = [MockDNSAnswer(["v=DMARC1; p=none; rua=mailto:dmarc@example.com"])]
        result = check_dmarc_record("example.com")
        assert result["status"] == "warning"
        assert result["policy"] == "none"
        assert any(i["code"] == "DMARC_POLICY_NONE" for i in result["issues"])

    # DMARC with p=reject (healthy)
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = [MockDNSAnswer(["v=DMARC1; p=reject; rua=mailto:dmarc@example.com"])]
        result = check_dmarc_record("example.com")
        assert result["status"] == "healthy"
        assert result["policy"] == "reject"


def test_check_mx_records_provider_detection():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = [
            MockMXAnswer(10, "aspmx.l.google.com."),
            MockMXAnswer(20, "alt1.aspmx.l.google.com."),
        ]
        result = check_mx_records("example.com")
        assert result["status"] == "healthy"
        assert result["detected_provider"] == "Google Workspace"
        assert len(result["records"]) == 2
        assert result["records"][0]["priority"] == 10
        # Verify MX hosts NEVER contain blocklists
        for mx in result["records"]:
            assert "spamhaus" not in mx["host"]
            assert "spamcop" not in mx["host"]


def test_check_dnsbl_blocklists_against_relay():
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        import dns.resolver
        # Target relay IP 1.2.3.4
        mock_resolve.side_effect = dns.resolver.NXDOMAIN
        res = check_dnsbl_blocklists("example.com", relay_host="smtp.example.com", relay_ip="1.2.3.4")
        assert res["status"] == "clean"
        assert "1.2.3.4" in res["target_checked"]
        assert len(res["results"]) == 3


def test_analyze_email_headers():
    sample_headers = """Received: from smtp.company.com ([192.0.2.1]) by mx.google.com; Wed, 21 Oct 2026 10:00:00 +0000
From: Support <support@company.com>
To: client@example.org
Subject: Q4 System Update
Message-ID: <msg-999@company.com>
Date: Wed, 21 Oct 2026 10:00:00 +0000
Return-Path: <support@company.com>
Authentication-Results: mx.google.com;
       dkim=pass header.i=@company.com header.s=s1;
       spf=pass (google.com: domain of support@company.com designates 192.0.2.1 as permitted sender);
       dmarc=pass (p=REJECT) header.from=company.com
DKIM-Signature: v=1; a=rsa-sha256; d=company.com; s=s1;
"""
    result = analyze_email_headers(sample_headers, is_demo=True)
    assert result["overall_status"] == "healthy"
    assert result["is_demo_data"] is True
    assert result["from_domain"] == "company.com"
    assert result["sending_relay_ip"] == "192.0.2.1"
    assert result["spf"]["verdict"] == "pass"
    assert result["spf"]["aligned"] is True
    assert result["dkim"]["verdict"] == "pass"
    assert result["dkim"]["aligned"] is True
    assert result["dmarc"]["verdict"] == "pass"


@pytest.mark.asyncio
async def test_get_inbox_delivery_stats_aggregates_direct_and_campaign(session):
    inbox = await make_inbox(session, email="metrics@weblinxsolution.com", provider="smtp")

    # Initially 0 sends -> rates should be None (N/A)
    stats_empty = await get_inbox_delivery_stats(session, inbox.id)
    assert stats_empty["total_sent"] == 0
    assert stats_empty["open_rate"] is None
    assert stats_empty["reply_rate"] is None
    assert stats_empty["bounce_rate"] is None

    # Add 1 campaign email
    el = EmailLog(
        inbox_id=inbox.id,
        lead_id=1,
        campaign_id=1,
        opened=True,
        clicked=False,
    )
    session.add(el)

    # Add 1 direct email
    de = DirectEmail(
        inbox_id=inbox.id,
        to_email="test@recipient.com",
        subject="Direct test",
        body="Hello",
        status="sent",
        opened=False,
        replied=True,
    )
    session.add(de)
    await session.commit()

    stats = await get_inbox_delivery_stats(session, inbox.id)
    assert stats["campaign_sent"] == 1
    assert stats["direct_sent"] == 1
    assert stats["total_sent"] == 2
    assert stats["total_opened"] == 1
    assert stats["total_replied"] == 1
    assert stats["open_rate"] == 50.0
    assert stats["reply_rate"] == 50.0


@pytest.mark.asyncio
async def test_run_domain_health_scan_for_inbox(session):
    inbox = await make_inbox(session, email="ops@weblinxsolution.com", provider="smtp")

    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        def side_effect(qname, rtype):
            if rtype == "TXT" and str(qname) == "weblinxsolution.com":
                return [MockDNSAnswer(["v=spf1 include:spf.titan.email ~all"])]
            elif rtype == "TXT" and str(qname).startswith("_dmarc."):
                return [MockDNSAnswer(["v=DMARC1; p=quarantine; rua=mailto:dmarc@weblinxsolution.com"])]
            elif rtype == "TXT" and "._domainkey." in str(qname):
                dummy_key = base64.b64encode(b"0" * 260).decode("utf-8")
                return [MockDNSAnswer([f"v=DKIM1; p={dummy_key}"])]
            elif rtype == "MX":
                return [MockMXAnswer(10, "mx1.titan.email.")]
            return []

        mock_resolve.side_effect = side_effect

        scan = await run_domain_health_scan_for_inbox(session, inbox.id, custom_dkim_selector="titan1")
        assert scan.domain == "weblinxsolution.com"
        assert scan.spf_status == "healthy"
        assert scan.dmarc_status == "healthy"
        assert scan.dmarc_policy == "quarantine"
        assert scan.mx_status == "healthy"


@pytest.mark.asyncio
async def test_deliverability_api_endpoints(session):
    from app.routers.deliverability import (
        get_deliverability_summary,
        inspect_email_headers,
        HeaderInspectRequest,
    )
    inbox = await make_inbox(session, email="marketing@weblinxsolution.com", provider="smtp")

    # 1. Summary router call
    summary = await get_deliverability_summary(db=session)
    assert "total_inboxes" in summary
    assert summary["total_inboxes"] >= 1
    assert any(i["email"] == "marketing@weblinxsolution.com" for i in summary["inboxes"])

    # 2. Inspect headers router call
    test_headers = """From: news@weblinxsolution.com
To: user@example.com
Subject: Weekly Newsletter
Return-Path: <news@weblinxsolution.com>
Authentication-Results: mx.google.com; spf=pass; dkim=pass header.i=@weblinxsolution.com; dmarc=pass
DKIM-Signature: v=1; d=weblinxsolution.com; s=s1;
"""
    req = HeaderInspectRequest(raw_headers_or_eml=test_headers, is_demo=False)
    report = await inspect_email_headers(req)
    assert report["overall_status"] == "healthy"
    assert report["spf"]["verdict"] == "pass"
    assert report["dkim"]["verdict"] == "pass"
    assert report["is_demo_data"] is False


def test_titan_dkim_selector_in_probe_list():
    from app.deliverability import COMMON_DKIM_SELECTORS
    # Titan Email selectors titan1-titan10 must be in probe list
    for i in range(1, 11):
        assert f"titan{i}" in COMMON_DKIM_SELECTORS
    assert "titan" in COMMON_DKIM_SELECTORS


def test_dmarc_quarantine_evaluation(monkeypatch):
    from app.deliverability import check_dmarc_record

    class MockAnswer:
        def __init__(self, txt):
            self.strings = [txt.encode("utf-8")]

    class MockResolver:
        def resolve(self, qname, rtype):
            if "_dmarc" in qname and rtype == "TXT":
                return [MockAnswer("v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com")]
            raise Exception("NXDOMAIN")

    monkeypatch.setattr("app.deliverability.get_dns_resolver", lambda: MockResolver())

    res = check_dmarc_record("example.com")
    assert res["status"] == "healthy"
    assert res["policy"] == "quarantine"
    assert res["record"] == "v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com"
    # Quarantine should not produce a policy warning
    assert not any(i.get("code") == "DMARC_POLICY_NONE" for i in res["issues"])


def test_email_header_dkim_matching_published_key(monkeypatch):
    from app.deliverability import analyze_email_headers

    # Mock check_dkim_record to simulate published DNS key match
    def mock_check_dkim(domain, custom_selector=None, provider=None):
        if custom_selector == "titan4":
            return {
                "status": "healthy",
                "selector": "titan4",
                "record": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ...",
                "published_in_dns": True,
            }
        return {"status": "not_verified", "record": None, "published_in_dns": False}

    monkeypatch.setattr("app.deliverability.check_dkim_record", mock_check_dkim)

    headers = """From: yousaf@weblinxsolution.com
To: user@example.com
Subject: Test Email
Return-Path: <yousaf@weblinxsolution.com>
Authentication-Results: mx.google.com; spf=pass; dkim=pass header.i=@weblinxsolution.com header.s=titan4; dmarc=pass (p=QUARANTINE)
DKIM-Signature: v=1; a=rsa-sha256; d=weblinxsolution.com; s=titan4;
"""
    report = analyze_email_headers(headers)
    assert report["overall_status"] == "healthy"
    assert report["dkim"]["verdict"] == "pass"
    assert report["dkim"]["dns_key_matched"] is True
    assert any(diag["category"] == "DKIM DNS Alignment" and diag["status"] == "pass" for diag in report["diagnostics"])

