# Durable Demo Project State — Design

Sub-project 3 of the issue #55 Demo Recorder overhaul (mkflyamd/aigator-releases #55). Foundation for sub-projects 2, 4, 5, 6 and 7.

## Problem

A demo's state is scattered and global:

- Recordings land in a flat `~/Downloads/gator_demos/demo_<timestamp>/` folder (`OUT_DIR`, `web/routes/recorder.py:21`) with raw segments, stitched file, ffmpeg log and final output side by side.
- "Latest" is two singleton files, `~/.gator/latest_output.json` and `~/.gator/narration_pending.json`. A second demo overwrites the first; nothing ties narration, media or output to one demo.
- The in-memory session (`_session_dir`, `_session_tag`, `_segments`, `recorder.py:95-105`) is lost on restart, so a half-finished demo cannot be resumed.
- The output root is hard-coded.

## Goals

1. Every demo is a **project** with a stable ID kept from first recording through delivery.
2. A human-readable `project.json` in the user-visible project folder is the record of the project.
3. A fixed folder layout separates deliverables from working files.
4. The output root is configurable: global default in Settings, per-project root chosen at creation with a native "Save project to…" picker.
5. A recent-projects index in `~/.gator` survives restarts.
6. Existing flat `demo_*` folders are adopted without losing files.
7. The project-keyed API replaces the `latest-output` singleton.
8. The skill learns the active project without making unauthenticated mutating HTTP calls.

Non-goals: moving an existing project to another root, deleting projects, multi-user sharing. The narration editor UI, media import and approval transaction belong to sub-projects 7, 6 and 2.

## Layout

```
<root>/<project_id>/
  project.json
  final/                 delivered video(s) — the only folder a user needs to open
  previous/              prior finals, moved here by archive_final()
  source/                raw captures and imported media
    seg_00.mp4 ...       recorder segments
    recording.mp4        stitched raw recording
  work/
    normalized/          normalized clips (sub-project 6)
    frames/              extracted frames
    tts/                 narration audio
    logs/                ffmpeg_log.txt and pipeline logs
    narration.json       approved narration (written by the backend)
```

`project_id` is `demo_YYYYMMDD_HHMMSS` (same shape as today's folder tag), with `_2`, `_3` appended on collision. Default root is `~/Downloads/gator_demos/`.

## project.json (schema_version 1)

```json
{
  "schema_version": 1,
  "project_id": "demo_20261019_143012",
  "name": "demo_20261019_143012",
  "created_at": "2026-10-19T14:30:12+00:00",
  "updated_at": "2026-10-19T14:41:50+00:00",
  "stage": "recorded",
  "segments": ["source/seg_00.mp4", "source/seg_01.mp4"],
  "raw": "source/recording.mp4",
  "narration": {"approved_at": "2026-10-19T14:40:00+00:00"},
  "ext": {}
}
```

- Paths inside `project.json` are relative to the project folder, so the folder can be moved or synced.
- `stage` is one of `created`, `recording`, `recorded`, `narration_approved`, `delivered`.
- `ext` is a dict keyed by sub-project (`"approval"`, `"media"`, ...). Other sub-projects store their fields there through `set_ext()`; SP3 does not interpret it.
- The backend is the only writer, using an atomic temp-file-and-rename write.

**Disk is the truth for artifacts.** When a file exists in `final/`, `get_project()` reports stage `delivered` in place of a stored `recorded` or `narration_approved`. `final` is never stored; `get_project()` derives it as the newest file in `final/`, and the legacy `final` and `raw` paths are derived the same way. Pipeline code (the agent) delivers by writing a file into `final/`; nothing needs to register it.

## Project store module

New `web/demo_projects.py`, no FastAPI dependency, importable by `recorder.py` and routes.

```python
DEFAULT_ROOT: Path            # ~/Downloads/gator_demos
INDEX_PATH: Path              # GATOR_DIR / "demo_projects.json"

def atomic_write_json(path: Path, data: dict) -> None
def get_default_root() -> Path                  # config key demo_projects_root, else DEFAULT_ROOT
def set_default_root(root: str | None) -> Path  # validates absolute + writable; None resets
def create_project(name: str | None = None, root: Path | None = None) -> dict
def get_project(project_id: str) -> dict        # project.json + derived artifacts + absolute paths
def list_projects() -> list[dict]               # recent first; adopts legacy folders
def get_active_id() -> str | None
def set_active(project_id: str) -> None
def update_project(project_id: str, **fields) -> dict     # name, stage, segments, raw, narration
def set_ext(project_id: str, namespace: str, value: dict) -> dict
def project_path(project_id: str) -> Path
def archive_final(project_id: str) -> list[Path]          # moves final/* into previous/<UTC stamp>_<name>
def resolve_file(project_id: str, rel: str) -> Path       # raises ValueError if outside the project folder
def adopt_legacy_folder(folder: Path) -> dict
def begin_session(project_id: str | None = None) -> dict  # continue project_id, or create; sets active
def save_narration(project_id: str, segments: list, flags: dict) -> dict
```

Index file `~/.gator/demo_projects.json`:

```json
{"schema_version": 1, "active_project_id": "demo_20261019_143012",
 "projects": [{"project_id": "demo_20261019_143012", "name": "...", "path": "C:/.../demo_20261019_143012", "updated_at": "..."}]}
```

The index is the lookup from ID to folder (a project can live under any root). It holds at most 50 entries, most recently updated first. If a folder in the index no longer exists, `list_projects()` drops the entry.

### Legacy adoption

A folder under the default root matching `demo_\d{8}_\d{6}` with no `project.json` is adopted by `list_projects()`: create the layout; move `seg_*.mp4` to `source/`, `ffmpeg_log.txt` to `work/logs/`, and `<id>_final.mp4` (which the old recorder wrote as the stitched raw recording, not a deliverable) to `source/recording.mp4`; write `project.json` with stage `recorded` if a stitched file exists, else `created`. Other files stay in place. The recorder always writes `project.json` when it starts a session, so an active recording is never adopted. Adoption is idempotent.

## Root selection

- Global default: `config.json` key `demo_projects_root` (absolute path string). Settings → General shows it with Change and Reset buttons.
- Per project: `POST /api/demo-projects` accepts `root`. The chosen folder is where `<project_id>/` is created and is recorded as the project's `path` in the index.
- Native picker: Electron IPC `demo:pick-folder` (`shell/main.js`, next to `skill:pick-local`) opens `showOpenDialog` with `openDirectory` and `createDirectory`, exposed as `window.gatorShell.pickDemoFolder()` returning `{ok, path}`. The Demo Recorder widget is a sandboxed iframe, so it asks through a new `gator:pick-demo-folder` postMessage case in `app.js`; the reply is `gator:pick-demo-folder-result`.
- Validation (`set_default_root`, and `create_project` when `root` is given): path must be absolute, creatable, and pass a write probe. Failure raises `ValueError`, and routes return 400.

## API

All under `/api/demo-projects`. Every POST/PUT carries `dependencies=[Depends(verify_csrf)]`.

| Route | Purpose |
|---|---|
| `GET /settings` | `{default_root, is_default}` |
| `PUT /settings` | body `{root: str \| null}`; sets or resets the global default |
| `GET /` | recent projects, newest first |
| `POST /` | body `{name?, root?}`; creates and activates a project |
| `GET /active` | the active project (404 if none) |
| `GET /{id}` | project with derived `final`, `raw`, absolute paths |
| `POST /{id}/activate` | makes it the active project |
| `POST /{id}/narration` | body `{segments, flags}`; writes `work/narration.json`, sets stage `narration_approved` |
| `GET /{id}/file?rel=` | serves a file inside the project folder (mp4/mp3/m4a), 403 outside it |

`GET /settings` is declared before `GET /{id}`.

### CSRF and the agent

Agent-run code cannot hold the CSRF token (by design, `web/security.py`), so the agent never calls a mutating route. The split:

- **UI-called (CSRF):** create, activate, settings, narration approval. These are called from `app.js` and the widget bridge, which attach `X-CSRF-Token`.
- **Agent reads files, writes files:** the agent reads `~/.gator/demo_projects.json` for the active project folder, reads `work/narration.json`, writes `work/tts/`, `work/logs/` and the deliverable into `final/`. No agent HTTP writes.

### Existing recorder routes

| Existing | New behavior |
|---|---|
| `POST /api/recorder/start` | `StartRequest` gains `project_id: str \| None`. With it, the segments continue that project; without it, a project is created under the default root and activated. Segments go to `source/seg_NN.mp4`; the ffmpeg log to `work/logs/ffmpeg_log.txt`. Response keeps `session_dir` (now the project folder) and adds `project_id`. |
| `POST /api/recorder/stop` | Stitched output goes to `source/recording.mp4`; project stage becomes `recorded`; `segments` and `raw` are saved. Response keeps `path` (the raw recording) and adds `project_id`. It no longer writes `latest_output.json`. |
| `GET /api/recorder/latest-output` | Returns `{raw, final, timestamp, project_id}` derived from the active project; 404 when there is none. Kept so already-saved widgets keep working. |
| `POST /api/recorder/set-output` | Removed from the skill. The route remains as a shim that, when `final` is under the active project folder, does nothing further (disk already shows it); otherwise returns 400. |
| `POST /api/recorder/narration-approved` | Delegates to the project's `narration` route logic for the active project; still writes `~/.gator/narration_pending.json` so older skill copies keep working. |
| `GET /api/recorder/serve-file` | Allowed set widens from `OUT_DIR` to the folder of any project in the index. |

`/status` (`recorder.py:984-1021`) adds `project_id`.

## SKILL.md changes

`web/skills/gator-demo-recorder/SKILL.md` references the singleton flow at lines 34, 485, 722, 757, 765, 808, 829-834, 881-899. Replace them with a "Project folder" section near the top plus this resolver snippet, used wherever the skill needs a path:

```python
import json, pathlib
idx = json.loads((pathlib.Path.home() / ".gator" / "demo_projects.json").read_text(encoding="utf-8"))
proj = next(p for p in idx["projects"] if p["project_id"] == idx["active_project_id"])
PROJECT_DIR = pathlib.Path(proj["path"])
```

Phase 4 writes TTS audio to `PROJECT_DIR/work/tts`, logs to `PROJECT_DIR/work/logs`, the merged deliverable to `PROJECT_DIR/final/<name>.mp4`, and reads approved narration from `PROJECT_DIR/work/narration.json`. The `set-output` and `latest-output` calls are deleted from the skill. `scripts/tts_pipeline.py` and `scripts/preflight.py` take their directories from arguments; any `gator_demos` literal in them is replaced.

## recorder.py seams shared with sub-project 4

SP3 changes only these places; SP4 must leave them intact or coordinate:

| Lines (ref tree) | Change |
|---|---|
| 21 | `OUT_DIR` stays as the legacy default for `serve-file` fallback only |
| 95-105 | `_session_dir` / `_session_tag` kept as names, now set from the project (`_session_dir = project folder`, `_session_tag = project_id`) |
| 655-660 | `_start_segment` writes `source/seg_NN.mp4` and `work/logs/ffmpeg_log.txt` |
| 756-759 | session creation replaced by `begin_session()` (create or reuse project) |
| 789-790 | start response `path` and `session_dir` |
| 937-954 | stop: stitched path and the `_write_latest_output` call |
| 965-981 | `_write_latest_output` deleted |
| 984-1021 | `/status` adds `project_id` |
| 1033-1087 | `latest-output`, `set-output`, `narration-approved` become shims |
| 1144-1161 | `serve-file` allowed set |

Pause/resume (`801-885`) change only through `_start_segment`.

## Interfaces for other sub-projects

- **SP2 (approval transaction, skill pinning):** store approval fields with `set_ext(project_id, "approval", {...})`. The approval route is UI-called with CSRF, keyed by `project_id`. Stage `narration_approved` is already set by the narration route; SP2 may tighten it behind its transaction.
- **SP4 (recorder fixes 1-5):** use the seam table above. Recorder state globals keep their names. A new project is created in `begin_session()`; do not create folders elsewhere.
- **SP5 (media provenance and ops):** record provenance in `ext["media"]`; write operation logs under `work/logs/`; call `archive_final()` before replacing a final. Deliverables go in `final/`.
- **SP6 (media intake, multi-clip):** imported media goes to `source/` (originals untouched), normalized copies to `work/normalized/`, frames to `work/frames/`. Continuing a project with new clips uses `StartRequest.project_id`.
- **SP7 (narration editor UX):** the editor reads `GET /{id}`, saves approval through `POST /{id}/narration`. "Open final folder" opens `get_project(id)["final_dir"]`, replacing the Download control. Playback uses `GET /{id}/file`.

`get_project()` returns, in addition to `project.json` fields: `path`, `final_dir`, `final` (absolute path of newest file in `final/` or `null`), `raw` (absolute or `null`), `segments` (absolute).

## Testing

- `tests/demo_project_state/test_store.py`: layout creation, ID collision, atomic write leaves no temp file, relative paths, derived `final`, `archive_final`, `resolve_file` traversal rejection, root validation, index trim and stale-entry drop, legacy adoption (including idempotence).
- `tests/demo_project_state/test_routes.py`: every route, CSRF rejection on each POST/PUT, 403 on traversal, `GET /settings` not shadowed by `/{id}`, `latest-output` shim derived from the active project, `narration-approved` writes both files.
- `tests/test_csrf_route_inventory.py` passes with no baseline change.
- `tests/demo_project_bridge.test.js`: the `gator:pick-demo-folder` case replies with the picker result.

## Decisions

1. Folder layout is `final/`, `previous/`, `source/`, `work/{normalized,frames,tts,logs}` with `project.json` at the top; `previous/` is a sibling of `final/`.
2. Project ID keeps the existing `demo_YYYYMMDD_HHMMSS` shape.
3. `project.json` stores relative paths; the index stores the absolute folder.
4. Disk is the truth for artifacts: `final` is derived from `final/`, never registered.
5. The agent never calls mutating routes; it reads `~/.gator/demo_projects.json` and writes files. This resolves the CSRF constraint.
6. `ext` namespaces let later sub-projects add fields without schema changes.
7. Config key `demo_projects_root` holds the global default; the per-project root is the folder chosen at creation.
8. Legacy `latest-output`, `set-output` and `narration-approved` stay as shims so saved widgets and older skill copies keep working.
9. Moving a project to another root and deleting projects are out of scope.
10. Legacy folders are adopted by moving files into the new layout on first listing.
