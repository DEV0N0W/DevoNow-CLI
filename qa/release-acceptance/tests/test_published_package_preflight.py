"""Offline tests for supplied npm archive inspection."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "published_package_preflight", Path(__file__).resolve().parents[1] / "published_package_preflight.py"
)
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class PublishedPackagePreflightTests(unittest.TestCase):
    def archive(self, path: Path, name: str = preflight.PACKAGE_NAME,
                os_name: str | None = None) -> str:
        with tarfile.open(path, "w:gz") as package:
            metadata = {"name": name, "version": "1.2.3",
                        "bin": {"devnow": "bin/codex.js"}}
            if os_name:
                metadata["os"] = [os_name]
            for member_name, data in {
                "package/package.json": json.dumps(metadata).encode(),
                "package/LICENSE": b"license",
                "package/NOTICE": b"notice",
                "package/bin/codex.js": b"#!/usr/bin/env node\n",
            }.items():
                member = tarfile.TarInfo(member_name)
                member.size = len(data)
                package.addfile(member, io.BytesIO(data))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_missing_artifact_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            result = preflight.inspect_archive(Path(folder) / "missing.tgz", "0" * 64, "1.2.3")
        self.assertEqual("BLOCKED", result["status"])

    def test_matching_archive_is_preliminary_only(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "candidate.tgz"
            digest = self.archive(archive)
            result = preflight.inspect_archive(archive, digest, "1.2.3")
        self.assertEqual("PREFLIGHT_PASS", result["status"])
        self.assertIn("clean install", result["remaining"])

    def test_digest_and_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "candidate.tgz"
            digest = self.archive(archive, name="wrong")
            mismatch = preflight.inspect_archive(archive, "0" * 64, "1.2.3")
            wrong_name = preflight.inspect_archive(archive, digest, "1.2.3")
        self.assertEqual("PREFLIGHT_FAIL", mismatch["status"])
        self.assertEqual("PREFLIGHT_FAIL", wrong_name["status"])

    def test_platform_metadata_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "candidate.tgz"
            digest = self.archive(archive, os_name="linux")
            result = preflight.inspect_archive(archive, digest, "1.2.3", expected_os="darwin")
        self.assertEqual("PREFLIGHT_FAIL", result["status"])

    def test_native_payload_requires_executable_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "candidate.tgz"
            with tarfile.open(archive, "w:gz") as package:
                for name, data in {
                    "package/package.json": json.dumps({
                        "name": preflight.PACKAGE_NAME, "version": "1.2.3-darwin-arm64",
                        "os": ["darwin"], "cpu": ["arm64"]}).encode(),
                    "package/LICENSE": b"license", "package/NOTICE": b"notice",
                    "package/vendor/aarch64-apple-darwin/codex/codex": b"binary",
                }.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o644
                    package.addfile(member, io.BytesIO(data))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            result = preflight.inspect_archive(archive, digest, "1.2.3-darwin-arm64",
                                               "darwin", "arm64", "aarch64-apple-darwin")
        self.assertEqual("PREFLIGHT_FAIL", result["status"])
        self.assertIn("execute permission", result["blocker"])

    def test_unsafe_member_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "candidate.tgz"
            with tarfile.open(archive, "w:gz") as package:
                member = tarfile.TarInfo("package/redirect")
                member.type = tarfile.SYMTYPE
                member.linkname = "/tmp/outside"
                package.addfile(member)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            result = preflight.inspect_archive(archive, digest, "1.2.3")
        self.assertEqual("PREFLIGHT_FAIL", result["status"])
        self.assertIn("unsafe", result["blocker"])


if __name__ == "__main__":
    unittest.main()
