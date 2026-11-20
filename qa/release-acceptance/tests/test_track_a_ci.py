"""Cross-platform Track A provenance checks without native runner access."""
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
SPEC = importlib.util.spec_from_file_location("track_a_ci", ROOT / "track_a_ci.py")
track_a = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = track_a
SPEC.loader.exec_module(track_a)


class TrackACiTests(unittest.TestCase):
    def test_source_digest_changes_with_source_and_ignores_generated_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "src").mkdir()
            (root / "src/main.rs").write_bytes(b"original")
            first = track_a.source_digest(root)
            (root / "target").mkdir()
            (root / "target/generated").write_bytes(b"ignored")
            self.assertEqual(first, track_a.source_digest(root))
            (root / "src/main.rs").write_bytes(b"changed")
            self.assertNotEqual(first, track_a.source_digest(root))

    def test_wrong_host_stops_before_git_and_toolchain(self):
        with patch.object(track_a, "native_target", return_value=(None, "wrong host")), \
             patch.object(track_a, "command_output") as command:
            result = track_a.prebuild("U02", "0" * 64)
        command.assert_not_called()
        self.assertEqual("BLOCKED", result["status"])

    def test_verified_host_records_source_comparison(self):
        def output(*args):
            if args[:2] == ("git", "rev-parse"):
                return "abc"
            if args[:2] == ("git", "status"):
                return ""
            if args[:2] == ("sysctl", "-n"):
                return "17179869184"
            return "version"

        with patch.object(track_a, "native_target", return_value=("x86_64-apple-darwin", None)), \
             patch.object(track_a, "command_output", side_effect=output), \
             patch.object(track_a, "source_digest", return_value="accepted"):
            result = track_a.prebuild("U03", "accepted")
        self.assertEqual("HOST_VERIFIED", result["status"])
        self.assertTrue(result["source_matches_accepted"])
        self.assertEqual("abc", result["git_commit"])
        self.assertEqual("cargo build --locked -p codex-cli --bin codex --target x86_64-apple-darwin",
                         result["build_command"])

    def test_pe_amd64_and_macho_intel_architecture(self):
        with tempfile.TemporaryDirectory() as folder:
            pe = Path(folder) / "devnow.exe"
            data = bytearray(256)
            data[:2] = b"MZ"
            data[0x3c:0x40] = (128).to_bytes(4, "little")
            data[128:134] = b"PE\0\0" + (0x8664).to_bytes(2, "little")
            pe.write_bytes(data)
            self.assertEqual("PE AMD64", track_a.executable_architecture(pe, "U02"))
            data[132:134] = (0xaa64).to_bytes(2, "little")
            pe.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "Expected AMD64"):
                track_a.executable_architecture(pe, "U02")
            macho = Path(folder) / "devnow"
            macho.write_bytes(b"\xcf\xfa\xed\xfe" + (0x01000007).to_bytes(4, "little"))
            self.assertEqual("Mach-O x86_64", track_a.executable_architecture(macho, "U03"))

    def test_postbuild_records_digest_and_preserves_unmatched_source(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "devnow"
            binary.write_bytes(b"\xcf\xfa\xed\xfe" + (0x01000007).to_bytes(4, "little"))
            record = {"git_commit": "abc", "source_sha256": "other",
                      "source_matches_accepted": False, "build_command": "cargo build"}
            result = track_a.postbuild("U03", binary, record)
        self.assertEqual("BUILD_PASS", result["status"])
        self.assertFalse(result["source_matches_accepted"])
        self.assertEqual(hashlib.sha256(b"\xcf\xfa\xed\xfe" +
                                        (0x01000007).to_bytes(4, "little")).hexdigest(),
                         result["executable_sha256"])

    def test_source_gate_requires_identical_clean_checkout(self):
        record = {"source_sha256": "accepted", "accepted_source_sha256": "accepted",
                  "source_matches_accepted": True, "git_commit": "abc", "git_dirty": False}
        self.assertEqual("SOURCE_MATCH", track_a.source_gate("U03", record)["status"])
        record["git_dirty"] = True
        self.assertEqual("SOURCE_MISMATCH", track_a.source_gate("U03", record)["status"])


if __name__ == "__main__":
    unittest.main()
