"""Check that the campaign views preserve evidence and scenario status."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "phase_14_2_71_dashboard", ROOT / "phase_14_2_71_dashboard.py"
)
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


class CampaignDashboardTests(unittest.TestCase):
    def test_scenario_statuses_and_counts(self):
        data = dashboard.build_dashboard()
        rows = {row["scenario"]: row for row in data["scenarios"]}
        self.assertEqual(17, len(rows))
        self.assertEqual([f"U{number:02}" for number in range(1, 8)]
                         + [f"A{number:02}" for number in range(1, 11)],
                         list(rows))
        self.assertEqual("ACCEPTED", rows["U01"]["status"])
        self.assertEqual(25, rows["U01"]["checks"]["passed"])
        self.assertEqual({"U02": "PENDING", "U03": "PENDING", "U04": "BLOCKED"},
                         {key: rows[key]["status"] for key in ("U02", "U03", "U04")})
        self.assertEqual(14, rows["U04"]["preliminary_checks"]["passed"])
        self.assertTrue(all(rows[key]["status"] == "PREVIOUSLY ACCEPTED"
                            for key in ("U05", "U06", "U07")))
        self.assertTrue(all(rows[f"A{number:02}"]["status"] == "BLOCKED"
                            for number in range(1, 11)))
        self.assertTrue(all(rows[key]["checks"]["passed"] == 0
                            for key in rows if key != "U01"))

    def test_retained_markdown_and_json_match(self):
        report = ROOT / "reports" / "phase-14-2-71"
        data = json.loads((report / "dashboard.json").read_text())
        self.assertEqual(dashboard.render_markdown(data),
                         (report / "dashboard.md").read_text())


if __name__ == "__main__":
    unittest.main()
