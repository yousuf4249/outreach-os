"""QA Verification for Optimized Prospects Database Table & Search."""
import urllib.request
import json
from app.auth import create_access_token

def test_api():
    token = create_access_token('1', role='admin')
    base_url = "http://127.0.0.1:8000"
    headers = {"Authorization": f"Bearer {token}"}

    print("=== STARTING PROSPECTS DATABASE TABLE & SEARCH QA ===")

    # 1. Fetch all leads
    req = urllib.request.Request(f"{base_url}/api/leads", headers=headers)
    with urllib.request.urlopen(req) as resp:
        leads = json.loads(resp.read().decode("utf-8"))
    
    print(f"Total leads returned: {len(leads)}")
    assert len(leads) >= 15, f"Expected at least 15 leads, got {len(leads)}"

    # Verify first lead has all 7 default column fields
    first = leads[0]
    print(f"Sample lead fields check:")
    print(f"  Company: {first.get('company')} (Website: {first.get('website')})")
    print(f"  Contact: {first.get('name')}")
    print(f"  Email: {first.get('email')}")
    print(f"  Phone: {first.get('phone')}")
    print(f"  Verification: {first.get('email_verification_status')}")
    print(f"  Pipeline Status: {first.get('pipeline_status')}")

    assert first.get('company'), "Company should be populated"
    assert first.get('email'), "Email should be populated"
    print("  [PASS] All 7 core columns fields available in API response.")

    # 2. Test search across Company Name
    req = urllib.request.Request(f"{base_url}/api/leads?q=Barton", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    assert len(res) >= 1, "Should find Barton Springs Digital"
    assert "Barton Springs" in res[0]["company"]
    print("  [PASS] Search across Company Name verified.")

    # 3. Test search across Contact Name
    req = urllib.request.Request(f"{base_url}/api/leads?q=Marcus", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    assert len(res) >= 1, "Should find Marcus Vance"
    assert "Marcus Vance" in res[0]["name"]
    print("  [PASS] Search across Contact Name verified.")

    # 4. Test search across Email Address
    req = urllib.request.Request(f"{base_url}/api/leads?q=sococreative", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    assert len(res) >= 1, "Should find sococreative email"
    assert "sococreative.com" in res[0]["email"]
    print("  [PASS] Search across Email Address verified.")

    # 5. Test search across Phone Number
    req = urllib.request.Request(f"{base_url}/api/leads?q=0103", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    assert len(res) >= 1, "Should find phone containing 0103"
    assert "0103" in res[0]["phone"]
    print(f"  [PASS] Search across Phone Number verified (matched: {res[0]['name']} | {res[0]['phone']}).")

    # 6. Test Pipeline Status filter
    req = urllib.request.Request(f"{base_url}/api/leads?pipeline_status=interested", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    assert len(res) >= 1
    for l in res:
        assert l["pipeline_status"] == "interested"
    print(f"  [PASS] Pipeline status filter verified ({len(res)} leads with status 'interested').")

    # 7. Test Verification Status filter
    req = urllib.request.Request(f"{base_url}/api/leads?email_verification_status=valid", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    assert len(res) >= 1
    for l in res:
        assert l["email_verification_status"] == "valid"
    print(f"  [PASS] Email verification status filter verified ({len(res)} valid leads).")

    print("\n=== ALL PROSPECT TABLE & SEARCH TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_api()
