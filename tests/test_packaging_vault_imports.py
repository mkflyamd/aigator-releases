from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_spec_bundles_keyring_backends_off_windows():
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    assert "keyring.backends" in spec
    assert 'copy_metadata("keyring")' in spec
    assert 'sys.platform != "win32"' in spec


def test_dependencies_are_declared_for_non_windows():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    reqs = (ROOT / "web" / "requirements.txt").read_text(encoding="utf-8")
    assert "keyring" in pyproject and "cryptography" in pyproject
    assert "keyring" in reqs and "cryptography" in reqs
