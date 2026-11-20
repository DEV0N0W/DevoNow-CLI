"""Verify Track B reporting does not upgrade historical or blocked scenarios."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "phase_14_2_72_dashboard", ROOT / "phase_14_2_72_dashboard.py")
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


class TrackBDashboardTests(unittest.TestCase):
    def test_all_scenarios_preserve_acceptance_status(self):
        data = dashboard.build_track_b_dashboard()
        rows = {row["scenario"]: row for row in data["scenarios"]}
        self.assertEqual(17, len(rows))
        self.assertEqual("ACCEPTED", rows["U01"]["status"])
        self.assertEqual(25, rows["U01"]["checks"]["passed"])
        self.assertEqual("BLOCKED", rows["U04"]["status"])
        self.assertEqual("PREVIOUSLY ACCEPTED", rows["U06"]["status"])
        self.assertEqual(15, rows["U06"]["automated_checks_executed"])
        self.assertEqual("PREVIOUSLY ACCEPTED", rows["U07"]["status"])
        self.assertEqual({"passed": 2, "failed": 0, "unexecuted": 1},
                         rows["U07"]["preliminary_checks"])
        self.assertTrue(all(rows[f"A{number:02}"]["status"] == "BLOCKED"
                            for number in range(1, 11)))
        self.assertTrue(all(rows[f"A{number:02}"]["functional_objective"] is None
                            for number in range(1, 11)))

    def test_markdown_matches_json(self):
        report = ROOT / "reports" / "phase-14-2-72"
        data = json.loads((report / "dashboard.json").read_text())
        self.assertEqual(dashboard.render_markdown(data),
                         (report / "dashboard.md").read_text())


if __name__ == "__main__":
    unittest.main()
