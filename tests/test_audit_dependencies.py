import importlib.util
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "audit_dependencies", ROOT / "tools" / "audit_dependencies.py"
)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

TODAY = date(2026, 11, 17)
PICOMATCH_GHSA = "GHSA-fc5q-39xc-vjpf"


def advisory(ghsa, name, severity="high"):
    return {
        "source": 1,
        "name": name,
        "dependency": name,
        "title": f"{name} advisory",
        "url": f"https://github.com/advisories/{ghsa}",
        "severity": severity,
        "range": "*",
    }


def report(vulns):
    counts = dict.fromkeys(audit.KNOWN_SEVERITIES, 0)
    for entry in vulns.values():
        counts[entry["severity"]] = counts.get(entry["severity"], 0) + 1
    counts["total"] = len(vulns)
    return {
        "auditReportVersion": 2,
        "vulnerabilities": vulns,
        "metadata": {"vulnerabilities": counts},
    }


def entry(name, severity, via):
    return {
        "name": name,
        "severity": severity,
        "via": via,
        "isDirect": False,
        "nodes": [f"node_modules/{name}"],
    }


ALL_DEV = {f"node_modules/{n}" for n in ("picomatch", "tinyglobby", "fdir", "minimatch")}


def evaluate(audit_report, today=TODAY, dev_nodes=ALL_DEV):
    return audit.evaluate_npm_audit(audit_report, today, dev_nodes)


def picomatch_tree():
    return {
        "picomatch": entry("picomatch", "high", [advisory(PICOMATCH_GHSA, "picomatch")]),
        "tinyglobby": entry("tinyglobby", "high", ["fdir", "picomatch"]),
        "fdir": entry("fdir", "high", ["picomatch"]),
        "minimatch": entry(
            "minimatch", "moderate", [advisory("GHSA-g3hv-75wg-m249", "minimatch", "moderate")]
        ),
    }


def test_only_accepted_picomatch_advisory_passes_with_waiver(capsys):
    result = evaluate(report(picomatch_tree()), TODAY)
    assert result.blocking == []
    assert [(a.id, a.package) for a, _, _ in result.waived] == [
        (PICOMATCH_GHSA, "picomatch")
    ]
    audit.report_npm_audit(result)
    out = capsys.readouterr().out
    assert "SECURITY WAIVER APPLIED" in out
    assert f"Advisory: {PICOMATCH_GHSA}" in out
    assert "Package: picomatch" in out
    assert "Review by: 2026-12-17" in out
    assert "Blocking vulnerabilities: 0" in out


def test_accepted_advisory_plus_another_high_fails():
    vulns = picomatch_tree()
    vulns["lodash"] = entry("lodash", "high", [advisory("GHSA-aaaa-bbbb-cccc", "lodash")])
    result = evaluate(report(vulns), TODAY)
    assert [a.id for a in result.blocking] == ["GHSA-aaaa-bbbb-cccc"]


def test_other_advisory_on_picomatch_fails():
    vulns = picomatch_tree()
    vulns["picomatch"]["via"].append(advisory("GHSA-zzzz-yyyy-xxxx", "picomatch", "critical"))
    result = evaluate(report(vulns), TODAY)
    assert [(a.id, a.package) for a in result.blocking] == [
        ("GHSA-zzzz-yyyy-xxxx", "picomatch")
    ]


def test_accepted_ghsa_on_unexpected_package_fails():
    vulns = {"micromatch": entry("micromatch", "high", [advisory(PICOMATCH_GHSA, "micromatch")])}
    result = evaluate(report(vulns), TODAY)
    assert [(a.id, a.package) for a in result.blocking] == [(PICOMATCH_GHSA, "micromatch")]
    assert result.waived == []


def test_expired_waiver_fails():
    result = evaluate(report(picomatch_tree()), date(2026, 12, 18))
    assert [a.id for a in result.blocking] == [PICOMATCH_GHSA]
    assert result.waived == []
    assert any("expired" in note for note in result.notes)


def test_waiver_valid_on_review_date():
    result = evaluate(report(picomatch_tree()), date(2026, 12, 17))
    assert result.blocking == []


def test_no_high_or_critical_findings_passes():
    vulns = picomatch_tree()
    del vulns["picomatch"], vulns["tinyglobby"], vulns["fdir"]
    result = evaluate(report(vulns), TODAY)
    assert result.blocking == [] and result.waived == []


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"error": {"code": "ENOAUDIT", "summary": "network failure"}},
        {"auditReportVersion": 1, "advisories": {}},
        {"auditReportVersion": 2, "metadata": {"vulnerabilities": {}}},
        report({"x": entry("x", "severe", [])}),
        report({"x": entry("x", "high", ["missing-package"])}),
        report({"x": entry("x", "high", [42])}),
        report({"x": entry("x", "high", [{"name": "x", "severity": "high"}])}),
        # high package whose only root advisory is moderate cannot be explained
        report({"x": entry("x", "high", [advisory("GHSA-aaaa-bbbb-cccc", "x", "moderate")])}),
        {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": []},
        {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {"high": "1"}}},
        # shape npm 10 emits when the audit endpoint is unreachable
        {
            "message": "request to http://127.0.0.1:9/-/npm/v1/security/audits/quick failed",
            "error": {"summary": "", "detail": ""},
        },
    ],
)
def test_malformed_or_unknown_audit_response_fails(bad):
    with pytest.raises(audit.AuditError):
        evaluate(bad, TODAY)


def test_critical_advisory_under_lower_graded_package_blocks():
    vulns = {"x": entry("x", "moderate", [advisory("GHSA-aaaa-bbbb-cccc", "x", "critical")])}
    result = evaluate(report(vulns), TODAY)
    assert [a.id for a in result.blocking] == ["GHSA-aaaa-bbbb-cccc"]


def test_via_cycle_terminates():
    vulns = picomatch_tree()
    vulns["fdir"]["via"].append("tinyglobby")
    result = evaluate(report(vulns), TODAY)
    assert result.blocking == []


def test_unused_waiver_is_reported():
    result = evaluate(report({}), TODAY)
    assert any("no longer matches" in note for note in result.notes)


def test_metadata_count_mismatch_fails():
    bad = report(picomatch_tree())
    bad["metadata"]["vulnerabilities"]["high"] = 0
    with pytest.raises(audit.AuditError):
        evaluate(bad, TODAY)


def test_waiver_rejected_when_package_is_not_dev_only():
    result = evaluate(report(picomatch_tree()), dev_nodes=ALL_DEV - {"node_modules/picomatch"})
    assert [a.id for a in result.blocking] == [PICOMATCH_GHSA]
    assert any("not dev-only" in note for note in result.notes)


def test_waiver_rejected_when_severity_escalates():
    vulns = picomatch_tree()
    vulns["picomatch"]["via"] = [advisory(PICOMATCH_GHSA, "picomatch", "critical")]
    for name in ("picomatch", "tinyglobby", "fdir"):
        vulns[name]["severity"] = "critical"
    result = evaluate(report(vulns))
    assert [a.id for a in result.blocking] == [PICOMATCH_GHSA]


def test_list_valued_severity_fails_closed():
    bad = report(picomatch_tree())
    bad["vulnerabilities"]["fdir"]["severity"] = ["high"]
    with pytest.raises(audit.AuditError, match="malformed severity"):
        evaluate(bad)


def test_unreadable_lockfile_fails_closed(tmp_path):
    with pytest.raises(audit.AuditError):
        audit.load_dev_nodes(tmp_path / "missing.json")


def test_real_lockfile_marks_picomatch_dev_only():
    assert "node_modules/picomatch" in audit.load_dev_nodes()


def _fake_npm(monkeypatch, returncode=1, stdout="", stderr=""):
    monkeypatch.setattr(audit, "load_dev_nodes", lambda: ALL_DEV)
    monkeypatch.setattr(audit.shutil, "which", lambda _: "npm")
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, stderr),
    )


def test_check_npm_fails_with_blocking_finding(monkeypatch, capsys):
    vulns = picomatch_tree()
    vulns["lodash"] = entry("lodash", "high", [advisory("GHSA-aaaa-bbbb-cccc", "lodash")])
    _fake_npm(monkeypatch, stdout=json.dumps(report(vulns)))
    assert audit.check_npm(TODAY) == 1
    out = capsys.readouterr().out
    assert "SECURITY WAIVER APPLIED" in out
    assert "Blocking vulnerabilities: 1" in out


@pytest.mark.parametrize("exc", [OSError("spawn failed"), subprocess.TimeoutExpired("npm", 300)])
def test_npm_spawn_error_or_timeout_fails(monkeypatch, exc):
    monkeypatch.setattr(audit.shutil, "which", lambda _: "npm")

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(audit.subprocess, "run", boom)
    assert audit.check_npm(TODAY) == 1


def test_npm_network_failure_fails(monkeypatch, capsys):
    error = {
        "message": "request to https://registry.npmjs.org/-/npm/v1/security/audits/quick failed",
        "error": {"summary": "", "detail": ""},
    }
    _fake_npm(monkeypatch, stdout=json.dumps(error))
    assert audit.check_npm(TODAY) == 1
    assert "failed closed" in capsys.readouterr().out


def test_npm_crash_fails(monkeypatch):
    _fake_npm(monkeypatch, returncode=254, stderr="boom")
    assert audit.check_npm(TODAY) == 1


def test_npm_non_json_output_fails(monkeypatch):
    _fake_npm(monkeypatch, stdout="npm WARN something\n")
    assert audit.check_npm(TODAY) == 1


def test_npm_missing_fails(monkeypatch):
    monkeypatch.setattr(audit.shutil, "which", lambda _: None)
    assert audit.check_npm(TODAY) == 1


def test_check_npm_passes_with_only_waived_finding(monkeypatch):
    _fake_npm(monkeypatch, stdout=json.dumps(report(picomatch_tree())))
    assert audit.check_npm(TODAY) == 0


def test_waiver_records_required_fields():
    for ghsa, waiver in audit.ACCEPTED_ADVISORIES.items():
        assert audit.GHSA_URL.match(f"https://github.com/advisories/{ghsa}")
        assert waiver["package"] and waiver["reason"] and waiver["owner"]
        assert isinstance(waiver["review_by"], date)
        assert waiver["tracking"].startswith("https://")
