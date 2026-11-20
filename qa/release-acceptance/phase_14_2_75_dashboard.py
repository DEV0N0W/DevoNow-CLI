#!/usr/bin/env python3
"""Render Phase 14.2.75 evidence without upgrading historical acceptance."""
from __future__ import annotations

import json
from pathlib import Path

from phase_14_2_71_dashboard import ROOT
from phase_14_2_72_dashboard import render_markdown
from phase_14_2_73_dashboard import build_track_a_dashboard


OUTPUT = ROOT / "reports" / "phase-14-2-75"


def build_dashboard(root: Path = ROOT) -> dict:
    data = build_track_a_dashboard(root)
    evidence = json.loads((root / "reports" / "phase-14-2-75" / "evidence.json").read_text())
    data["campaign"] = "Phase 14.2.75"
    data["notes"].append(
        f"U05-U07 current-build probes use test revision {evidence['test_revision']}; "
        "replacement matrices are proposed and unapproved.")
    data["notes"].append("Historical PREVIOUSLY ACCEPTED labels do not confer current-build revalidation.")
    for row in data["scenarios"]:
        scenario = row["scenario"]
        if scenario not in {"U05", "U06", "U07"}:
            continue
        probe = evidence[scenario.lower()]
        row["criteria_availability"] = "MISSING_SPECIFICATION; PROPOSED_REPLACEMENT_UNAPPROVED"
        row["current_build_applicability"] = "CANDIDATE_IDENTITY_MATCHED; REVALIDATION_INCOMPLETE"
        row["environment"] = "Ubuntu 24.04 ARM64 devonow-ubuntu2404; isolated test state"
        row["probe_test_revision"] = evidence["test_revision"]
        row["binary_sha256"] = evidence["binary_sha256"]
        row["source_sha256"] = "948b053788ea11007efe7b846c2cd9e11f9df4e00dbe8915dde2421063392201"
        row["current_probe_status"] = "INCOMPLETE; NO CURRENT ACCEPTANCE"
        row["current_probe_evidence"] = "reports/phase-14-2-75/evidence.json"
        if scenario == "U05":
            row["offline_verification"] = "PTY OUTPUT CAPTURED; ACCESSIBILITY UNVERIFIED"
            row["blocker"] = "Original/approved criteria and manual assistive-technology checks unavailable"
            row["next_action"] = "Approve proposed U05 matrix and complete manual accessibility review"
            row["automated_checks_executed"] = 1
        elif scenario == "U06":
            row["offline_verification"] = f"CURRENT BINARY: {probe['passed']}/{probe['count']} BOUNDED COMMANDS PASS"
            row["blocker"] = "Original/approved workload duration and resource thresholds unavailable"
            row["next_action"] = "Approve proposed U06 workload and thresholds; execute extended measurement"
            row["automated_checks_executed"] = probe["count"]
        else:
            row["offline_verification"] = "CREATE/RESUME/FORK PERSISTED; CORRUPT CASE UNVERIFIED"
            row["blocker"] = "Original/approved criteria and corrupt-rollout handling unverified"
            row["next_action"] = "Approve proposed U07 matrix and verify corrupt-rollout handling"
            row["automated_checks_executed"] = 5
        row["evidence"] = "Current accepted Ubuntu executable probed; historical acceptance retained separately"
    return data


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = build_dashboard()
    (OUTPUT / "dashboard.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (OUTPUT / "dashboard.md").write_text(render_markdown(data))
    print("Phase 14.2.75: U01 ACCEPTED (retained); U05-U07 PREVIOUSLY ACCEPTED")
    print("Current-build U05-U07 revalidation: INCOMPLETE; proposed criteria unapproved")


if __name__ == "__main__":
    main()
