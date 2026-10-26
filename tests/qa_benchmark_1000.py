"""End-to-End QA Benchmark: 1,000 Controlled Records

Validates:
1. Syntax validation & RFC 5322 compliance
2. Offline 97k disposable domain blocklist accuracy
3. Domain existence & NXDOMAIN detection
4. Common typo detection and auto-suggestions
5. Role-based account categorization without technical deliverability degradation
6. Zero inflation of "Valid" status (honesty rule for domain_validated)
7. Performance throughput (records/sec)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import uuid
from typing import Dict, Any, List
import asyncio

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
from app.verification_data import (
    is_disposable_domain,
    check_role_account,
    check_typo_suggestion,
)


def generate_controlled_dataset() -> List[Dict[str, Any]]:
    dataset = []

    # 1. 250 Invalid Syntax Records
    syntax_samples = [
        "plainaddress",
        "@missinglocal.com",
        "missingatsign.com",
        "two@@atsigns.com",
        "leading.dot.@domain.com",
        "trailing.dot.@domain.com.",
        "user@domain..com",
        "user name@domain.com",
        "user<test>@domain.com",
        "user@domain,com",
    ]
    for i in range(250):
        sample = syntax_samples[i % len(syntax_samples)]
        email = f"bad_{i}_{sample}" if "@" in sample else f"{sample}_{i}"
        dataset.append({
            "id": f"syntax_{i+1}",
            "email": email,
            "category": "invalid_syntax",
            "expected_status": STATUS_INVALID,
        })

    # 2. 250 Known Disposable Burner Domains
    disposable_hosts = [
        "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
        "throwawaymail.com", "sharklasers.com", "getairmail.com", "yopmail.com",
        "trashmail.com", "temp-mail.org", "dispostable.com", "fakeinbox.com",
        "burnermail.io", "nada.ltd", "dropmail.me", "mohmal.com",
        "inboxkitten.com", "crazymailing.com", "mytemp.email", "tempail.com",
        "disposablemail.com", "emailondeck.com", "tempinbox.com", "trashmail.net",
        "guerrillamail.net"
    ]
    for i in range(250):
        host = disposable_hosts[i % len(disposable_hosts)]
        email = f"disposable_user_{i}@{host}"
        dataset.append({
            "id": f"disp_{i+1}",
            "email": email,
            "category": "disposable",
            "expected_status": STATUS_INVALID,
        })

    # 3. 200 Nonexistent / NXDOMAIN Domains
    for i in range(200):
        fake_domain = f"nxdomain-{uuid.uuid4().hex[:12]}-nonexistent.org"
        email = f"lead_{i}@{fake_domain}"
        dataset.append({
            "id": f"nxdomain_{i+1}",
            "email": email,
            "category": "nxdomain",
            "expected_status": STATUS_INVALID,
        })

    # 4. 150 Role-Based Business Accounts
    role_prefixes = [
        "sales", "support", "billing", "info", "admin", "contact",
        "help", "team", "office", "marketing", "press", "legal",
        "hr", "jobs", "careers"
    ]
    for i in range(150):
        prefix = role_prefixes[i % len(role_prefixes)]
        # Weblinxsolution.com has active MX records
        email = f"{prefix}.test{i}@weblinxsolution.com"
        dataset.append({
            "id": f"role_{i+1}",
            "email": email,
            "category": "role_account",
            "expected_status": STATUS_DOMAIN_VALIDATED,  # Must NOT be degraded to risky or invalid
            "must_be_role": True,
        })

    # 5. 100 Common Domain Typos
    typo_domains = [
        "gamil.com", "hotmial.com", "yaho.com", "outlok.com",
        "gmal.com", "gmial.com", "yhoo.com", "iclud.com"
    ]
    for i in range(100):
        typo_d = typo_domains[i % len(typo_domains)]
        email = f"user_{i}@{typo_d}"
        dataset.append({
            "id": f"typo_{i+1}",
            "email": email,
            "category": "domain_typo",
            "expected_status": STATUS_RISKY,
            "must_have_typo_suggestion": True,
        })

    # 6. 50 Edge Case / Null MX / Unknown Records
    for i in range(50):
        # Localhost / invalid TLDs
        email = f"edge_{i}@subdomain.invalid"
        dataset.append({
            "id": f"edge_{i+1}",
            "email": email,
            "category": "edge_case",
            "expected_status": STATUS_INVALID,
        })

    return dataset


async def run_qa_benchmark():
    dataset = generate_controlled_dataset()
    total_records = len(dataset)
    print(f"============================================================")
    print(f"  STARTING QA BENCHMARK: {total_records} CONTROLLED RECORDS")
    print(f"============================================================")

    results = {
        "total": total_records,
        "processed": 0,
        "passed_assertions": 0,
        "failed_assertions": 0,
        "classification_counts": {
            STATUS_VALID: 0,
            STATUS_DOMAIN_VALIDATED: 0,
            STATUS_INVALID: 0,
            STATUS_RISKY: 0,
            STATUS_CATCH_ALL: 0,
            STATUS_UNKNOWN: 0,
        },
        "category_metrics": {},
        "failures": [],
    }

    start_time = time.time()

    # Process in concurrency batches of 25
    batch_size = 25
    for idx in range(0, total_records, batch_size):
        batch = dataset[idx:idx + batch_size]

        async def verify_item(item):
            em = item["email"]
            cat = item["category"]
            exp_status = item["expected_status"]

            # Perform verification with safe SMTP probe disabled (DNS/MX only)
            res = await verify_single_email(em, check_smtp=False, dns_timeout=2.0)
            
            passed = True
            err_reason = None

            # Assert expected status
            if res.status != exp_status:
                passed = False
                err_reason = f"Expected status {exp_status}, got {res.status} (Reason: {res.reason})"

            # Category-specific assertions
            if cat == "disposable":
                if not res.disposable.get("is_disposable"):
                    passed = False
                    err_reason = "Disposable domain was not flagged in disposable_details"
            elif cat == "role_account":
                if not res.role_based.get("is_role_account"):
                    passed = False
                    err_reason = "Role account was not flagged in role_based"
                # Rule 1: Never inflate to valid when mailbox check unconfirmed
                if res.status == STATUS_VALID:
                    passed = False
                    err_reason = "CRITICAL VIOLATION: Inappropriate inflation to 'valid' without SMTP probe"
            elif cat == "domain_typo":
                if not res.typo.get("has_typo_risk") or not res.typo.get("suggestion"):
                    passed = False
                    err_reason = f"Domain typo was not suggested for {em}"

            return item, res, passed, err_reason

        batch_outcomes = await asyncio.gather(*(verify_item(item) for item in batch))

        for item, res, passed, err_reason in batch_outcomes:
            results["processed"] += 1
            st = res.status
            results["classification_counts"][st] = results["classification_counts"].get(st, 0) + 1

            cat = item["category"]
            if cat not in results["category_metrics"]:
                results["category_metrics"][cat] = {"total": 0, "passed": 0, "failed": 0}
            results["category_metrics"][cat]["total"] += 1

            if passed:
                results["passed_assertions"] += 1
                results["category_metrics"][cat]["passed"] += 1
            else:
                results["failed_assertions"] += 1
                results["category_metrics"][cat]["failed"] += 1
                results["failures"].append({
                    "id": item["id"],
                    "email": item["email"],
                    "category": cat,
                    "error": err_reason,
                })

        if results["processed"] % 200 == 0 or results["processed"] == total_records:
            elapsed = time.time() - start_time
            rps = results["processed"] / (elapsed or 0.001)
            print(f"Processed: {results['processed']}/{total_records} ({rps:.1f} records/sec)")

    total_time = time.time() - start_time
    throughput = total_records / (total_time or 0.001)

    print("\n" + "=" * 60)
    print("  QA BENCHMARK EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Total Controlled Records:   {results['total']}")
    print(f"Total Execution Time:       {total_time:.2f} seconds")
    print(f"Processing Throughput:      {throughput:.1f} records/second")
    print(f"Total Assertions Passed:    {results['passed_assertions']} ({results['passed_assertions']/results['total']*100:.1f}%)")
    print(f"Total Assertions Failed:    {results['failed_assertions']}")
    print("\nCategory Breakdown:")
    for cat, m in results["category_metrics"].items():
        acc = (m["passed"] / m["total"]) * 100
        print(f"  - {cat:20s}: {m['passed']}/{m['total']} ({acc:.1f}% accuracy)")

    print("\nDeliverability Status Distribution:")
    for st, count in results["classification_counts"].items():
        pct = (count / results['total']) * 100
        print(f"  - {st:20s}: {count:4d} ({pct:5.1f}%)")

    if results["failures"]:
        print("\nFailures Sample (first 5):")
        for f in results["failures"][:5]:
            print(f"  * {f['id']} | {f['email']} | {f['category']} -> {f['error']}")

    assert results["failed_assertions"] == 0, f"{results['failed_assertions']} assertions failed out of {results['total']}"
    print("\nSUCCESS: All 1,000 controlled records passed QA validation with 100% accuracy!")


if __name__ == "__main__":
    asyncio.run(run_qa_benchmark())
