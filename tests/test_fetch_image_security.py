"""Security regression coverage for authenticated image downloads."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from skills.fetch_image.tools import _safe_http_get, _tool_fetch_image, _validate_fetch_url


def test_source_flag_cannot_force_graph_auth_for_an_untrusted_url():
    with (
        patch("skills.fetch_image.tools._fetch_graph_image") as graph,
        patch("skills.fetch_image.tools._fetch_unauthenticated", return_value=(b"data", "image/png")) as anonymous,
        patch("skills.fetch_image.tools._save_image", return_value="/tmp/image.png"),
    ):
        result = _tool_fetch_image(url="https://example.com/image.png", source="graph")

    assert result["file_path"] == "/tmp/image.png"
    graph.assert_not_called()
    anonymous.assert_called_once_with("https://example.com/image.png")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/image.png",
        "file:///etc/passwd",
        "https://127.0.0.1/image.png",
        "https://[::1]/image.png",
    ],
)
def test_validate_fetch_url_rejects_non_public_or_non_https_targets(url):
    with pytest.raises(ValueError):
        _validate_fetch_url(url)


def test_redirect_is_revalidated_and_credentials_are_not_forwarded():
    class Response:
        def __init__(self, redirect=False, location="", content=b""):
            self.is_redirect = redirect
            self.headers = {"location": location} if location else {"content-type": "image/png"}
            self.content = content

        def raise_for_status(self):
            return None

    validated = []
    responses = [Response(redirect=True, location="https://cdn.example.net/image.png"), Response(content=b"image")]
    with (
        patch("skills.fetch_image.tools._validate_fetch_url", side_effect=lambda url, hosts=None: validated.append((url, hosts))),
        patch("httpx.get", side_effect=responses) as get,
    ):
        data, content_type = _safe_http_get(
            "https://graph.microsoft.com/v1.0/image",
            headers={"Authorization": "Bearer secret"},
            allowed_hosts={"graph.microsoft.com"},
        )

    assert data == b"image"
    assert content_type == "image/png"
    assert validated == [
        ("https://graph.microsoft.com/v1.0/image", {"graph.microsoft.com"}),
        ("https://cdn.example.net/image.png", None),
    ]
    assert get.call_args_list[0].kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert get.call_args_list[1].kwargs["headers"] == {}
