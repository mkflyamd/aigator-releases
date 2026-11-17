"""Identity is the Microsoft account email read from the stored Graph token claims."""

import base64
import json

import identity
import secure_store


def _token(claims: dict) -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


def test_upn_is_preferred_and_lowercased():
    t = _token({"upn": "Jane.Doe@amd.com", "preferred_username": "other@amd.com", "email": "x@amd.com"})
    assert identity.email_from_token(t) == "jane.doe@amd.com"


def test_falls_back_to_preferred_username_then_email():
    assert identity.email_from_token(_token({"preferred_username": "a@amd.com", "email": "b@amd.com"})) == "a@amd.com"
    assert identity.email_from_token(_token({"email": "b@amd.com"})) == "b@amd.com"


def test_claim_without_an_at_sign_gives_no_email():
    assert identity.email_from_token(_token({"upn": "jane"})) == ""


def test_malformed_or_empty_token_gives_no_email():
    assert identity.email_from_token("not-a-jwt") == ""
    assert identity.email_from_token("") == ""


def test_get_identity_reads_the_stored_token_even_when_expired():
    secure_store.set_json(
        "graph/token",
        {"access_token": _token({"upn": "jane.doe@amd.com", "name": "Jane Doe", "exp": 1}), "expires_at": 1},
    )
    assert identity.get_identity() == {"id": "jane.doe@amd.com", "name": "Jane Doe"}


def test_get_identity_is_none_without_a_token():
    assert identity.get_identity() is None
