"""Turns GitHub's "SAML SSO not authorized" refusal into a chat card instead of a raw error."""
import re

from . import credentials, gh_cli

_ACCOUNT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?")
_SAML = re.compile(r"SAML", re.IGNORECASE)
_ORG_FROM_URL = re.compile(r"/orgs/([^/\s?#]+)/sso")
_ORG_FROM_TEXT = re.compile(r"The '([^']+)' organization")
_ORG_NAME = re.compile(r"[A-Za-z0-9_.-]+")

GUIDANCE = (
    "GitHub needs the user to authorize their sign-in for this organization (SAML SSO). An authorization card "
    "with an 'Open authorization page' button is now shown in the chat. Tell the user in one sentence that "
    "authorization is needed and the card is below, then stop; do not paste the error text or links, and do "
    "not open the public page or call other tools meanwhile. When the user says they authorized, retry the "
    "same GitHub request."
)


def _host() -> str:
    return credentials.get_base_url() if credentials.is_enterprise() else "https://github.com"


def card_for(text: str, owner: str = "") -> dict | None:
    if not text or not _SAML.search(text):
        return None
    org = ""
    for pattern in (_ORG_FROM_URL, _ORG_FROM_TEXT):
        found = pattern.search(text)
        if found and _ORG_NAME.fullmatch(found.group(1)):
            org = found.group(1)
            break
    if not org and _ORG_NAME.fullmatch(owner or ""):
        org = owner
    if not org:
        return None
    url = f"{_host()}/orgs/{org}/sso"
    # The one-time link GitHub puts in the error authorizes that very token; the plain page only
    # authorizes the browser session.
    link = re.search(re.escape(url) + r"\?authorization_request=[A-Za-z0-9_-]+", text)
    return {"org": org, "url": link.group(0) if link else url}


def _active_account() -> str:
    """The login gh runs as. The one-time link only opens for that account, so the card names it."""
    got = gh_cli.run_gh(["api", "user", "--jq", ".login"], use_saved_token=False)
    login = (got.get("stdout") or "").strip()
    return login if not got.get("error") and _ACCOUNT.fullmatch(login) else ""


def read_as_other_account(args, **kw) -> dict | None:
    """Retry a read-only gh command as each other signed-in login, one command at a time, without
    changing which account gh uses by default. Returns the first success, else None."""
    if not gh_cli.is_read_only(args):
        return None
    for login in gh_cli.other_accounts():
        got = gh_cli.run_gh(args, as_account=login, **kw)
        if not got.get("error"):
            return got
    return None


def needs_authorization(card: dict) -> dict:
    account = _active_account()
    if account:
        card = {**card, "account": account}
    others = gh_cli.other_accounts()
    if others:
        card = {**card, "others": others}
    return {
        "error": f"GitHub SSO authorization needed for {card['org']}. Use the authorization card in the chat.",
        "_github_sso": card,
        "assistant_guidance": GUIDANCE,
    }
