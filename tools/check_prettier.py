import subprocess
import sys


def main() -> int:
    if len(sys.argv) == 1:
        return 0
    return subprocess.run(["prettier", "--check", *sys.argv[1:]]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
