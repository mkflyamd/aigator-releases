import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
PATTERN = re.compile(r"(?<![A-Za-z_])(teams_token|skype_token|skypetoken|\.pkce_pending)\.?json|token\.json")
ALLOWED = {
    "secure_store.py",                      # legacy migration table
    "graph_client.py",                      # legacy TOKEN_FILE symbols (canonical + 7 wrappers)
}


def test_no_module_references_plaintext_token_files():
    offenders = []
    for path in WEB.rglob("*.py"):
        if "tests" in path.parts or path.name in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if PATTERN.search(text):
            offenders.append(str(path.relative_to(WEB)))
    assert offenders == []
