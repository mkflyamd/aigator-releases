import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from agent_loop import _file_chip_entries

CHIP = {"name": "report.html", "download_url": "/api/files/r1/report.html", "size_bytes": 10, "mime_type": "text/html"}


def test_downloadable_files_become_chips():
    assert _file_chip_entries({"files": [CHIP]}) == [CHIP]


def test_a_plain_list_of_paths_is_not_a_chip():
    assert _file_chip_entries({"files": ["references/DESIGN.md", "assets/logo.png"]}) == []


def test_entries_without_a_download_url_are_dropped():
    assert _file_chip_entries({"files": [{"name": "a.txt"}, CHIP]}) == [CHIP]


def test_results_without_files_give_no_chips():
    assert _file_chip_entries({"stdout": "x"}) == []
    assert _file_chip_entries("not a dict") == []
