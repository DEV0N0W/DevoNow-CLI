#!/usr/bin/env python3
"""Extend the retained campaign dashboard with Track B readiness evidence."""
from __future__ import annotations

import json
import re
from pathlib import Path

from phase_14_2_71_dashboard import ROOT, build_dashboard


OUTPUT = ROOT / "reports" / "phase-14-2-72"


def build_track_b_dashboard(root: Path = ROOT) -> dict:
    data = build_dashboard(root)
    data["campaign"] = "Phase 14.2.72"
    probe_path = root / "reports" / "phase-14-2-72" / "u06-bounded-offline-probe.json"
    probe = json.loads(probe_path.read_text())
    artifact_readiness = json.loads((root / "reports" / "phase-14-2-72"
                                     / "u04-artifact-readiness.json").read_text())
    packaging_log = (root / "reports" / "phase-14-2-72" / "u04-offline-packaging.log").read_text()
    packaging_match = re.search(r"Ran (\d+) tests? in .+\n\nOK", packaging_log)
    if packaging_match is None:
        raise ValueError("Track B offline packaging log has no successful unittest summary")
    packaging_passed = int(packaging_match.group(1))
    session_test_passed = 0
    for name in ("u07-fork-core-test.log", "u07-resume-core-test.log"):
        session_log = (root / "reports" / "phase-14-2-72" / name).read_text()
        if not re.search(r"test result: ok\. 1 passed; 0 failed; 0 ignored", session_log):
            raise ValueError(f"Focused U07 test log has no successful result: {name}")
        session_test_passed += 1
    for row in data["scenarios"]:
        scenario = row["scenario"]
        row["criteria_availability"] = (
            "APPROVED_REPLACEMENT" if scenario == "U01" else "MISSING_SPECIFICATION")
        row["current_build_applicability"] = (
            "MATCHED_ACCEPTED_CANDIDATE" if scenario == "U01" else "UNESTABLISHED")
        row["offline_verification"] = "NONE"
        row["automated_checks_executed"] = 0
        if scenario == "U01":
            row["offline_verification"] = "25 MANDATORY PASS; RETAINED"
            row["automated_checks_executed"] = 25
        elif scenario in {"U02", "U03"}:
            row["offline_verification"] = "HOST_READINESS_BLOCKED; TRACK A"
        elif scenario == "U04":
            row["status"] = ("NOT ACCEPTED" if artifact_readiness["status"] == "PREFLIGHT_FAIL"
                             else "BLOCKED")
            row["offline_verification"] = (f"{packaging_passed} FIXTURE PACKAGING PASS; "
                                            f"ARCHIVE {artifact_readiness['status']}")
            row["automated_checks_executed"] = packaging_passed
            row["evidence"] = (f"Track B fixture packaging {packaging_passed} PASS; "
                               f"published archive readiness {artifact_readiness['status']}")
        elif scenario == "U05":
            row["offline_verification"] = "NO CURRENT INTERACTIVE CHECK"
        elif scenario == "U06":
            passed = sum(check["status"] == "PASS" for check in probe["checks"])
            failed = sum(check["status"] == "FAIL" for check in probe["checks"])
            row["preliminary_checks"] = {"passed": passed, "failed": failed, "unexecuted": 0}
            row["offline_verification"] = f"{probe['status']}: {passed} PASS, {failed} FAIL; MAC DEBUG BINARY"
            row["automated_checks_executed"] = len(probe["checks"])
            row["evidence"] += f"; offline probe SHA256 {probe['sha256']}"
        elif scenario == "U07":
            row["preliminary_checks"] = {"passed": session_test_passed,
                                         "failed": 0, "unexecuted": 1}
            row["offline_verification"] = (f"{session_test_passed} MOCKED CORE BEHAVIOR TESTS PASS; "
                                            "MISSING-SESSION PTY BLOCKED")
            row["automated_checks_executed"] = session_test_passed
            row["evidence"] += "; current-checkout mocked resume and fork behavior PASS; PTY attempt BLOCKED"
        else:
            row.update({
                "original_requirement_source": None,
                "functional_objective": None,
                "expected_observable_behavior": None,
                "required_cloud_services": None,
                "required_account_permissions": None,
                "required_infrastructure": None,
                "input_output_contracts": None,
                "security_considerations": "Unknown until original criterion and service are identified",
                "estimated_cost_category": None,
                "cleanup_and_rollback": None,
                "automation_feasibility": "Undetermined; no case mapping",
                "offline_mock_coverage": "No scenario-specific test; cloud-task mocks are unmapped",
                "live_cloud_acceptance_requirements": None,
                "missing_approvals_or_prerequisites": [
                    "original case definition", "provider/service mapping", "account scope",
                    "permissions", "cost limit", "test data", "cleanup plan", "live-use approval"],
            })
            row["offline_verification"] = "NO SCENARIO-SPECIFIC OFFLINE TEST"
    data["notes"].append("Track B local readiness is distinct from scenario acceptance and historical U05–U07 status.")
    data["notes"].append("A01–A10 individual specification fields are null where the originals are unrecovered.")
    return data


def render_markdown(data: dict) -> str:
    lines = [f"# {data['campaign']} release acceptance dashboard", "",
             f"Generated: {data['generated_at']}", "",
             *[f"- {note}" for note in data["notes"]], "",
             "| Scenario | Status | Criteria | Checks P/F/S/U | Automated executed | Offline verification | Current-build applicability | Environment | Evidence | Blocker | Next action |",
             "|---|---|---|---|---:|---|---|---|---|---|---|"]
    for row in data["scenarios"]:
        counts = "/".join(str(row["checks"][key])
                          for key in ("passed", "failed", "skipped", "unexecuted"))
        values = [row["scenario"], row["status"], row["criteria_availability"], counts,
                  row["automated_checks_executed"], row["offline_verification"],
                  row["current_build_applicability"], row["environment"], row["evidence"],
                  row["blocker"], row["next_action"]]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ")
                                       for value in values) + " |")
    lines.extend(["", "P/F/S/U = passed/failed/skipped/unexecuted defined acceptance checks. "
                  "Detailed A01–A10 missing-specification fields are in the matching JSON rows.", ""])
    return "\n".join(lines)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = build_track_b_dashboard()
    (OUTPUT / "dashboard.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (OUTPUT / "dashboard.md").write_text(render_markdown(data))


if __name__ == "__main__":
    main()
