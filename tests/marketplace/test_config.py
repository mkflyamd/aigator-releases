import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from config import PATCHABLE_CONFIG_KEYS, INSTALLED_SKILLS_DIR

def test_marketplace_keys_patchable():
    assert "marketplace_enabled" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_allowed_tiers" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_clawhub_url" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_verified_url" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_enterprise_url" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_anthropic_enabled" in PATCHABLE_CONFIG_KEYS

def test_installed_skills_dir():
    assert INSTALLED_SKILLS_DIR == Path.home() / ".gator" / "skills"
