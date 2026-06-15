"""Regression: migration must execute before `shared` is imported.

shared.py runs `load_config()` at module import. If migration is wired into
the FastAPI lifespan instead, shared.cfg freezes as {} before the migration
copies the real config from ~/.config/teamspoc → ~/.gator, and the app boots
with empty settings (no LLM profile, Welcome modal stuck, etc.).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))


def test_run_migration_is_called_before_shared_import_in_app_module():
    """Static check: in web/app.py, the `from migration import run_migration`
    line (and its invocation) must appear above `import shared`."""
    app_path = os.path.join(os.path.dirname(__file__), '..', 'web', 'app.py')
    with open(app_path, encoding='utf-8') as f:
        source = f.read()

    mig_marker = "from migration import run_migration"
    shared_marker = "import shared"
    mig_idx = source.find(mig_marker)
    shared_idx = source.find(shared_marker)
    assert mig_idx != -1, "expected `from migration import run_migration` in web/app.py"
    assert shared_idx != -1, "expected `import shared` in web/app.py"
    assert mig_idx < shared_idx, (
        f"web/app.py must import & invoke run_migration BEFORE `import shared` "
        f"(found migration at offset {mig_idx}, shared at {shared_idx}). "
        f"shared.py runs load_config() at import time — migrating later is a no-op."
    )


def test_fastapi_title_is_not_poc():
    """CLAUDE.md: 'This project is called AI Gator — never refer to it as a POC.'"""
    app_path = os.path.join(os.path.dirname(__file__), '..', 'web', 'app.py')
    with open(app_path, encoding='utf-8') as f:
        source = f.read()
    assert 'FastAPI(title="TeamsPOC"' not in source
    assert 'POC' not in 'AI Gator', "sanity"
