from fastapi import HTTPException
import pytest

from web.routes.config_routes import _normalize_github_url


def test_github_url_adds_https_to_bare_hostname():
    assert _normalize_github_url("github.com/") == "https://github.com"


def test_github_url_preserves_enterprise_https_url():
    assert (
        _normalize_github_url("https://github.example.com/")
        == "https://github.example.com"
    )


@pytest.mark.parametrize(
    "url",
    ["http://github.com", "https://user:aigator-fake-api-key@github.com", "not a host"],
)
def test_github_url_rejects_unsafe_or_invalid_values(url):
    with pytest.raises(HTTPException):
        _normalize_github_url(url)
