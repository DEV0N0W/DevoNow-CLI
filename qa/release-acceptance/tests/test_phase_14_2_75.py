"""Guard candidate identity and preserve scenario decisions in Phase 14.2.75."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


probe = load("phase_14_2_75_probe")
dashboard = load("phase_14_2_75_dashboard")


class Phase75Tests(unittest.TestCase):
    def test_identity_mismatch_prevents_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "candidate"
            binary.write_bytes(b"different")
            result = probe.probe(binary, "expected")
        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertEqual({}, result["u05"])
        self.assertEqual({}, result["u06"])
        self.assertEqual({}, result["u07"])

    def test_dashboard_retains_historical_statuses(self):
        data = dashboard.build_dashboard()
        rows = {row["scenario"]: row for row in data["scenarios"]}
        self.assertEqual(17, len(rows))
        self.assertEqual("ACCEPTED", rows["U01"]["status"])
        self.assertEqual(25, rows["U01"]["checks"]["passed"])
        self.assertEqual({"U02": "PENDING", "U03": "PENDING", "U04": "BLOCKED"},
                         {key: rows[key]["status"] for key in ("U02", "U03", "U04")})
        for key in ("U05", "U06", "U07"):
            self.assertEqual("PREVIOUSLY ACCEPTED", rows[key]["status"])
            self.assertEqual("INCOMPLETE; NO CURRENT ACCEPTANCE", rows[key]["current_probe_status"])
        self.assertTrue(all(rows[f"A{number:02d}"]["status"] == "BLOCKED"
                            for number in range(1, 11)))

    def test_dashboard_markdown_matches_json(self):
        report = ROOT / "reports" / "phase-14-2-75"
        data = json.loads((report / "dashboard.json").read_text())
        self.assertEqual(dashboard.render_markdown(data),
                         (report / "dashboard.md").read_text())

    def test_command_timeout_cleans_measurement_file(self):
        if sys.platform != "linux":
            self.skipTest("Probe uses GNU /usr/bin/time in the Ubuntu acceptance VM")
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            result = probe.command(Path("/bin/sleep"), ["2"], os.environ.copy(),
                                   work, timeout=0.05)
            self.assertEqual("TIMEOUT", result["exit_code"])
            self.assertEqual([], list(work.iterdir()))


if __name__ == "__main__":
    unittest.main()
