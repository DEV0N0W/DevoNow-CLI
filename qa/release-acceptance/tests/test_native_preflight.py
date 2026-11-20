"""Offline checks for the cross-platform readiness helper."""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "native_preflight", Path(__file__).resolve().parents[1] / "native_preflight.py"
)
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class NativePreflightTests(unittest.TestCase):
    def test_host_gate_rejects_wrong_platform(self):
        with patch.object(preflight.sys, "platform", "darwin"), \
             patch.object(preflight.platform, "machine", return_value="arm64"):
            result = preflight.preflight("U03", None, None)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual([], result["checks"])
        self.assertIn("native matching host", result["blocker"])

    def test_windows_target_identification(self):
        with patch.object(preflight.sys, "platform", "win32"), \
             patch.object(preflight.platform, "machine", return_value="AMD64"):
            self.assertEqual(("x86_64-pc-windows-msvc", None), preflight.native_target("U02"))

    def test_rosetta_does_not_count_as_native_intel(self):
        response = subprocess.CompletedProcess([], 0, "1\n", "")
        with patch.object(preflight.sys, "platform", "darwin"), \
             patch.object(preflight.platform, "machine", return_value="x86_64"), \
             patch.object(preflight.subprocess, "run", return_value=response):
            target, blocker = preflight.native_target("U03")
        self.assertIsNone(target)
        self.assertIn("Rosetta", blocker)

    def test_digest_mismatch_blocks_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "candidate"
            binary.write_bytes(b"candidate")
            with patch.object(preflight, "native_target", return_value=("x86_64-apple-darwin", None)), \
                 patch.object(preflight, "run") as run:
                result = preflight.preflight("U03", binary, "0" * 64)
            run.assert_not_called()
        self.assertEqual("PREFLIGHT_FAIL", result["status"])
        self.assertEqual("Candidate artifact digest mismatch", result["blocker"])

    def test_matching_candidate_runs_eight_offline_checks_only(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "candidate"
            binary.write_bytes(b"candidate")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            with patch.object(preflight, "native_target", return_value=("x86_64-apple-darwin", None)), \
                 patch.object(preflight, "run", return_value={"status": "PASS"}) as run:
                result = preflight.preflight("U03", binary, digest)
            self.assertEqual(8, run.call_count)
        self.assertEqual("PREFLIGHT_PASS", result["status"])
        self.assertEqual(2, result["test_revision"])
        self.assertIn("remaining native security/TUI checks", result["blocker"])

    def test_windows_child_uses_disposable_profile_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "candidate.exe"
            binary.write_bytes(b"candidate")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            with patch.object(preflight.sys, "platform", "win32"), \
                 patch.object(preflight, "native_target", return_value=("x86_64-pc-windows-msvc", None)), \
                 patch.object(preflight, "run", return_value={"status": "PASS"}) as run:
                preflight.preflight("U02", binary, digest)
            child_env = run.call_args.args[2]
        self.assertEqual(child_env["USERPROFILE"], child_env["HOME"])
        self.assertTrue(child_env["APPDATA"].startswith(child_env["HOME"]))
        self.assertTrue(child_env["LOCALAPPDATA"].startswith(child_env["HOME"]))


if __name__ == "__main__":
    unittest.main()
