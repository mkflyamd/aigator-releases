import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from fastapi.testclient import TestClient

import security

STATIC = pathlib.Path(__file__).parent.parent / "web" / "static"
HOST = {"Host": "127.0.0.1:8000"}


def _page(monkeypatch=None, headers=HOST):
    import app as app_module

    return TestClient(app_module.app).get("/", headers=headers)


def _directive(csp: str, name: str) -> str:
    return next(d for d in csp.split("; ") if d.startswith(name + " "))


def test_page_has_enforcing_csp_without_inline_script_allowance(monkeypatch):
    monkeypatch.delenv("AIGATOR_CSP_REPORT_ONLY", raising=False)
    response = _page()
    csp = response.headers["content-security-policy"]
    script_src = _directive(csp, "script-src")
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "object-src 'none'" in csp and "base-uri 'self'" in csp
    assert "ws://127.0.0.1:8000" in _directive(csp, "connect-src")


def test_every_inline_script_carries_the_response_nonce(monkeypatch):
    monkeypatch.delenv("AIGATOR_CSP_REPORT_ONLY", raising=False)
    response = _page()
    nonce = re.search(r"'nonce-([^']+)'", response.headers["content-security-policy"]).group(1)
    html = response.text
    assert f"window.__CSP_NONCE__ = \"{nonce}\"" in html
    for tag in re.findall(r"<script\b[^>]*>", html):
        if " src=" in tag:
            continue
        assert f'nonce="{nonce}"' in tag, tag


def test_nonce_changes_on_every_response():
    first = _page().headers["content-security-policy"]
    second = _page().headers["content-security-policy"]
    assert first != second


def test_report_only_switch(monkeypatch):
    monkeypatch.setenv("AIGATOR_CSP_REPORT_ONLY", "1")
    response = _page()
    assert "content-security-policy-report-only" in response.headers
    assert "content-security-policy" not in response.headers


def test_odd_host_header_cannot_add_csp_directives():
    csp = security.build_csp("n", "evil.test; script-src *")
    assert "evil.test" not in csp


def test_bootstrap_data_cannot_close_the_script_tag():
    assert "<" not in security.script_json(["</script><script>alert(1)</script>"])


def test_no_inline_event_handlers_remain_in_served_ui():
    handler = re.compile(r"""[\s'"`]on[a-z]{3,}\s*=\s*["'\\]""")
    offenders = []
    for path in [STATIC / "index.html", *STATIC.glob("*.js")]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            if handler.search(line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == []
