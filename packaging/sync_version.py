import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def main() -> None:
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(
            f"version.txt must contain a semantic version, got {version!r}"
        )

    for relative_path in ("shell/package.json", "shell/package-lock.json"):
        path = ROOT / relative_path
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = version
        if relative_path.endswith("package-lock.json"):
            data["packages"][""]["version"] = version
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
