"""Tests for the Google Workspace MCP preset endpoint.

The preset at /api/config/mcp/presets/google is the single source of truth for
the "Connect Google" wizard in the modal. The frontend reads it to know which
servers to register, which OAuth scopes to request, and the redirect URI the
user must register in their Google Cloud Console.

These tests pin the preset's shape so a refactor can't silently break the
wizard's contract with the backend. The MCP URLs here MUST match the entries
in mcp/url_fetcher.py:_KNOWN_DOC_URLS so a user who later pastes a
developers.google.com doc URL lands on the same connection record.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

def _preset():
    """Return the static route payload without starting the full app lifespan.

    This contract suite validates the preset definition, not startup workers,
    schedulers, browser cleanup, or MCP supervision. Calling the synchronous
    route handler directly keeps that unrelated application lifecycle out of
    every assertion and avoids platform-specific TestClient startup hangs.
    """
    from routes.mcp_routes import get_google_preset
    return get_google_preset()


def test_preset_endpoint_returns_google_workspace_definition():
    data = _preset()
    assert data['id'] == 'google-workspace'
    assert data['label'] == 'Google Workspace'


def test_preset_has_single_workspace_server():
    """The preset uses a single workspace-mcp server covering both Gmail and
    Calendar (plus Docs, Sheets, etc.) — one connection, one auth. Runs over
    HTTP (streamable-http on a local port), not stdio — stdio blocks on the
    server's internal OAuth flow before tool discovery can complete."""
    data = _preset()
    assert len(data['servers']) == 1
    server = data['servers'][0]
    assert server['name'] == 'Google Workspace'
    assert server['transport'] == 'http'
    assert server['command'] == 'uvx'
    assert 'workspace-mcp' in server['args']


def test_preset_server_has_env_mapping():
    """The server declares env_mapping so the wizard can inject credentials
    from shared config. This is the generic mechanism — works for any preset."""
    data = _preset()
    server = data['servers'][0]
    assert 'env_mapping' in server
    assert 'GOOGLE_OAUTH_CLIENT_ID' in server['env_mapping']
    assert 'GOOGLE_OAUTH_CLIENT_SECRET' in server['env_mapping']
    # The mapping values are config keys, not the actual secrets
    assert server['env_mapping']['GOOGLE_OAUTH_CLIENT_ID'] == 'google_oauth_client_id'
    assert server['env_mapping']['GOOGLE_OAUTH_CLIENT_SECRET'] == 'google_oauth_client_secret'


def test_preset_includes_redirect_uri_and_console_url():
    """The wizard shows the user the redirect URI they must register in their
    Google Cloud Console. If this is missing or wrong, OAuth fails at the
    redirect step with a confusing 'redirect_uri mismatch' error."""
    data = _preset()
    assert data['redirect_uri'].startswith('http://127.0.0.1:')
    assert data['redirect_uri'].endswith('/oauth/callback')
    assert data['console_url'].startswith('https://')


def test_preset_flags_developer_preview():
    """Google's MCP servers are in Developer Preview — the wizard must surface
    this so users know tool names/schemas may change before GA."""
    data = _preset()
    assert data['preview'] is True
    assert data['preview_note']
    assert 'Preview' in data['preview_note']


def test_preset_server_names_slugify_to_disambiguation_rule_matches():
    """The connection name the wizard passes to /api/config/mcp determines the
    connection id: 'mcp-' + slugify(name). The chat disambiguation rule at
    chat.py:1357 tells the LLM to honor explicit signals like 'gmail' and
    'outlook'. So 'Gmail' must slugify to 'gmail' and 'Google Calendar' to
    'google-calendar' for the rule to fire when the user types those words."""
    from mcp.manager import _slugify
    data = _preset()
    for server in data['servers']:
        slug = _slugify(server['name'])
        if server['name'] == 'Gmail':
            assert slug == 'gmail', f"'Gmail' must slugify to 'gmail' (got {slug!r})"
        elif server['name'] == 'Google Calendar':
            assert slug == 'google-calendar', (
                f"'Google Calendar' must slugify to 'google-calendar' (got {slug!r})"
            )


def test_preset_http_servers_match_url_fetcher_known_doc_urls():
    """HTTP MCP servers backed by Google's own remote endpoint (e.g. Drive)
    must match the hardcoded entries in url_fetcher.py:_KNOWN_DOC_URLS, so a
    user who connects via the wizard and later pastes the doc URL doesn't
    create a duplicate connection. Stdio servers (no URL) and servers backed
    by a local subprocess (loopback URL, e.g. workspace-mcp on 127.0.0.1) are
    skipped — a user would never paste a doc URL for a process running on
    their own machine, so there's no duplicate-connection risk to guard."""
    from mcp.url_fetcher import _KNOWN_DOC_URLS
    data = _preset()
    fetcher_urls = {entry['url'] for _, entry in _KNOWN_DOC_URLS if 'url' in entry}
    for server in data['servers']:
        if server.get('transport') != 'http':
            continue  # stdio servers have no URL
        url = server['url']
        if '127.0.0.1' in url or 'localhost' in url:
            continue  # local subprocess, not a remotely-documented endpoint
        assert url in fetcher_urls, (
            f"Preset URL {url} not in url_fetcher _KNOWN_DOC_URLS — "
            "the wizard and the paste-flow would create duplicate connections."
        )
