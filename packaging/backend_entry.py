import argparse
import multiprocessing
import os
import runpy
import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def run_python(arguments: list[str]) -> None:
    if not arguments:
        raise SystemExit("Python arguments are required after --run-python")

    if arguments[0] == "-c":
        if len(arguments) < 2:
            raise SystemExit("Python source is required after -c")
        sys.argv = ["-c", *arguments[2:]]
        exec(compile(arguments[1], "<string>", "exec"), {"__name__": "__main__"})
        return

    if arguments[0] == "-m":
        if len(arguments) < 2:
            raise SystemExit("A module name is required after -m")
        sys.argv = [arguments[1], *arguments[2:]]
        runpy.run_module(arguments[1], run_name="__main__", alter_sys=True)
        return

    if arguments[0] == "-":
        sys.argv = ["-", *arguments[1:]]
        exec(compile(sys.stdin.read(), "<stdin>", "exec"), {"__name__": "__main__"})
        return

    script_path = Path(arguments[0]).resolve()
    sys.argv = [str(script_path), *arguments[1:]]
    sys.path[0] = str(script_path.parent)
    runpy.run_path(str(script_path), run_name="__main__")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--run-python", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.run_python is not None:
        run_python(args.run_python)
        return

    root = resource_root()
    os.chdir(root)
    web_dir = root / "web"
    for candidate in (str(root), str(web_dir)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)

    import uvicorn
    from web.app import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
