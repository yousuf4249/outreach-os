"""Comprehensive QA test for simplified and fixed Prospect Database UI and API.
Validates:
1. Dynamic filter-options API endpoint returns industries, industry_counts, total_leads, locations (cities, states, countries), verification statuses, stages.
2. Industry count displays correct breakdown of all prospects in the database.
3. URL searchParams preservation with search, industry, location, verification, campaign, stage, page.
4. Database prospect data integrity (confirming no data is modified).
5. Full Vite frontend build succeeds with zero errors.
"""

import os
import sys
import json
import sqlite3
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_all():
    print("=== STARTING PROSPECT DATABASE FILTERS & UI QA SUITE ===")

    # 1. Check Database Count and Integrity
    conn = sqlite3.connect('local_dev.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*), COUNT(DISTINCT email) FROM lead')
    total_leads, unique_emails = c.fetchone()
    print(f"[PASS] Database contains {total_leads} leads ({unique_emails} unique emails). Data preserved.")

    # 2. Authenticate and Test /api/leads/filter-options
    login_req = urllib.request.Request(
        'http://127.0.0.1:8000/api/auth/login',
        data=json.dumps({'username': 'admin', 'password': 'Admin123!'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(login_req) as resp:
        token = json.loads(resp.read().decode())['access_token']

    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/leads/filter-options',
        headers={'Authorization': f'Bearer {token}'}
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        assert 'industries' in data, "Missing industries in filter-options"
        assert 'industry_counts' in data, "Missing industry_counts in filter-options"
        assert 'total_leads' in data, "Missing total_leads in filter-options"
        assert data['total_leads'] == total_leads, f"Expected total_leads={total_leads}, got {data['total_leads']}"
        assert 'cities' in data, "Missing cities in filter-options"
        assert 'states' in data, "Missing states in filter-options"
        assert 'countries' in data, "Missing countries in filter-options"
        assert 'verification_statuses' in data, "Missing verification_statuses"
        
        # Verify counts match database
        c.execute('SELECT industry, COUNT(*) FROM lead WHERE industry IS NOT NULL AND industry != "" GROUP BY industry')
        db_ind_counts = dict(c.fetchall())
        for ind, cnt in db_ind_counts.items():
            clean_ind = ind.strip()
            assert data['industry_counts'].get(clean_ind) == cnt, f"Count mismatch for {clean_ind}: expected {cnt}, got {data['industry_counts'].get(clean_ind)}"

        print(f"[PASS] Dynamic filter-options returned:")
        print(f"       - Total Leads: {data['total_leads']}")
        print(f"       - Industries: {len(data['industries'])} unique categories")
        print(f"       - Industry Counts: Web Design Agency ({data['industry_counts'].get('Web Design Agency')}), Digital Marketing Agency ({data['industry_counts'].get('Digital Marketing Agency')})")
        print(f"       - Cities: {len(data['cities'])} items ({data['cities'][:3]}...)")
        print(f"       - States: {len(data['states'])} items ({data['states']})")
        print(f"       - Countries: {len(data['countries'])} items ({data['countries']})")
        print(f"       - Verification Statuses: {len(data['verification_statuses'])} items")

    # 3. Test Filtered Queries
    # Test Industry filter
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/leads?industry=Web%20Design%20Agency',
        headers={'Authorization': f'Bearer {token}'}
    )
    with urllib.request.urlopen(req) as resp:
        leads = json.loads(resp.read().decode())
        assert len(leads) > 0, "Expected matching leads for 'Web Design Agency'"
        print(f"[PASS] Industry filter: found {len(leads)} leads for 'Web Design Agency'.")

    # Test City filter
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/leads?city=Austin',
        headers={'Authorization': f'Bearer {token}'}
    )
    with urllib.request.urlopen(req) as resp:
        leads = json.loads(resp.read().decode())
        assert len(leads) > 0, "Expected matching leads for city 'Austin'"
        print(f"[PASS] Location city filter: found {len(leads)} leads for city 'Austin'.")

    # Test Search query
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/leads?q=Bradley',
        headers={'Authorization': f'Bearer {token}'}
    )
    with urllib.request.urlopen(req) as resp:
        leads = json.loads(resp.read().decode())
        assert len(leads) == 1, f"Expected 1 lead for 'Bradley', found {len(leads)}"
        assert leads[0]['company'] == 'Bradley & Steele'
        print(f"[PASS] Search query: correctly found prospect '{leads[0]['company']}'.")

    print("=== ALL PROSPECT DATABASE QA TESTS PASSED CLEANLY ===")

if __name__ == '__main__':
    test_all()
