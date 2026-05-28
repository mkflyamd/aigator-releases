import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch
from routes.marketplace import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

CATALOG = [
    {"id": "powerbi", "name": "Power BI", "tier": "Verified", "description": "",
     "version": "1.0", "install_url": "", "install_count": 0, "category": "", "license": "", "has_tools": False, "source": "verified"},
    {"id": "gmail", "name": "Gmail", "tier": "Community", "description": "",
     "version": "1.0", "install_url": "", "install_count": 0, "category": "", "license": "", "has_tools": False, "source": "clawhub"},
]

def test_no_tier_filter_returns_all():
    with patch("routes.marketplace.fetch_catalog", return_value=CATALOG), \
         patch("routes.marketplace._load_config", return_value={"marketplace_enabled": True}), \
         patch("routes.marketplace._load_native_skills", return_value=[]):
        r = client.get("/api/marketplace/catalog")
    assert r.json()["count"] == 2

def test_allowed_tiers_filters_community():
    cfg = {"marketplace_enabled": True, "marketplace_allowed_tiers": ["Native", "Verified"]}
    with patch("routes.marketplace.fetch_catalog", return_value=CATALOG), \
         patch("routes.marketplace._load_config", return_value=cfg), \
         patch("routes.marketplace._load_native_skills", return_value=[]):
        r = client.get("/api/marketplace/catalog")
    data = r.json()
    assert data["count"] == 1
    assert data["skills"][0]["id"] == "powerbi"

def test_marketplace_disabled_returns_empty():
    with patch("routes.marketplace._load_config", return_value={"marketplace_enabled": False}):
        r = client.get("/api/marketplace/catalog")
    assert r.json()["skills"] == []
    assert r.json()["disabled"] is True
