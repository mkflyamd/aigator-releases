"""The Confluence edit-form PUT must reject malformed markup with a clear,
human-readable message BEFORE it reaches Confluence — never let an opaque
parse 400 bubble up, and never PUT body that we know will fail.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app


def test_malformed_body_rejected_before_put():
    client = TestClient(app)
    with patch("skills.confluence.api.confluence_api") as api:
        r = client.put("/api/confluence/page/123", json={
            "title": "Doc",
            "body": "<ul><li>one<li>two</li></ul>",  # one </li> short
            "version": 4,
        })
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "can't be saved" in detail.lower() or "isn't balanced" in detail.lower()
    # The PUT must NOT have been attempted.
    assert not any(c.args and c.args[0] == "PUT" for c in api.call_args_list)


def test_well_formed_body_passes_through_to_put():
    client = TestClient(app)
    with patch("skills.confluence.api.confluence_api") as api, \
         patch("skills.confluence.api.confluence_browse_url", return_value="https://wiki"):
        api.return_value = {"id": "123", "title": "Doc",
                            "version": {"number": 5}, "_links": {"webui": "/x"}}
        r = client.put("/api/confluence/page/123", json={
            "title": "Doc",
            "body": "<ul><li>one</li><li>two</li></ul>",
            "version": 4,
        })
    assert r.status_code == 200
    assert r.json()["updated"] is True
    assert any(c.args and c.args[0] == "PUT" for c in api.call_args_list)
