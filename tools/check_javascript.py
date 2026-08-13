import subprocess
import sys


def main() -> int:
    for filename in sys.argv[1:]:
        result = subprocess.run(["node", "--check", filename])
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
