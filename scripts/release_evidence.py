"""Opt-in pytest plugin recording execution, omissions and provenance for release review."""

import importlib.metadata
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class ReleaseEvidence:
    def __init__(self, config: Any, destination: Path) -> None:
        self.destination = destination
        self.cases: Dict[str, Dict[str, Any]] = {}
        dependencies = {}
        for name in ("pytest", "torch", "transformers", "huggingface-hub", "nbval"):
            try:
                dependencies[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                dependencies[name] = "not installed"
        self.evidence: Dict[str, Any] = {
            "schema_version": 1,
            "suite": os.environ["TL_RELEASE_SUITE"],
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "dirty_worktree": bool(
                subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
            ),
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "dependencies": dependencies,
            "command": list(config.invocation_params.args),
            "deselected": [],
            "collection_problems": [],
        }

    def pytest_collection_finish(self, session: Any) -> None:
        for item in session.items:
            self.cases[item.nodeid] = {"nodeid": item.nodeid, "phases": [], "properties": []}

    def pytest_deselected(self, items: Any) -> None:
        self.evidence["deselected"].extend(item.nodeid for item in items)

    def pytest_collectreport(self, report: Any) -> None:
        if report.outcome != "passed":
            self.evidence["collection_problems"].append(
                {"nodeid": report.nodeid, "outcome": report.outcome, "detail": str(report.longrepr)}
            )

    def pytest_runtest_logreport(self, report: Any) -> None:
        case = self.cases.setdefault(
            report.nodeid, {"nodeid": report.nodeid, "phases": [], "properties": []}
        )
        case["phases"].append(
            {
                "when": report.when,
                "outcome": report.outcome,
                "xfail": getattr(report, "wasxfail", None),
                "duration": report.duration,
                "detail": str(report.longrepr) if report.longrepr else "",
            }
        )
        case["properties"] = list(report.user_properties)

    def pytest_sessionfinish(self, session: Any, exitstatus: Any) -> None:
        self.evidence.update(
            exit_code=int(exitstatus),
            finished_at=datetime.now(timezone.utc).isoformat(),
            cases=list(self.cases.values()),
        )
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.evidence, indent=2, allow_nan=False) + "\n")
        temporary.replace(self.destination)


def pytest_configure(config: Any) -> None:
    destination = os.environ.get("TL_RELEASE_EVIDENCE")
    if destination:
        if not os.environ.get("TL_RELEASE_SUITE"):
            raise ValueError("TL_RELEASE_SUITE is required when recording release evidence")
        path = Path(destination)
        path.unlink(missing_ok=True)
        config.pluginmanager.register(ReleaseEvidence(config, path), "release-evidence-recorder")
