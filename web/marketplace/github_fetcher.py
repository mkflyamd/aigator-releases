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
_GIT_CLONE_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


def parse_git_clone_url(url: str) -> tuple[str, str] | None:
    """Parse a bare GitHub clone URL (https://github.com/{owner}/{repo}[.git])
    into (owner, repo). Returns None for non-github.com or malformed URLs.

    Distinct from parse_github_url above: that one expects tree/blob/raw URLs
    with a path segment (what the manual "import skill from URL" flow takes).
    This one expects the plain clone URL shape used by claude-plugins-official
    marketplace.json's git-subdir source objects (source.url).
    """
    m = _GIT_CLONE_URL_RE.match(url or "")
    if not m:
        return None
    return m.group("owner"), m.group("repo")


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
                raise ValueError(
                    "Blob URL points at a root-level SKILL.md; specify the repo as a tree URL instead"
                )
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
        raise ValueError(
            "Unsupported URL: needs a tree/<branch>/<folder> or blob/<branch>/<file> segment; bare repo root URLs lack a folder"
        )
    raise ValueError(
        "Unsupported URL: only github.com and raw.githubusercontent.com are accepted"
    )


def fetch_raw_bytes(url: str, max_bytes: int, timeout: int = 15) -> bytes:
    """Fetch a URL with host pinning to raw.githubusercontent.com over HTTPS.

    Reads at most max_bytes + 1 to detect oversize; raises ValueError on
    invalid host/scheme or oversize."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise ValueError(
            "Invalid URL: only raw.githubusercontent.com over https is allowed"
        )
    req = urllib.request.Request(url, headers={"User-Agent": "AIGator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Response too large (> {max_bytes} bytes)")
    return data


def _detect_archive_root(tf: tarfile.TarFile) -> str:
    """Derive the single top-level directory from a codeload tarball.

    GitHub's codeload service always emits archives whose every entry is
    prefixed by one top-level directory — usually "{repo}-{ref}/" but, after
    a repository rename, the directory reflects the CURRENT repository name,
    not the name used to request the archive.  The canonical example is the
    Slack plugin: the catalog URL points at "slack-mcp-plugin.git", but
    GitHub emits "slack-skills-plugin-{sha}/" after the repository rename.
    Hardcoding "{repo}-{branch}/" as the root therefore finds nothing.

    This function scans every entry name, extracts the leading path component
    before the first "/", asserts exactly one distinct top-level component
    exists (a multi-root archive is either malformed or a supply-chain
    anomaly), and returns that component with a trailing slash so callers can
    use it directly as a prefix string.

    Called on the same tarfile.TarFile object that the extraction loop will
    use — the caller must reset to the beginning (tarfile.open on the same
    BytesIO object) before iterating again.  This is safe because TarFile
    members are read lazily; calling getmembers() here does NOT extract file
    content.

    Raises ValueError on an empty archive or a multi-root archive."""
    roots: set[str] = set()
    for member in tf.getmembers():
        name = member.name.replace("\\", "/")
        slash = name.find("/")
        root = name[:slash] if slash != -1 else name
        if root:
            roots.add(root)
    if not roots:
        raise ValueError("Archive is empty or has no recognizable directory structure")
    if len(roots) > 1:
        raise ValueError(
            f"Archive has multiple top-level entries ({sorted(roots)!r}) — "
            "expected a single-root codeload archive"
        )
    return roots.pop() + "/"


def download_skill_tarball(
    owner: str, repo: str, branch: str, subpath: str
) -> dict[str, bytes]:
    """Stream the repo's tar.gz from codeload, return {relative_path: bytes} for
    files under subpath. Enforces 100 MB compressed cap, MAX_TOTAL_BYTES and
    MAX_FILES extracted caps. Rejects symlinks inside the selected plugin
    subtree; symlinks outside the selected subtree are silently skipped (they
    are never extracted or followed). Rejects path-traversal entries.

    Archive-root normalization (P0 fix — renamed-repository case): GitHub's
    codeload service names the top-level directory after the CURRENT repository
    name, not the name used in the request URL. After a rename (e.g.
    slack-mcp-plugin → slack-skills-plugin), the archive root becomes
    "slack-skills-plugin-{sha}/" even though the request URL still says
    "slack-mcp-plugin". This function derives the real root from the tarball
    contents via _detect_archive_root() rather than hardcoding
    "{repo}-{branch}/", so renamed repositories install correctly.

    `branch` accepts any git ref codeload understands — a branch name, a tag,
    or a full commit sha."""
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

    buf = io.BytesIO(data)
    try:
        tf_scan = tarfile.open(fileobj=buf, mode="r:gz")
    except tarfile.TarError as e:
        raise ValueError(f"Invalid archive: {e}") from e

    with tf_scan:
        archive_root = _detect_archive_root(tf_scan)

    if subpath:
        prefix = archive_root + subpath.strip("/") + "/"
    else:
        prefix = archive_root

    buf.seek(0)
    try:
        tf = tarfile.open(fileobj=buf, mode="r:gz")
    except tarfile.TarError as e:
        raise ValueError(f"Invalid archive: {e}") from e

    out: dict[str, bytes] = {}
    total_bytes = 0
    with tf:
        for entry in tf:
            if not entry.name.startswith(prefix):
                continue
            rel = entry.name[len(prefix):]
            if (
                not rel
                or rel.startswith(("/", "\\"))
                or ".." in rel.replace("\\", "/").split("/")
            ):
                raise ValueError(f"Invalid file path in skill archive: {rel}")
            # Skip entries inside dotfile directories (.cursor/, .git/,
            # .github/, etc.) — they are IDE/tooling metadata that are never
            # installed and must not trigger the symlink guard. A symlink
            # inside .cursor/ (e.g. canva's .cursor/skills) is not a threat
            # because those entries are skipped entirely, never extracted.
            # Only directory components (not the filename itself) are checked:
            # .mcp.json is a dotfile at root level that IS valid content.
            rel_parts = rel.replace("\\", "/").split("/")
            if any(part.startswith(".") for part in rel_parts[:-1] if part):
                continue
            if entry.issym() or entry.islnk():
                raise ValueError(
                    f"Skill archives may not contain symlinks (found: {entry.name!r})"
                )
            if not entry.isfile():
                continue
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
