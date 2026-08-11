import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

from config import PATCHABLE_CONFIG_KEYS, INSTALLED_SKILLS_DIR, PLUGINS_DIR, USER_SKILL_DIRS

def test_marketplace_keys_patchable():
    assert "marketplace_enabled" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_allowed_tiers" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_clawhub_url" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_verified_url" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_enterprise_url" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_anthropic_enabled" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_claude_plugins_official_enabled" in PATCHABLE_CONFIG_KEYS

def test_installed_skills_dir():
    assert INSTALLED_SKILLS_DIR == Path.home() / ".gator" / "skills"

def test_plugins_cache_is_a_user_skill_dir():
    """PLUGINS_DIR/cache must be a USER_SKILL_DIRS root so
    shared.load_installed_skill_prompts()'s recursive SKILL.md scan discovers
    skills bundled inside marketplace plugins (2026-08-07 milestone, decision #3)."""
    assert PLUGINS_DIR / "cache" in USER_SKILL_DIRS
