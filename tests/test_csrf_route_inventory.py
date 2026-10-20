"""Every state-changing route must require the CSRF token or be in the reviewed baseline.

New POST/PUT/PATCH/DELETE routes are default-deny: add `dependencies=[Depends(verify_csrf)]`
(see web/security.py). The baseline lists routes that existed before this check; it may only shrink.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from app import app

BASELINE = pathlib.Path(__file__).with_name("csrf_route_baseline.txt")
MUTATING = {"post", "put", "patch", "delete"}
CSRF_HEADER = "x-csrf-token"


def _inventory():
    total, unprotected = 0, set()
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            if method not in MUTATING:
                continue
            total += 1
            headers = {p["name"].lower() for p in operation.get("parameters", []) if p.get("in") == "header"}
            if CSRF_HEADER not in headers:
                unprotected.add(f"{method.upper()} {path}")
    return total, unprotected


def _baseline():
    lines = BASELINE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_inventory_sees_the_routes():
    total, _ = _inventory()
    assert total >= 150, f"only {total} state-changing routes found; the route inventory is broken"


def test_new_state_changing_routes_require_csrf():
    _, unprotected = _inventory()
    new = sorted(unprotected - _baseline())
    assert not new, (
        "State-changing routes without CSRF protection:\n  " + "\n  ".join(new)
        + "\nAdd dependencies=[Depends(verify_csrf)] from web/security.py to each route."
    )


def test_baseline_lists_only_unprotected_routes():
    _, unprotected = _inventory()
    stale = sorted(_baseline() - unprotected)
    assert not stale, (
        "Baseline entries that are now protected or no longer exist; delete them from "
        "tests/csrf_route_baseline.txt:\n  " + "\n  ".join(stale)
    )


def test_sensitive_routes_are_registered_and_protected():
    from security import SENSITIVE_ROUTES

    _, unprotected = _inventory()
    routes = {
        f"{method.upper()} {path}"
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in MUTATING
    }
    missing = sorted(SENSITIVE_ROUTES - routes)
    assert not missing, "SENSITIVE_ROUTES lists routes that do not exist:\n  " + "\n  ".join(missing)
    open_routes = sorted(SENSITIVE_ROUTES & unprotected)
    assert not open_routes, "Sensitive routes without verify_csrf:\n  " + "\n  ".join(open_routes)


def test_sensitive_routes_reject_requests_without_a_token():
    import re

    from fastapi.testclient import TestClient

    from security import SENSITIVE_ROUTES

    client = TestClient(app, raise_server_exceptions=False)
    failures = []
    for route in sorted(SENSITIVE_ROUTES):
        method, path = route.split(" ", 1)
        url = re.sub(r"\{[^}]+\}", "x", path)
        response = client.request(method, url)
        if response.status_code != 403:
            failures.append(f"{route} -> {response.status_code}")
    assert not failures, "Sensitive routes that accepted a request without a CSRF token:\n  " + "\n  ".join(failures)
