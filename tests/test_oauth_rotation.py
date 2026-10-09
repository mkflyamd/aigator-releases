import time

from oauth import flow, storage
from oauth.provider import OAuthProvider

FAKE = "aigator-fake-api-key"


def test_refresh_adopts_rotated_refresh_token(monkeypatch):
    prov = OAuthProvider(id="p1", mode="static", authorize_url="https://a.invalid/auth",
                         token_url="https://a.invalid/token", client_id="c")
    storage.save("p1", {"provider": prov.to_dict(),
                        "token": {"access_token": "old", "refresh_token": "r1", "expires_at": 0}})
    monkeypatch.setattr(
        flow, "_post_form",
        lambda url, params, secret="": {"access_token": FAKE, "refresh_token": "r2", "expires_in": 3600},
    )
    assert flow.get_access_token("p1") == FAKE
    assert storage.load("p1")["token"]["refresh_token"] == "r2"
