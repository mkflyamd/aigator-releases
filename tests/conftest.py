"""pytest configuration — adds web/ to sys.path so bare imports like
'import shared' resolve correctly when testing web.routes modules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))
