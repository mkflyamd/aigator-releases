import pytest

from sandbox import approvals


@pytest.fixture(autouse=True)
def _fresh():
    approvals._reset()
    yield
    approvals._reset()


R, W, H = ["C:/data"], ["C:/out"], ["api.example.com:443"]


def test_unknown_set_is_none():
    assert approvals.lookup("tab-1", R, W, H) == ("none", None)


def test_pending_then_approved_is_consumed_once():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    assert approvals.lookup("tab-1", R, W, H, now=101.0) == ("pending", req)
    approvals.decide(req.id, "tab-1", True, now=102.0)
    status, got = approvals.lookup("tab-1", R, W, H, now=103.0)
    assert (status, got.id) == ("approved", req.id)
    assert approvals.lookup("tab-1", R, W, H, now=104.0) == ("none", None)


def test_exact_set_match_only():
    req = approvals.create("tab-1", R, [], [], now=100.0)
    approvals.decide(req.id, "tab-1", True, now=101.0)
    assert approvals.lookup("tab-1", R + ["C:/other"], [], [], now=102.0) == ("none", None)
    assert approvals.lookup("tab-1", [], R, [], now=102.0) == ("none", None)
    assert approvals.lookup("tab-1", ["c:/DATA"], [], [], now=102.0)[0] in ("approved", "none")


def test_other_tab_does_not_match():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", True, now=101.0)
    assert approvals.lookup("tab-2", R, W, H, now=102.0) == ("none", None)


def test_denied_reported_once():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", False, now=101.0)
    assert approvals.lookup("tab-1", R, W, H, now=102.0)[0] == "denied"
    assert approvals.lookup("tab-1", R, W, H, now=103.0) == ("none", None)


def test_expiry_after_ten_minutes():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", True, now=200.0)
    assert approvals.lookup("tab-1", R, W, H, now=100.0 + 601)[0] == "expired"


def test_decide_errors():
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide("nope", "tab-1", True)
    assert e.value.status_code == 404
    req = approvals.create("tab-1", R, W, H, now=100.0)
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req.id, "tab-2", True, now=101.0)
    assert e.value.status_code == 409
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req.id, "tab-1", True, now=100.0 + 601)
    assert e.value.status_code == 410
    req2 = approvals.create("tab-1", R, [], [], now=100.0)
    approvals.decide(req2.id, "tab-1", True, now=101.0)
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req2.id, "tab-1", False, now=102.0)
    assert e.value.status_code == 409
