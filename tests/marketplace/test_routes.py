import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch
from routes.marketplace import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

SAMPLE_SKILL = {
    "id": "powerbi", "name": "Power BI", "tier": "Verified",
    "description": "Read reports", "version": "1.0", "install_url": "",
    "install_count": 0, "category": "Productivity", "license": "MIT",
    "has_tools": False, "source": "verified"
}

def test_get_catalog_returns_list():
    with patch("routes.marketplace.fetch_catalog", return_value=[SAMPLE_SKILL]), \
         patch("routes.marketplace._load_config", return_value={"marketplace_enabled": True}), \
         patch("routes.marketplace._load_native_skills", return_value=[]):
        r = client.get("/api/marketplace/catalog")
    assert r.status_code == 200
    assert r.json()["skills"][0]["id"] == "powerbi"

def test_get_installed_returns_list():
    with patch("routes.marketplace.load_installed", return_value=[]), \
         patch("routes.marketplace._load_native_skills", return_value=[]):
        r = client.get("/api/marketplace/installed")
    assert r.status_code == 200
    assert r.json()["skills"] == []

def test_install_requires_content():
    r = client.post("/api/marketplace/install",
                    json={"skill_id": "x", "skill_md": "", "install_url": ""})
    assert r.status_code == 400

def test_create_skill():
    with patch("routes.marketplace.create_user_skill", return_value={"ok": True, "skill_id": "my-wf"}):
        r = client.post("/api/marketplace/create",
                        json={"name": "My WF", "description": "desc", "instructions": "do X"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_uninstall_skill():
    with patch("routes.marketplace.uninstall_skill", return_value={"ok": True, "skill_id": "powerbi"}):
        r = client.delete("/api/marketplace/uninstall/powerbi")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_marketplace_disabled():
    with patch("routes.marketplace._load_config", return_value={"marketplace_enabled": False}):
        r = client.get("/api/marketplace/catalog")
    assert r.json()["disabled"] is True
    assert r.json()["skills"] == []
