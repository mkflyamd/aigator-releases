"""Tests for config migration: legacy api_key → llm_profiles."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

from config import migrate_llm_config


def test_migration_creates_profile_from_api_key():
    cfg = {"api_key": "mykey", "gateway_user_id": "jsmith"}
    changed = migrate_llm_config(cfg)
    assert changed
    assert len(cfg["llm_profiles"]) == 1
    p = cfg["llm_profiles"][0]
    assert p["api_key"] == "mykey"
    assert p["user_id"] == "jsmith"
    assert p["type"] == "gateway"
    assert cfg["llm_active_profile"] == p["id"]


def test_migration_removes_legacy_keys():
    cfg = {"api_key": "mykey", "gateway_user_id": "jsmith"}
    migrate_llm_config(cfg)
    assert "api_key" not in cfg
    assert "gateway_user_id" not in cfg


def test_migration_noop_when_profiles_exist():
    existing = [{"id": "x", "name": "Existing"}]
    cfg = {"llm_profiles": existing, "api_key": "mykey"}
    changed = migrate_llm_config(cfg)
    assert not changed
    assert cfg["llm_profiles"] is existing


def test_migration_noop_when_no_api_key():
    cfg = {"gateway_user_id": "jsmith"}
    changed = migrate_llm_config(cfg)
    assert not changed
    assert "llm_profiles" not in cfg


def test_migration_uses_custom_gateway_url():
    cfg = {"api_key": "mykey", "llm_gateway_url": "https://corp.example.com/llm"}
    migrate_llm_config(cfg)
    assert cfg["llm_profiles"][0]["base_url"] == "https://corp.example.com/llm"
