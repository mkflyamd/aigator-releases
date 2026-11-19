from oauth import dcr

ISSUER = "https://www.producthunt.com/mcp/oauth"
PATH_INSERTED = "https://www.producthunt.com/.well-known/oauth-authorization-server/mcp/oauth"
AS_DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "registration_endpoint": f"{ISSUER}/register",
}


def _fake_fetch(published: dict):
    def fetch(url):
        return published.get(url)
    return fetch


def test_path_issuer_resolves_via_rfc8414_path_insertion(monkeypatch):
    monkeypatch.setattr(dcr, "_fetch_json", _fake_fetch({PATH_INSERTED: AS_DOC}))
    meta = dcr._resolve_as_from_protected_resource({"authorization_servers": [ISSUER]})
    assert meta == AS_DOC


def test_path_issuer_tries_path_insertion_before_appended_forms():
    urls = dcr._as_metadata_urls(ISSUER)
    assert urls[0] == PATH_INSERTED
    assert urls[1] == "https://www.producthunt.com/.well-known/openid-configuration/mcp/oauth"
    assert f"{ISSUER}/.well-known/oauth-authorization-server" in urls


def test_pathless_issuer_keeps_existing_candidates():
    assert dcr._as_metadata_urls("https://auth.example.com") == [
        "https://auth.example.com/.well-known/oauth-authorization-server",
        "https://auth.example.com/.well-known/openid-configuration",
        "https://auth.example.com",
    ]


def test_appended_form_still_resolves(monkeypatch):
    appended = f"{ISSUER}/.well-known/oauth-authorization-server"
    monkeypatch.setattr(dcr, "_fetch_json", _fake_fetch({appended: AS_DOC}))
    meta = dcr._resolve_as_from_protected_resource({"authorization_servers": [ISSUER]})
    assert meta == AS_DOC
