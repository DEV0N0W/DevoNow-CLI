#!/usr/bin/env python3
"""Render the cross-platform acceptance overview from retained evidence."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "reports" / "phase-14-2-71"


def build_dashboard(root: Path = ROOT) -> dict:
    evidence = root / "reports" / "phase-14-2-71"
    u01 = json.loads((root / "reports" / "u01-approved-results-2026-11-16.json").read_text())
    u02 = json.loads((evidence / "u02-host-readiness.json").read_text())
    u03 = json.loads((evidence / "u03-host-readiness.json").read_text())
    u04 = json.loads((evidence / "u04-artifact-readiness.json").read_text())
    packaging_log = (evidence / "u04-offline-packaging.log").read_text()
    match = re.search(r"Ran (\d+) tests? in .+\n\nOK", packaging_log)
    if match is None:
        raise ValueError("Offline packaging log has no successful unittest summary")
    packaging_passed = int(match.group(1))
    checks = u01["acceptance"]["checks"]
    mandatory = [check for check in checks if check["mandatory"]]
    rows = [{
        "scenario": "U01", "status": u01["acceptance"]["full_u01"],
        "checks": {"passed": sum(check["status"] == "PASS" for check in mandatory),
                   "failed": sum(check["status"] == "FAIL" for check in mandatory),
                   "skipped": sum(check["status"] == "SKIPPED" for check in mandatory),
                   "unexecuted": sum(check["status"] in {"PENDING", "BLOCKED", "STALE"} for check in mandatory)},
        "environment": "Ubuntu 24.04 ARM64, devonow-ubuntu2404",
        "evidence": "Current automated; approved argument replacement; original phases historical",
        "source_sha256": u01["environment"]["source_sha256"],
        "binary_sha256": u01["environment"]["binary_sha256"],
        "blocker": "None for U01", "next_action": "Retain accepted candidate evidence",
    }]
    for scenario, readiness, environment in (
        ("U02", u02, "Windows 11 native x64/ARM64 unavailable"),
        ("U03", u03, "macOS 12+ native Intel unavailable"),
    ):
        executed = readiness["checks"]
        rows.append({"scenario": scenario,
                     "status": "NOT ACCEPTED" if readiness["status"] == "PREFLIGHT_FAIL" else "PENDING",
                     "checks": {"passed": 0, "failed": 0, "skipped": 0, "unexecuted": 0},
                     "preliminary_checks": {
                         "passed": sum(check["status"] == "PASS" for check in executed),
                         "failed": sum(check["status"] == "FAIL" for check in executed),
                         "unexecuted": max(0, 6 - len(executed))},
                     "environment": environment,
                     "evidence": f"Host readiness {readiness['status']}; no native candidate test",
                     "blocker": "Original checklist, native host, candidate-matched artifact",
                     "next_action": f"Run native_preflight.py on {scenario} host with verified candidate digest"})
    rows.append({"scenario": "U04",
                 "status": "NOT ACCEPTED" if u04["status"] == "PREFLIGHT_FAIL" else "BLOCKED",
                 "checks": {"passed": 0, "failed": 0, "skipped": 0, "unexecuted": 0},
                 "preliminary_checks": {"passed": packaging_passed + len(u04["checks"]),
                                        "failed": int(u04["status"] == "PREFLIGHT_FAIL"),
                                        "unexecuted": int(u04["status"] == "BLOCKED")},
                 "environment": "macOS arm64 fixture tests; published target unavailable",
                 "evidence": f"Offline packaging {packaging_passed}/14 PASS; artifact readiness {u04['status']}; public npm lookup 404",
                 "blocker": "Original checklist and genuine published release artifact; signing and clean-install evidence",
                 "next_action": "Supply release version, archive, independent digest, and publication provenance"})
    for scenario, detail in (
        ("U05", "Terminal accessibility"),
        ("U06", "Extended stability"),
        ("U07", "Session resume/fork"),
    ):
        rows.append({"scenario": scenario, "status": "PREVIOUSLY ACCEPTED",
                     "checks": {"passed": 0, "failed": 0, "skipped": 0, "unexecuted": 0},
                     "environment": "Earlier environment; original fingerprint unavailable",
                     "evidence": f"Carried-forward {detail} acceptance; no current-build revalidation",
                     "blocker": "Original case details and candidate applicability comparison",
                     "next_action": "Recover original evidence and assess targeted retest need"})
    for number in range(1, 11):
        rows.append({"scenario": f"A{number:02}", "status": "BLOCKED",
                     "checks": {"passed": 0, "failed": 0, "skipped": 0, "unexecuted": 0},
                     "environment": "Cloud provider and service unspecified",
                     "evidence": "No scenario-specific current or historical execution proof",
                     "blocker": "Original criterion, account scope, credentials, cost limit, test data, cleanup plan",
                     "next_action": "Obtain authoritative case and approved cloud scope"})
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "campaign": "Phase 14.2.71", "scenarios": rows,
            "notes": ["U01 acceptance uses the approved replacement for unrecovered Phases 14.2.41/42A.",
                      "Acceptance check counts cover defined checks only; original U02–U04 and A01–A10 counts are unknown.",
                      "Preliminary checks do not confer scenario acceptance.",
                      "No cloud account or paid resource was used."]}


def render_markdown(data: dict) -> str:
    lines = ["# Phase 14.2.71 release acceptance", "",
             f"Generated: {data['generated_at']}", "",
             *[f"- {note}" for note in data["notes"]], "",
             "| Scenario | Status | Acceptance checks P/F/S/U | Preliminary | Environment | Evidence | Blocker | Next action |",
             "|---|---|---|---|---|---|---|---|"]
    for row in data["scenarios"]:
        check = row["checks"]
        counts = "/".join(str(check[key]) for key in ("passed", "failed", "skipped", "unexecuted"))
        preliminary = row.get("preliminary_checks", {})
        prep = (f"{preliminary['passed']} PASS, {preliminary['failed']} FAIL, "
                f"{preliminary['unexecuted']} unexecuted"
                if preliminary else "—")
        values = [row["scenario"], row["status"], counts, prep, row["environment"],
                  row["evidence"], row["blocker"], row["next_action"]]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ")
                                       for value in values) + " |")
    lines.extend(["", "P/F/S/U = passed/failed/skipped/unexecuted acceptance checks. Counts do not imply partial scenario acceptance.", ""])
    return "\n".join(lines)


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    data = build_dashboard()
    (EVIDENCE / "dashboard.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (EVIDENCE / "dashboard.md").write_text(render_markdown(data))


if __name__ == "__main__":
    main()
