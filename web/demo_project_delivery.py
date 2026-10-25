import json
from pathlib import Path

import demo_projects as dp

PROGRESS_REL = Path("work") / "logs" / "merge_progress.json"


def _dir_bytes(folder):
    total = 0
    for f in Path(folder).rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _rel_inside(root, target):
    if not target:
        return None
    try:
        return Path(target).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        return None


def project_summary(project_id):
    proj = dp.get_project(project_id)
    root = Path(proj["path"])
    final = proj["final"]
    return {
        "project_id": project_id,
        "path": str(root),
        "final_dir": str(proj["final_dir"]),
        "final": str(final) if final else None,
        "final_rel": (Path("final") / Path(final).name).as_posix() if final else None,
        "raw_rel": _rel_inside(root, proj.get("raw")),
        "source_count": len(proj["segments"]),
        "work_bytes": _dir_bytes(root / "work"),
    }


def read_progress(project_id):
    root = Path(dp.get_project(project_id)["path"])
    try:
        data = json.loads((root / PROGRESS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "none"}
    return data if isinstance(data, dict) else {"state": "none"}
