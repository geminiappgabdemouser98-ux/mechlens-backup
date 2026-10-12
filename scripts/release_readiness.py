"""Fail closed on incomplete release execution evidence; emit JSON and Markdown reports."""

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


def validate_evidence(evidence: Any, commit: str, run_id: str, run_attempt: str) -> List[str]:
    problems = []
    if not isinstance(evidence, dict):
        return ["evidence must be an object"]
    if evidence.get("schema_version") != 1:
        problems.append("unsupported evidence schema")
    if evidence.get("dirty_worktree") is not False:
        problems.append("working tree was dirty or its state was not recorded")
    for field, expected in (("commit", commit), ("run_id", run_id), ("run_attempt", run_attempt)):
        if evidence.get(field) != expected:
            problems.append(f"{field} does not match this candidate/run")
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
    found: Dict[str, Any] = {}
    for path in sorted(evidence_dir.rglob("*.json")):
        try:
            evidence = load_json(path)
            suite = evidence.get("suite") if isinstance(evidence, dict) else None
            if not isinstance(suite, str) or suite not in expected:
                blockers.append(f"{path.name}: unknown or missing suite")
                continue
            if suite in found:
                blockers.append(f"{suite}: duplicate evidence")
                continue
            found[suite] = evidence
            errors = validate_evidence(evidence, commit, run_id, run_attempt)
            suites.append(
                {
                    "suite": suite,
                    "file": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "ready": not errors,
                    "case_count": len(evidence.get("cases", []))
                    if isinstance(evidence.get("cases"), list)
                    else 0,
                    "blockers": errors,
                }
            )
            blockers.extend(f"{suite}: {error}" for error in errors)
        except (OSError, ValueError, TypeError) as exc:
            blockers.append(f"{path.name}: unreadable evidence ({exc})")
    blockers.extend(f"{suite}: missing evidence" for suite in expected if suite not in found)
    return {
        "schema_version": 1,
        "commit": commit,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "ready": not blockers,
        "blockers": blockers,
        "suites": suites,
    }


def markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Release readiness: " + ("PASS" if report["ready"] else "BLOCKED"),
        "",
        f"Candidate: `{report.get('commit', 'unknown')}`",
        f"Run: `{report.get('run_id', 'unknown')}` / attempt `{report.get('run_attempt', 'unknown')}`",
        "",
        "This is an execution-completeness gate, not a model-correctness certification.",
        "Raw evidence records test IDs, outcomes, omissions, properties and dependency versions.",
        "",
        "| Suite | Cases | Result |",
        "| --- | ---: | --- |",
    ]
    for suite in report["suites"]:
        lines.append(
            f"| {suite['suite']} | {suite['case_count']} | "
            + ("PASS" if suite["ready"] else "BLOCKED")
            + " |"
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
