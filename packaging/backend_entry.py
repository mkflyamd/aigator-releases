import argparse
import multiprocessing
import os
import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--run-python", type=Path)
    args = parser.parse_args()

    if args.run_python:
        script_path = args.run_python.resolve()
        os.chdir(script_path.parent)
        sys.argv = [str(script_path)]
        source = script_path.read_bytes()
        exec(compile(source, str(script_path), "exec"), {"__name__": "__main__", "__file__": str(script_path)})
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
