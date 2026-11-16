import json

import pytest


@pytest.fixture(autouse=True)
def _all_tiers_allowed(tmp_path):
    from sandbox import policy

    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified", "Community", "Mine"]}), encoding="utf-8"
    )
    policy._reset_cache()
    yield
    policy._reset_cache()
