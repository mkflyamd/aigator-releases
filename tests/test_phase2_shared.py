# tests/test_phase2_shared.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

def test_outputs_dir_in_config():
    from config import OUTPUTS_DIR
    # OUTPUTS_DIR moved from ~/.config/teamspoc/outputs to ~/.gator/outputs in
    # the gator-path migration (see web/migration.py + 46cdb5a).
    assert OUTPUTS_DIR.parent.name == ".gator"
    assert OUTPUTS_DIR.name == "outputs"

def test_new_config_keys_patchable():
    from config import PATCHABLE_CONFIG_KEYS
    assert "code_runner_timeout_verified" in PATCHABLE_CONFIG_KEYS
    assert "code_runner_timeout_community" in PATCHABLE_CONFIG_KEYS
    assert "marketplace_verified_manifest_url" in PATCHABLE_CONFIG_KEYS

def test_shared_new_dicts():
    import shared
    assert hasattr(shared, "TOOL_TIER_MAP")
    assert hasattr(shared, "INSTALLED_TOOL_MODULES")
    assert hasattr(shared, "TOOL_SEMAPHORES")
    assert isinstance(shared.TOOL_TIER_MAP, dict)
    assert isinstance(shared.INSTALLED_TOOL_MODULES, dict)
    assert isinstance(shared.TOOL_SEMAPHORES, dict)
