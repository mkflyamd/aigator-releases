import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str], cwd: Path = ROOT) -> int:
    return subprocess.run(command, cwd=cwd).returncode


def main() -> int:
    if run(["uv", "audit", "--locked"]):
        return 1
    if run(
        ["npm", "audit", "--package-lock-only", "--audit-level=high"], ROOT / "shell"
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
