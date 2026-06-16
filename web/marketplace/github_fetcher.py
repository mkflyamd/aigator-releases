"""Fetch skill folders from GitHub via codeload tarball downloads.

Pure-function helpers — no disk writes here. The installer drives I/O."""

import io
import logging
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

MAX_FILES = 100
MAX_TOTAL_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024  # 100 MB compressed

_CODELOAD_HOST = "codeload.github.com"

_TREE_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<kind>tree|blob)/(?P<branch>[^/]+)/(?P<path>.+)$"
)
_RAW_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$"
)


def parse_github_url(url: str) -> dict:
    """Return {owner, repo, branch, path, kind} for a GitHub tree/blob/raw URL.

    kind is "folder" for tree URLs and blob URLs pointing at SKILL.md
    (caller treats parent as the skill folder). kind is "raw_file" for
    raw.githubusercontent.com URLs.

    Raises ValueError on any unsupported URL shape."""
    m = _TREE_RE.match(url)
    if m:
        path = m.group("path")
        if m.group("kind") == "blob":
            if path.lower().endswith("/skill.md"):
                path = "/".join(path.split("/")[:-1])
            elif path.lower() == "skill.md":
                raise ValueError("Blob URL points at a root-level SKILL.md; specify the repo as a tree URL instead")
            else:
                raise ValueError("Only blob URLs pointing at SKILL.md are supported")
        return {
            "owner": m.group("owner"),
            "repo": m.group("repo"),
            "branch": m.group("branch"),
            "path": path,
            "kind": "folder",
        }
    m = _RAW_RE.match(url)
    if m:
        return {
            "owner": m.group("owner"),
            "repo": m.group("repo"),
            "branch": m.group("branch"),
            "path": m.group("path"),
            "kind": "raw_file",
        }
    if url.startswith("https://github.com/"):
        raise ValueError("Unsupported URL: needs a tree/<branch>/<folder> or blob/<branch>/<file> segment; bare repo root URLs lack a folder")
    raise ValueError("Unsupported URL: only github.com and raw.githubusercontent.com are accepted")


def fetch_raw_bytes(url: str, max_bytes: int, timeout: int = 15) -> bytes:
    """Fetch a URL with host pinning to raw.githubusercontent.com over HTTPS.

    Reads at most max_bytes + 1 to detect oversize; raises ValueError on
    invalid host/scheme or oversize."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise ValueError("Invalid URL: only raw.githubusercontent.com over https is allowed")
    req = urllib.request.Request(url, headers={"User-Agent": "AIGator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Response too large (> {max_bytes} bytes)")
    return data


def download_skill_tarball(
    owner: str, repo: str, branch: str, subpath: str
) -> dict[str, bytes]:
    """Stream the repo's tar.gz from codeload, return {relative_path: bytes} for
    files under subpath. Enforces 100 MB compressed cap, MAX_TOTAL_BYTES and
    MAX_FILES extracted caps, rejects symlinks and path-traversal entries."""
    url = f"https://{_CODELOAD_HOST}/{owner}/{repo}/tar.gz/{branch}"
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.hostname != _CODELOAD_HOST:
        raise ValueError("Invalid URL: only codeload.github.com over https is allowed")

    req = urllib.request.Request(url, headers={"User-Agent": "AIGator/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("Repo or branch not found") from e
        raise ValueError(f"GitHub error {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Could not reach GitHub: {e.reason}") from e

    with resp:
        cl = resp.headers.get("Content-Length")
        if cl and int(cl) > MAX_ARCHIVE_BYTES:
            raise ValueError(
                f"Repo archive too large (>{MAX_ARCHIVE_BYTES // (1024 * 1024)} MB)"
            )
        data = resp.read(MAX_ARCHIVE_BYTES + 1)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError(
                f"Repo archive too large (>{MAX_ARCHIVE_BYTES // (1024 * 1024)} MB)"
            )

    prefix = f"{repo}-{branch}/"
    if subpath:
        prefix += subpath.strip("/") + "/"

    out: dict[str, bytes] = {}
    total_bytes = 0
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as e:
        raise ValueError(f"Invalid archive: {e}") from e

    with tf:
        for entry in tf:
            if entry.issym() or entry.islnk():
                raise ValueError("Skill archives may not contain symlinks")
            if not entry.isfile():
                continue
            if not entry.name.startswith(prefix):
                continue
            rel = entry.name[len(prefix):]
            if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
                raise ValueError(f"Invalid file path in skill archive: {rel}")
            if len(out) >= MAX_FILES:
                raise ValueError(f"Skill has too many files (> {MAX_FILES})")
            f = tf.extractfile(entry)
            if f is None:
                continue
            file_bytes = f.read()
            total_bytes += len(file_bytes)
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError(
                    f"Skill too large (> {MAX_TOTAL_BYTES // (1024 * 1024)} MB)"
                )
            out[rel] = file_bytes
    return out
