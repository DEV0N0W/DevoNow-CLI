#!/usr/bin/env python3
"""Render Track A readiness without changing existing scenario decisions."""
from __future__ import annotations

import json
from pathlib import Path

from phase_14_2_71_dashboard import ROOT
from phase_14_2_72_dashboard import build_track_b_dashboard, render_markdown


OUTPUT = ROOT / "reports" / "phase-14-2-73"


def build_track_a_dashboard(root: Path = ROOT) -> dict:
    data = build_track_b_dashboard(root)
    data["campaign"] = "Phase 14.2.73"
    identity = json.loads((root / "reports" / "phase-14-2-73" / "source-identity.json").read_text())
    data["candidate_provenance"] = identity
    for row in data["scenarios"]:
        if row["scenario"] not in {"U02", "U03"}:
            continue
        scenario = row["scenario"]
        readiness = json.loads((root / "reports" / "phase-14-2-73"
                                / f"{scenario.lower()}-local-host-readiness.json").read_text())
        row["status"] = "PENDING"
        row["preliminary_checks"] = {"passed": 0, "failed": 0, "unexecuted": 8}
        row["native_preflight_test_revision"] = 2
        row["criteria_availability"] = "MISSING_SPECIFICATION; PROPOSED_REPLACEMENT_UNAPPROVED"
        row["offline_verification"] = (f"LOCAL HOST {readiness['status']}; "
                                       "8 PRELIMINARY CHECKS UNEXECUTED; GITHUB CI NOT EXECUTED")
        row["automated_checks_executed"] = 0
        row["current_build_applicability"] = "WORKING_SOURCE_MATCHES; COMMITTED_SOURCE_DIFFERS"
        row["evidence"] = ("Local host blocked before candidate execution; "
                           f"HEAD {identity['git_head']}; committed source differs from U01")
        row["blocker"] = ("Workflow absent from default branch; dispatch unauthorized; "
                          "committed candidate differs from U01; original criteria missing")
        row["next_action"] = ("Activate reviewed workflow on default branch, establish matching "
                              "candidate commit and usage budget, then authorize dispatch")
    data["notes"].append("Track A workflow is local only; neither GitHub Actions native job has run.")
    data["notes"].append("Windows Server 2025 technical evidence cannot by itself prove Windows 11 desktop acceptance.")
    return data


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = build_track_a_dashboard()
    (OUTPUT / "dashboard.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (OUTPUT / "dashboard.md").write_text(render_markdown(data))


if __name__ == "__main__":
    main()
