"""Fail closed on incomplete evidence or broken numerical limits; emit JSON and Markdown."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def load_json(path: Path) -> Any:
    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Non-finite JSON number: {value}")
        return number

    return json.loads(path.read_text(), parse_constant=reject_constant, parse_float=finite_float)


def validate_provenance(evidence: Any, commit: str, run_id: str, run_attempt: str) -> List[str]:
    problems = []
    if not isinstance(evidence, dict):
        return ["evidence must be an object"]
    if evidence.get("schema_version") != 1:
        problems.append("unsupported evidence schema")
    for field, expected in (("commit", commit), ("run_id", run_id), ("run_attempt", run_attempt)):
        if evidence.get(field) != expected:
            problems.append(f"{field} does not match this candidate/run")
    return problems


def validate_evidence(evidence: Any, commit: str, run_id: str, run_attempt: str) -> List[str]:
    problems = validate_provenance(evidence, commit, run_id, run_attempt)
    if not isinstance(evidence, dict):
        return problems
    if evidence.get("dirty_worktree") is not False:
        problems.append("working tree was dirty or its state was not recorded")
    if type(evidence.get("exit_code")) is not int or evidence["exit_code"] != 0:
        problems.append("pytest did not finish successfully")
    for field in ("deselected", "collection_problems"):
        if evidence.get(field) != []:
            problems.append(f"{field} is missing or non-empty")
    cases = evidence.get("cases")
    if not isinstance(cases, list) or not cases:
        return problems + ["no executed test cases"]
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("nodeid"), str):
            problems.append("malformed test case")
            continue
        nodeid = case["nodeid"]
        if not nodeid or nodeid in seen:
            problems.append(f"empty or duplicate test ID: {nodeid}")
        seen.add(nodeid)
        phases = case.get("phases")
        if not isinstance(phases, list) or any(not isinstance(p, dict) for p in phases):
            problems.append(f"{nodeid}: malformed phases")
            continue
        if [p.get("when") for p in phases] != ["setup", "call", "teardown"]:
            problems.append(f"{nodeid}: incomplete execution or retry")
        for phase in phases:
            if phase.get("outcome") != "passed" or phase.get("xfail") is not None:
                problems.append(
                    f"{nodeid} [{phase.get('when')}]: {phase.get('outcome')}"
                    + (f" (xfail: {phase['xfail']})" if phase.get("xfail") is not None else "")
                )
    return problems


def finite_nonnegative(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def check_thresholds(evidence: Dict[str, Any], limits: Dict[str, Any]) -> Dict[str, Any]:
    """Check every recorded measurement against policy, never an evidence-supplied tolerance."""
    problems: List[str] = []
    measurements: List[Dict[str, Any]] = []
    seen = set()
    cases = evidence.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        properties = case.get("properties", [])
        if not isinstance(properties, list):
            problems.append(f"{case.get('nodeid')}: malformed metric properties")
            continue
        case_metrics = set()
        for prop in properties:
            if (
                not isinstance(prop, (list, tuple))
                or len(prop) != 2
                or not isinstance(prop[0], str)
            ):
                problems.append(f"{case.get('nodeid')}: malformed metric property")
                continue
            name, value = prop
            if name not in limits:
                continue
            seen.add(name)
            if name in case_metrics:
                problems.append(f"{case.get('nodeid')}: duplicate metric {name}")
            case_metrics.add(name)
            limit = limits[name]
            passed = finite_nonnegative(value) and value <= limit
            measurements.append(
                {
                    "nodeid": case.get("nodeid"),
                    "metric": name,
                    "value": value,
                    "maximum": limit,
                    "passed": passed,
                }
            )
            if not passed:
                problems.append(
                    f"{case.get('nodeid')}: {name}={value!r}; required finite 0 <= value <= {limit}"
                )
    problems.extend(f"missing required metric: {name}" for name in limits if name not in seen)
    return {"blockers": problems, "measurements": measurements}


def validate_regressions(evidence: Dict[str, Any]) -> List[str]:
    """Supplemental findings cannot certify execution or be cleared by a summary."""
    cases = evidence.get("cases")
    if not isinstance(cases, list) or not cases:
        return ["regression evidence has no cases"]
    errors = []
    seen = set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("nodeid"), str)
            or not case["nodeid"]
        ):
            errors.append("malformed regression case")
            continue
        nodeid = case["nodeid"]
        if nodeid in seen:
            errors.append(f"duplicate regression case: {nodeid}")
        seen.add(nodeid)
        if type(case.get("regression")) is not bool:
            errors.append(f"{nodeid}: missing or invalid regression flag")
        elif case["regression"]:
            errors.append(f"{nodeid}: reported regression")
    return errors


def assess(
    policy: Any, evidence_dir: Path, commit: str, run_id: str, run_attempt: str, checks_result: str
) -> Dict[str, Any]:
    blockers: List[str] = []
    suites: List[Dict[str, Any]] = []
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        blockers.append("candidate must be a full 40-character commit SHA")
    if checks_result != "success":
        blockers.append(f"checks workflow result: {checks_result}")
    expected = policy.get("required_suites") if isinstance(policy, dict) else None
    if (
        not isinstance(policy, dict)
        or policy.get("schema_version") != 1
        or not isinstance(expected, list)
        or not expected
        or any(not isinstance(s, str) or not s for s in expected)
        or len(set(expected)) != len(expected)
    ):
        return {"ready": False, "blockers": ["invalid or empty release policy"], "suites": []}
    thresholds = policy.get("thresholds")
    if (
        not isinstance(thresholds, dict)
        or not thresholds
        or any(suite not in expected for suite in thresholds)
        or any(
            not isinstance(limits, dict)
            or not limits
            or any(
                not isinstance(name, str) or not name or not finite_nonnegative(limit)
                for name, limit in limits.items()
            )
            for limits in thresholds.values()
        )
    ):
        return {
            "ready": False,
            "blockers": ["invalid or missing numerical threshold policy"],
            "suites": [],
        }
    found: Dict[str, Any] = {}
    summaries: List[Dict[str, Any]] = []
    input_files = set()
    for path in sorted(evidence_dir.rglob("*.json")):
        filename = path.relative_to(evidence_dir).as_posix()
        input_files.add(filename)
        try:
            evidence = load_json(path)
            kind = evidence.get("kind", "execution") if isinstance(evidence, dict) else None
            if kind == "release-summary":
                errors = validate_provenance(evidence, commit, run_id, run_attempt)
                if type(evidence.get("all_passed")) is not bool:
                    errors.append("missing or invalid all_passed claim")
                elif not evidence["all_passed"]:
                    errors.append("summary reports failures")
                sources = evidence.get("sources")
                if (
                    not isinstance(sources, list)
                    or not sources
                    or any(not isinstance(source, str) or not source for source in sources)
                    or len(set(sources)) != len(sources)
                ):
                    errors.append("summary requires a non-empty unique list of source paths")
                    sources = []
                summaries.append(
                    {
                        "file": filename,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "all_passed": evidence.get("all_passed"),
                        "sources": sources,
                    }
                )
                blockers.extend(f"{filename}: {error}" for error in errors)
                continue
            if kind not in ("execution", "regression-evidence"):
                blockers.append(f"{filename}: unknown evidence kind")
                continue
            suite = evidence.get("suite") if isinstance(evidence, dict) else None
            if not isinstance(suite, str) or suite not in expected:
                blockers.append(f"{filename}: unknown or missing suite")
                continue
            if kind == "execution":
                errors = validate_evidence(evidence, commit, run_id, run_attempt)
                if suite in found:
                    errors.append("duplicate execution evidence")
                found[suite] = evidence
            else:
                errors = validate_provenance(evidence, commit, run_id, run_attempt)
                errors.extend(validate_regressions(evidence))
            numerical = check_thresholds(evidence, thresholds.get(suite, {}))
            errors.extend(numerical["blockers"])
            suites.append(
                {
                    "suite": suite,
                    "file": filename,
                    "kind": kind,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "ready": not errors,
                    "case_count": len(evidence.get("cases", []))
                    if isinstance(evidence.get("cases"), list)
                    else 0,
                    "blockers": errors,
                    "measurements": numerical["measurements"],
                }
            )
            blockers.extend(f"{filename} ({suite}): {error}" for error in errors)
        except (OSError, ValueError, TypeError) as exc:
            blockers.append(f"{filename}: unreadable evidence ({exc})")
    blockers.extend(f"{suite}: missing evidence" for suite in expected if suite not in found)
    if len(summaries) > 1:
        blockers.append("multiple release summaries; require one unambiguous claim")
    detailed_files = input_files - {summary["file"] for summary in summaries}
    for summary in summaries:
        claimed_files = set(summary["sources"])
        for missing in sorted(claimed_files - detailed_files):
            blockers.append(f"{summary['file']}: missing referenced evidence: {missing}")
        for omitted in sorted(detailed_files - claimed_files):
            blockers.append(f"{summary['file']}: omitted evidence from summary: {omitted}")
    contradictions = []
    reasons = list(blockers)
    for summary in summaries:
        if summary["all_passed"] is True and reasons:
            contradictions.append(
                {
                    "summary_file": summary["file"],
                    "claim": "all_passed",
                    "conflicting_files": [suite["file"] for suite in suites if not suite["ready"]],
                    "reasons": reasons,
                }
            )
            blockers.append(
                f"{summary['file']}: all_passed claim contradicted or unsupported by release evidence"
            )
    return {
        "schema_version": 1,
        "commit": commit,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "ready": not blockers,
        "blockers": blockers,
        "suites": suites,
        "summaries": summaries,
        "contradictions": contradictions,
    }


def markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Release readiness: " + ("PASS" if report["ready"] else "BLOCKED"),
        "",
        f"Candidate: `{report.get('commit', 'unknown')}`",
        f"Run: `{report.get('run_id', 'unknown')}` / attempt `{report.get('run_attempt', 'unknown')}`",
        "",
        "This checks execution completeness and recorded numerical thresholds, not all model correctness.",
        "Raw evidence records test IDs, outcomes, omissions, properties and dependency versions.",
        "",
        "| Suite / source file | Cases | Result |",
        "| --- | ---: | --- |",
    ]
    for suite in report["suites"]:
        lines.append(
            f"| {suite['suite']} / {suite['file']} | {suite['case_count']} | "
            + ("PASS" if suite["ready"] else "BLOCKED")
            + " |"
        )
    lines.extend(
        [
            "",
            "## Numerical acceptance",
            "",
            "| Suite / case | Metric | Observed | Maximum | Result |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for suite in report["suites"]:
        for measurement in suite.get("measurements", []):
            lines.append(
                f"| {suite['file']} / {measurement['nodeid']} | {measurement['metric']} | "
                f"{measurement['value']} | {measurement['maximum']} | "
                + ("PASS" if measurement["passed"] else "BLOCKED")
                + " |"
            )
    lines.extend(["", "## Summary contradictions", ""])
    for conflict in report.get("contradictions", []):
        lines.append(
            f"- {conflict['summary_file']}: claims all_passed; conflicting sources: "
            + ", ".join(conflict["conflicting_files"])
            + ". See blockers below."
        )
    lines.extend(["", "## Blockers", ""])
    # Keep the Actions summary bounded; the JSON report preserves every blocker.
    for blocker in report["blockers"][:100]:
        lines.append("- " + str(blocker).replace("\n", " ").replace("<", "&lt;"))
    if len(report["blockers"]) > 100:
        lines.append(f"- {len(report['blockers']) - 100} further blockers in readiness.json.")
    if not report["blockers"]:
        lines.append(
            "None in the required execution evidence. Human release review is still required."
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--checks-result", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        policy = load_json(args.policy)
        report = assess(
            policy,
            args.evidence_dir,
            args.commit,
            args.run_id,
            args.run_attempt,
            args.checks_result,
        )
    except (OSError, ValueError) as exc:
        report = {"ready": False, "blockers": [f"Cannot load policy: {exc}"], "suites": []}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "readiness.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output_dir / "readiness.md").write_text(markdown(report))
    print("Release readiness: " + ("PASS" if report["ready"] else "BLOCKED"))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
