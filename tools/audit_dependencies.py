import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BLOCKING_SEVERITIES = {"high", "critical"}
KNOWN_SEVERITIES = {"info", "low", "moderate", "high", "critical"}
GHSA_URL = re.compile(r"^https://github\.com/advisories/(GHSA(?:-[0-9a-z]{4}){3})$")

NPM_TIMEOUT_SECONDS = 300
EXPIRY_WARNING_DAYS = 14

# Each entry waives exactly one GHSA for exactly one package, at exactly the
# reviewed severity, only while every installed copy is a dev dependency, until
# review_by. Remove the entry once a patched release is available upstream.
ACCEPTED_ADVISORIES = {
    "GHSA-fc5q-39xc-vjpf": {
        "package": "picomatch",
        "severity": "high",
        "reason": (
            "Unpatched dev-only transitive dependency with no untrusted pattern "
            "input. Only reached via electron-builder > @electron/rebuild > "
            "node-gyp > tinyglobby, which globs the literal patterns "
            "'build/*.sln' and 'build/*.mk'. Not shipped in app.asar."
        ),
        "owner": "The AI Gator devs",
        "review_by": date(2026, 12, 17),
        "tracking": "https://github.com/mkflyamd/aigator-releases/issues/130",
    },
}


class AuditError(Exception):
    pass


@dataclass(frozen=True)
class Advisory:
    id: str
    package: str
    severity: str
    title: str


@dataclass
class AuditResult:
    blocking: list[Advisory]
    waived: list[tuple[Advisory, dict, list[str]]]
    notes: list[str]


def run(command: list[str], cwd: Path = ROOT) -> int:
    return subprocess.run(command, cwd=cwd).returncode


def _advisory_from_via(via: dict, package: str) -> Advisory:
    url = via.get("url")
    severity = via.get("severity")
    name = via.get("name")
    if not isinstance(url, str) or not isinstance(name, str):
        raise AuditError(f"advisory under {package!r} is missing url or name")
    if not isinstance(severity, str) or severity not in KNOWN_SEVERITIES:
        raise AuditError(f"advisory {url} has unknown severity {severity!r}")
    match = GHSA_URL.match(url)
    return Advisory(
        id=match.group(1) if match else url,
        package=name,
        severity=severity,
        title=str(via.get("title", "")),
    )


def _root_advisories(vulns: dict, package: str) -> set[Advisory]:
    found: set[Advisory] = set()
    pending, seen = [package], {package}
    while pending:
        current = pending.pop()
        entry = vulns.get(current)
        if not isinstance(entry, dict):
            raise AuditError(f"'via' references unknown package {current!r}")
        via = entry.get("via")
        if not isinstance(via, list) or not via:
            raise AuditError(f"package {current!r} has no 'via' list")
        for item in via:
            if isinstance(item, str):
                if item not in seen:
                    seen.add(item)
                    pending.append(item)
            elif isinstance(item, dict):
                found.add(_advisory_from_via(item, current))
            else:
                raise AuditError(f"package {current!r} has malformed 'via' entry")
    return found


def load_dev_nodes(lockfile: Path = ROOT / "shell" / "package-lock.json") -> set[str]:
    try:
        packages = json.loads(lockfile.read_text(encoding="utf-8"))["packages"]
        return {path for path, meta in packages.items() if meta.get("dev") is True}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise AuditError(f"could not read dev dependencies from {lockfile}: {exc}")


def _waiver_problem(
    advisory: Advisory, waiver: dict, vulns: dict, dev_nodes: set[str], today: date
) -> str | None:
    if waiver["package"] != advisory.package:
        return f"covers {waiver['package']!r}, not {advisory.package!r}"
    if waiver["severity"] != advisory.severity:
        return f"was reviewed at {waiver['severity']!r}, now {advisory.severity!r}"
    nodes = vulns.get(advisory.package, {}).get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return f"cannot locate installed copies of {advisory.package!r}"
    shipped = sorted(n for n in nodes if n not in dev_nodes)
    if shipped:
        return f"applies only to dev dependencies, but {shipped} are not dev-only"
    if today > waiver["review_by"]:
        return f"expired on {waiver['review_by'].isoformat()}"
    return None


def evaluate_npm_audit(report: object, today: date, dev_nodes: set[str]) -> AuditResult:
    if not isinstance(report, dict):
        raise AuditError("npm audit output is not a JSON object")
    if "error" in report:
        raise AuditError(
            f"npm audit reported an error: {report.get('message')!r} "
            f"{report['error']!r}"
        )
    if report.get("auditReportVersion") != 2:
        raise AuditError(
            f"unsupported auditReportVersion {report.get('auditReportVersion')!r}"
        )
    vulns = report.get("vulnerabilities")
    metadata = report.get("metadata")
    counts = metadata.get("vulnerabilities") if isinstance(metadata, dict) else None
    if not isinstance(vulns, dict) or not isinstance(counts, dict):
        raise AuditError("npm audit output is missing vulnerabilities or metadata")
    if not all(type(counts.get(s, 0)) is int for s in BLOCKING_SEVERITIES):
        raise AuditError("npm audit metadata has non-integer severity counts")

    flagged = []
    for package, entry in vulns.items():
        severity = entry.get("severity") if isinstance(entry, dict) else None
        if not isinstance(severity, str) or severity not in KNOWN_SEVERITIES:
            raise AuditError(f"package {package!r} has malformed severity")
        if entry["severity"] in BLOCKING_SEVERITIES:
            flagged.append(package)

    expected = sum(counts.get(s, 0) for s in BLOCKING_SEVERITIES)
    if expected != len(flagged):
        raise AuditError(
            f"metadata reports {expected} high/critical packages but "
            f"{len(flagged)} were found"
        )

    # Advisories are graded by their own severity, not the package entry's, so a
    # critical advisory under a mis-graded package still blocks.
    affected: dict[Advisory, list[str]] = {}
    for package in vulns:
        serious = {
            a
            for a in _root_advisories(vulns, package)
            if a.severity in BLOCKING_SEVERITIES
        }
        if package in flagged and not serious:
            raise AuditError(
                f"package {package!r} is {vulns[package]['severity']} but no "
                "high/critical advisory explains it"
            )
        for advisory in serious:
            affected.setdefault(advisory, []).append(package)

    blocking: set[Advisory] = set()
    waived: dict[Advisory, list[str]] = {}
    notes: list[str] = []
    for advisory, packages in affected.items():
        waiver = ACCEPTED_ADVISORIES.get(advisory.id)
        if waiver is None:
            blocking.add(advisory)
            continue
        problem = _waiver_problem(advisory, waiver, vulns, dev_nodes, today)
        if problem:
            notes.append(
                f"Waiver for {advisory.id} {problem}; treating as blocking."
            )
            blocking.add(advisory)
        else:
            waived[advisory] = packages
            days_left = (waiver["review_by"] - today).days
            if days_left <= EXPIRY_WARNING_DAYS:
                notes.append(
                    f"Waiver for {advisory.id} expires in {days_left} day(s) on "
                    f"{waiver['review_by'].isoformat()}; renew or remove it."
                )

    matched = {a.id for a in affected}
    for advisory_id in sorted(ACCEPTED_ADVISORIES.keys() - matched):
        notes.append(
            f"Waiver for {advisory_id} no longer matches any finding; remove it."
        )

    return AuditResult(
        blocking=sorted(blocking, key=lambda a: (a.package, a.id)),
        waived=[
            (a, ACCEPTED_ADVISORIES[a.id], sorted(paths))
            for a, paths in sorted(waived.items(), key=lambda kv: kv[0].id)
        ],
        notes=notes,
    )


def run_npm_audit(cwd: Path = ROOT / "shell") -> object:
    npm = shutil.which("npm")
    if npm is None:
        raise AuditError("npm executable not found on PATH")
    try:
        proc = subprocess.run(
            [npm, "audit", "--package-lock-only", "--json"],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=NPM_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f"could not run npm audit: {exc}") from exc
    # npm audit exits 1 whenever vulnerabilities exist; anything else is a crash.
    if proc.returncode not in (0, 1):
        raise AuditError(
            f"npm audit exited with {proc.returncode}: {proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AuditError(f"npm audit output is not valid JSON: {exc}") from exc


def report_npm_audit(result: AuditResult) -> None:
    for advisory, waiver, packages in result.waived:
        print("=" * 72)
        print("SECURITY WAIVER APPLIED")
        print(f"Advisory: {advisory.id} ({advisory.severity})")
        print(f"Package: {advisory.package}")
        print(f"Title: {advisory.title}")
        print(f"Reason: {waiver['reason']}")
        print(f"Owner: {waiver['owner']}")
        print(f"Review by: {waiver['review_by'].isoformat()}")
        print(f"Tracking: {waiver['tracking']}")
        print(f"Affected packages: {', '.join(packages)}")
        print("=" * 72)
    for note in result.notes:
        print(f"WARNING: {note}")
    for advisory in result.blocking:
        print(
            f"BLOCKING: {advisory.id} ({advisory.severity}) in "
            f"{advisory.package}: {advisory.title}"
        )
    print(f"Blocking vulnerabilities: {len(result.blocking)}")


def check_npm(today: date | None = None) -> int:
    try:
        result = evaluate_npm_audit(
            run_npm_audit(), today or date.today(), load_dev_nodes()
        )
    except AuditError as exc:
        print(f"npm audit failed closed: {exc}")
        return 1
    report_npm_audit(result)
    return 1 if result.blocking else 0


def main() -> int:
    if run(["uv", "audit", "--locked"]):
        return 1
    return check_npm()


if __name__ == "__main__":
    raise SystemExit(main())
