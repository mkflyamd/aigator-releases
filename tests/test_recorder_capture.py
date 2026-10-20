import os

from routes import recorder as rec


def test_is_windows_constant_matches_platform():
    assert rec._IS_WINDOWS == (os.name == "nt")
