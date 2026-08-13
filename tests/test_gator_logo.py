from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_dock_home_uses_the_canonical_gator_logo():
    html = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    dock_home = html.split('id="dock-home"', 1)[1].split("</button>", 1)[0]

    assert 'class="gator-logo-mark"' in dock_home
    assert 'src="/logo"' in dock_home
    assert "gator-svg" not in dock_home
