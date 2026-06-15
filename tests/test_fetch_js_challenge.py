"""Issue #47: fetch_webpage on JS-challenge sites (Cloudflare, PyPI bot
protection) returned the challenge page as if it were content, leaving the LLM
to "try the browser" and fail silently.

Architecture decision: fail fast with a clear error naming the blocker — no
headless-browser dependency. _detect_js_challenge inspects status/headers/body
and returns the blocker label (or None for a normal page); _tool_fetch_webpage
then returns an actionable error instead of the challenge HTML.
"""
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from skills._always_on.tools import _detect_js_challenge


def test_detects_cloudflare_just_a_moment_body():
    body = "<html><head><title>Just a moment...</title></head><body>" \
           "<div class='cf-browser-verification'></div></body></html>"
    assert _detect_js_challenge(200, {}, body) == "Cloudflare"


def test_just_a_moment_in_body_prose_is_not_a_challenge():
    # The generic phrase "just a moment" appears in real article prose; it must
    # only count as a challenge when it is the page <title>, not anywhere in body.
    body = "<html><head><title>How to relax</title></head><body>" \
           "<p>Take a deep breath and wait just a moment before you continue.</p>" \
           "</body></html>"
    assert _detect_js_challenge(200, {"Server": "nginx"}, body) is None


def test_detects_cloudflare_just_a_moment_in_title_without_class():
    body = "<html><head><title>Just a moment...</title></head><body></body></html>"
    assert _detect_js_challenge(200, {}, body) == "Cloudflare"


def test_detects_cloudflare_via_headers_on_403():
    headers = {"Server": "cloudflare", "cf-mitigated": "challenge"}
    assert _detect_js_challenge(403, headers, "") == "Cloudflare"


def test_detects_generic_enable_javascript_challenge():
    body = "Please enable JavaScript and cookies to continue."
    assert _detect_js_challenge(200, {}, body) is not None


def test_normal_html_is_not_a_challenge():
    body = "<html><body><h1>Welcome</h1><p>Real content here.</p></body></html>"
    assert _detect_js_challenge(200, {"Server": "nginx"}, body) is None


def test_header_lookup_is_case_insensitive():
    headers = {"SERVER": "cloudflare", "CF-Mitigated": "challenge"}
    assert _detect_js_challenge(503, headers, "") == "Cloudflare"
