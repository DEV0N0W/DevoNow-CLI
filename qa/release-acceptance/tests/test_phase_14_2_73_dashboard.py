"""Keep Track A readiness separate from native acceptance."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "phase_14_2_73_dashboard", ROOT / "phase_14_2_73_dashboard.py")
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


class TrackADashboardTests(unittest.TestCase):
    def test_statuses_and_candidate_provenance(self):
        data = dashboard.build_track_a_dashboard()
        rows = {row["scenario"]: row for row in data["scenarios"]}
        self.assertEqual(17, len(rows))
        self.assertEqual("ACCEPTED", rows["U01"]["status"])
        self.assertEqual(25, rows["U01"]["checks"]["passed"])
        self.assertEqual("PENDING", rows["U02"]["status"])
        self.assertEqual("PENDING", rows["U03"]["status"])
        self.assertEqual("BLOCKED", rows["U04"]["status"])
        self.assertFalse(data["candidate_provenance"]["committed_head_matches_accepted"])
        self.assertTrue(data["candidate_provenance"]["working_matches_accepted"])
        self.assertEqual(0, rows["U02"]["automated_checks_executed"])
        self.assertEqual(0, rows["U03"]["automated_checks_executed"])
        self.assertEqual(8, rows["U02"]["preliminary_checks"]["unexecuted"])
        self.assertEqual(2, rows["U03"]["native_preflight_test_revision"])

    def test_markdown_matches_json(self):
        report = ROOT / "reports" / "phase-14-2-73"
        data = json.loads((report / "dashboard.json").read_text())
        self.assertEqual(dashboard.render_markdown(data),
                         (report / "dashboard.md").read_text())


if __name__ == "__main__":
    unittest.main()
