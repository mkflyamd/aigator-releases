import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from unittest.mock import patch
from marketplace.registry import merge_catalogs, normalize_entry, _fetch_json_url

SAMPLE_ENTRY = {
    "id": "powerbi", "name": "Power BI", "description": "Read Power BI reports",
    "version": "1.0.0", "tier": "Verified", "install_url": "https://example.com/powerbi.gator",
    "install_count": 100, "category": "Productivity", "license": "MIT", "has_tools": False
}

def test_merge_dedup():
    a = [dict(SAMPLE_ENTRY)]
    b = [dict(SAMPLE_ENTRY, name="Power BI duplicate")]
    result = merge_catalogs([a, b])
    assert len(result) == 1
    assert result[0]["name"] == "Power BI"  # first source wins

def test_merge_unique():
    a = [dict(SAMPLE_ENTRY)]
    b = [dict(SAMPLE_ENTRY, id="gmail", name="Gmail")]
    result = merge_catalogs([a, b])
    assert len(result) == 2

def test_normalize_defaults():
    minimal = {"id": "test", "name": "Test", "description": "desc"}
    result = normalize_entry(minimal)
    assert result["tier"] == "Community"
    assert result["has_tools"] is False
    assert result["install_count"] == 0
    assert result["category"] == ""

def test_fetch_error_handling():
    with patch("urllib.request.urlopen", side_effect=Exception("network error")):
        result = _fetch_json_url("https://example.com/bad.json")
    assert result == []
