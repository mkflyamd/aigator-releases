import json

import pytest


@pytest.fixture(autouse=True)
def _all_tiers_allowed(tmp_path):
    """Route tests install Community skills, so give them an admin policy that allows every tier.

    The default (every tier allowed) and the narrowed lists are tested in test_governance.py, which removes this file.
    """
    from sandbox import policy

    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified", "Community", "Mine"]}), encoding="utf-8"
    )
    policy._reset_cache()
    yield
    policy._reset_cache()
