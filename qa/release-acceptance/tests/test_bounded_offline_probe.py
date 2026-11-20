"""Regression checks for the bounded offline repetition probe."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("bounded_offline_probe", ROOT / "bounded_offline_probe.py")
probe_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe_module
SPEC.loader.exec_module(probe_module)


class BoundedOfflineProbeTests(unittest.TestCase):
    def test_bounds_and_digest_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "candidate"
            binary.write_bytes(b"candidate")
            with self.assertRaisesRegex(ValueError, "between 1 and 20"):
                probe_module.probe(binary, "0" * 64, 21)
            with patch.object(probe_module, "run") as run:
                result = probe_module.probe(binary, "0" * 64, 1)
            run.assert_not_called()
        self.assertEqual("PREFLIGHT_FAIL", result["status"])

    def test_bounded_repetition_retains_each_check(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "candidate"
            binary.write_bytes(b"candidate")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            with patch.object(probe_module, "run", side_effect=lambda *args: {"status": "PASS"}) as run:
                result = probe_module.probe(binary, digest, 2)
            self.assertEqual(6, run.call_count)
        self.assertEqual("PREFLIGHT_PASS", result["status"])
        self.assertTrue(result["temporary_home_removed"])
        self.assertEqual([1, 1, 1, 2, 2, 2],
                         [check["iteration"] for check in result["checks"]])


if __name__ == "__main__":
    unittest.main()
