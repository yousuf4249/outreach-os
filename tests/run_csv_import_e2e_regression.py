"""E2E Test Runner for CSV Import Bug Regression Verification.

Runs the browser CDP test suite, checks database row counts before and after,
and cleans up test artifacts cleanly.
"""

import sys
import os
import subprocess
import sqlite3
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import AsyncSessionLocal
from app.models import User
from app.auth import create_access_token
from sqlalchemy import select


def get_lead_count():
    conn = sqlite3.connect('local_dev.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, company FROM lead")
    leads = cursor.fetchall()
    conn.close()
    return leads


def cleanup_test_leads():
    conn = sqlite3.connect('local_dev.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lead WHERE email = 'john.doe.qa@techinnovations.example.com'")
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"[Cleanup] Deleted {deleted} test lead(s) with email 'john.doe.qa@techinnovations.example.com'.")


async def get_admin_token():
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).limit(1))
        user = user_res.scalar_one_or_none()
        assert user is not None, "Admin user must exist"
        return create_access_token(user.id, user.role)


def main():
    print("=" * 60)
    print("WEBLINX OUTREACH OS: CSV IMPORT REGRESSION VERIFICATION")
    print("=" * 60)

    # 1. Check initial lead count
    initial_leads = get_lead_count()
    print(f"\n[DB Check Before Test] Total Leads in Database: {len(initial_leads)}")
    for l in initial_leads:
        print(f"  - Lead ID {l[0]}: {l[2]} ({l[1]}) - Company: {l[3]}")

    assert len(initial_leads) == 1, f"Expected 1 baseline lead, found {len(initial_leads)}"
    assert initial_leads[0][1] == "kristin@designgood.com", f"Baseline lead must be Kristin Moses"

    # 2. Generate token
    token = asyncio.run(get_admin_token())
    print("\n[Auth] Admin token successfully generated.")

    # 3. Run Node.js CDP browser regression test
    print("\n[Browser Test] Launching Chrome CDP headless regression test...")
    node_cmd = ["node", "tests/test_browser_csv_import_regression.js", token]
    result = subprocess.run(node_cmd, capture_output=True, text=True)

    print("\n--- BROWSER TEST STDOUT ---")
    print(result.stdout)

    if result.stderr:
        print("--- BROWSER TEST STDERR ---")
        print(result.stderr)

    if result.returncode != 0:
        print(f"\n[FAIL] Node test exited with return code {result.returncode}")
        sys.exit(result.returncode)

    # 4. Check lead count after import
    post_leads = get_lead_count()
    print(f"\n[DB Check After Test] Total Leads in Database: {len(post_leads)}")
    for l in post_leads:
        print(f"  - Lead ID {l[0]}: {l[2]} ({l[1]}) - Company: {l[3]}")

    assert len(post_leads) == 2, f"Expected 2 leads after import, found {len(post_leads)}"
    assert any(l[1] == "john.doe.qa@techinnovations.example.com" for l in post_leads), "Imported test lead must exist in DB"
    assert any(l[1] == "kristin@designgood.com" for l in post_leads), "Original lead Kristin Moses must remain intact"

    # 5. Clean up imported test lead
    cleanup_test_leads()

    final_leads = get_lead_count()
    print(f"\n[DB Check After Cleanup] Total Leads in Database: {len(final_leads)}")
    for l in final_leads:
        print(f"  - Lead ID {l[0]}: {l[2]} ({l[1]}) - Company: {l[3]}")

    assert len(final_leads) == 1, f"Expected 1 lead after cleanup, found {len(final_leads)}"
    assert final_leads[0][1] == "kristin@designgood.com", f"Remaining lead must be Kristin Moses"

    # 6. Clean up temporary csv if exists
    temp_csv = os.path.join(os.path.dirname(__file__), "test_prospects_import_temp.csv")
    if os.path.exists(temp_csv):
        os.remove(temp_csv)
        print(f"[Cleanup] Removed temp CSV file: {temp_csv}")

    print("\n" + "=" * 60)
    print("SUCCESS: CSV IMPORT REGRESSION TEST COMPLETED PERFECTLY!")
    print("=" * 60)


if __name__ == '__main__':
    main()
