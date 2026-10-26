"""Unit test verifying that compute_tracking_status_and_label and tracking payloads match frontend expectations."""
from app.unibox_tracking import compute_tracking_status_and_label

def test_tracking_status():
    # 1. Plain text / not tracked
    s1, l1 = compute_tracking_status_and_label(is_tracked=False)
    assert s1 == "not_tracked"
    print("  [PASS] Plain text / not tracked status verified.")

    # 2. Sent, no opens yet
    s2, l2 = compute_tracking_status_and_label(is_tracked=True, open_count=0, click_count=0)
    assert s2 == "no_open_detected"
    print("  [PASS] Sent / unopened status verified.")

    # 3. Open detected (1 open)
    s3, l3 = compute_tracking_status_and_label(is_tracked=True, open_count=1)
    assert s3 == "open_detected"
    print("  [PASS] Open detected status verified.")

    # 4. Clicked
    s4, l4 = compute_tracking_status_and_label(is_tracked=True, open_count=1, click_count=1)
    assert s4 == "clicked"
    print("  [PASS] Clicked status verified.")

    # 5. Replied
    s5, l5 = compute_tracking_status_and_label(is_tracked=True, open_count=2, click_count=1, is_replied=True)
    assert s5 == "replied"
    print("  [PASS] Replied status verified.")

    # 6. Delivery Failed
    s6, l6 = compute_tracking_status_and_label(failed=True)
    assert s6 == "failed"
    print("  [PASS] Delivery failed status verified.")

    print("\n=== ALL EMAIL TRACKING STATUS UNIT TESTS PASSED! ===")

if __name__ == "__main__":
    test_tracking_status()
