"""Offline release staging, archive and launcher regressions (no registry access)."""

import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_npm_package", REPO / "devnow-cli/scripts/build_npm_package.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
NAME = json.loads((REPO / "devnow-cli/package.json").read_text())["name"]
VERSION = "0.0.0-packaging-test"


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devnow-packaging-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.root / "home")}
        for key in ("userconfig", "globalconfig"):
            config = self.root / f"{key}.npmrc"
            config.touch()
            self.env[f"npm_config_{key}"] = str(config)
        self.env.update(
            npm_config_cache=str(self.root / "npm-cache"),
            npm_config_offline="true",
            npm_config_ignore_scripts="true",
            npm_config_update_notifier="false",
        )

    def stage(self, package):
        directory = self.root / package
        directory.mkdir()
        builder.stage_sources(directory, VERSION, package)
        return directory, json.loads((directory / "package.json").read_text())

    def test_readme_toc_fix_preserves_both_markers(self):
        readme = self.root / "README.md"
        readme.write_text("# Example\n\n<!-- Begin ToC -->\n<!-- End ToC -->\n\n## Installation\n")
        command = [sys.executable, "-B", str(REPO / "scripts/readme_toc.py"), str(readme)]
        result = subprocess.run(command + ["--fix"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<!-- Begin ToC -->", readme.read_text())
        self.assertIn("<!-- End ToC -->", readme.read_text())
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_release_wrapper_metadata(self):
        _, metadata = self.stage("codex")
        self.assertEqual(metadata["name"], NAME)
        self.assertNotIn("private", metadata)
        self.assertEqual(metadata["bin"], {"devnow": "bin/codex.js"})
        self.assertEqual(metadata["optionalDependencies"], {
            f"{NAME}-{platform['npm_tag']}": f"npm:{NAME}@{VERSION}-{platform['npm_tag']}"
            for platform in builder.CODEX_PLATFORM_PACKAGES.values()
        })
        self.assertIn("DEV0N0W/DevNow-CLI", metadata["repository"]["url"])

    def test_all_native_archives_preserve_payload_and_legal_documents(self):
        for package, platform in builder.CODEX_PLATFORM_PACKAGES.items():
            with self.subTest(package=package):
                directory, metadata = self.stage(package)
                self.assertEqual(metadata["name"], NAME)
                self.assertEqual(metadata["version"], f"{VERSION}-{platform['npm_tag']}")
                self.assertEqual(metadata["os"], [platform["os"]])
                self.assertEqual(metadata["cpu"], [platform["cpu"]])
                vendor = self.root / f"payload-{package}"
                target = platform["target_triple"]
                suffix = ".exe" if platform["os"] == "win32" else ""
                for component in builder.PACKAGE_NATIVE_COMPONENTS[package]:
                    binary = vendor / target / builder.COMPONENT_DEST_DIR[component] / (component + suffix)
                    binary.parent.mkdir(parents=True, exist_ok=True)
                    binary.write_text(f"fixture:{target}:{component}")
                builder.copy_native_binaries(vendor, directory,
                                            builder.PACKAGE_NATIVE_COMPONENTS[package], {target})
                archive = self.root / f"{package}.tgz"
                with patch.dict(os.environ, self.env, clear=True):
                    builder.run_npm_pack(directory, archive)
                with tarfile.open(archive) as tar:
                    for document in ("LICENSE", "NOTICE"):
                        self.assertEqual(tar.extractfile(f"package/{document}").read(),
                                         (REPO / document).read_bytes())
                    member = f"package/vendor/{target}/codex/codex{suffix}"
                    self.assertEqual(tar.extractfile(member).read(), f"fixture:{target}:codex".encode())
                    self.assertNotIn("package/scripts/build_npm_package.py", tar.getnames())

    def test_wrapper_proxy_and_sdk_archives_have_original_notices(self):
        # The SDK build is a separate check; this fixture tests staging of build output.
        def sdk_fixture(directory):
            (directory / "dist").mkdir()
            (directory / "dist/index.js").write_text("export {};\n")
        for package in ("codex", "codex-responses-api-proxy", "codex-sdk"):
            with self.subTest(package=package), patch.object(builder, "stage_codex_sdk_sources", sdk_fixture):
                directory, metadata = self.stage(package)
                self.assertTrue(metadata["name"].startswith(NAME))
                self.assertNotIn("prepare", metadata.get("scripts", {}))
                archive = self.root / f"{package}.tgz"
                with patch.dict(os.environ, self.env, clear=True):
                    builder.run_npm_pack(directory, archive)
                with tarfile.open(archive) as tar:
                    for document in ("LICENSE", "NOTICE"):
                        self.assertEqual(tar.extractfile(f"package/{document}").read(),
                                         (REPO / document).read_bytes())

    def test_source_packages_keep_authoritative_attribution(self):
        for folder in ("devnow-cli", "sdk/typescript", "devnow-rs/responses-api-proxy/npm"):
            for document in ("LICENSE", "NOTICE"):
                with self.subTest(folder=folder, document=document):
                    self.assertEqual((REPO / folder / document).read_bytes(), (REPO / document).read_bytes())

    def test_missing_native_target_fails(self):
        vendor = self.root / "empty-vendor"
        vendor.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Missing target directories"):
            builder.copy_native_binaries(vendor, self.root / "stage", ["codex"], {"missing-target"})

    def test_unknown_package_and_nonempty_stage_fail(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown package"):
            builder.stage_sources(self.root, VERSION, "unknown")
        (self.root / "existing").touch()
        with self.assertRaisesRegex(RuntimeError, "not empty"):
            builder.prepare_staging_dir(self.root)

    def test_launcher_selectors_and_child_exit(self):
        directory, _ = self.stage("codex")
        preload = self.root / "platform.mjs"
        preload.write_text("Object.defineProperty(process,'platform',{value:process.env.TEST_PLATFORM});"
                           "Object.defineProperty(process,'arch',{value:process.env.TEST_ARCH});")
        for package, platform in builder.CODEX_PLATFORM_PACKAGES.items():
            with self.subTest(package=package):
                target = platform["target_triple"]
                binary = directory / "vendor" / target / "codex" / (
                    "codex.exe" if platform["os"] == "win32" else "codex")
                binary.parent.mkdir(parents=True)
                binary.write_text("#!/bin/sh\nprintf '%s\\n' " + shlex.quote(target) + "\nprintf '%s\\n' \"$@\"\nexit 7\n")
                binary.chmod(0o755)
                result = subprocess.run([shutil.which("node"), "--import", str(preload),
                                         str(directory / "bin/codex.js"), "--test-argument"],
                                        env={**self.env, "TEST_PLATFORM": platform["os"],
                                             "TEST_ARCH": platform["cpu"]},
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual((result.returncode, result.stdout), (7, f"{target}\n--test-argument\n"))

    def test_optional_package_alias_precedes_bundled_payload(self):
        directory, _ = self.stage("codex")
        platform = "darwin-arm64"
        alias = directory / "node_modules" / (NAME + "-" + platform)
        alias.mkdir(parents=True)
        (alias / "package.json").write_text(json.dumps({"name": NAME, "version": VERSION + "-" + platform}))
        binary = alias / "vendor/aarch64-apple-darwin/codex/codex"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\necho optional-alias\n")
        binary.chmod(0o755)
        bundled = directory / "vendor/aarch64-apple-darwin/codex/codex"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("#!/bin/sh\necho incorrect-bundled-fallback\n")
        bundled.chmod(0o755)
        preload = self.root / "platform.mjs"
        preload.write_text("Object.defineProperty(process,'platform',{value:'darwin'});"
                           "Object.defineProperty(process,'arch',{value:'arm64'});")
        result = subprocess.run(["node", "--import", str(preload), str(directory / "bin/codex.js")],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual((result.returncode, result.stdout), (0, "optional-alias\n"))
        binary.unlink()
        result = subprocess.run(["node", "--import", str(preload), str(directory / "bin/codex.js")],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ENOENT", result.stderr)

    def test_missing_dependency_and_unsupported_platform_diagnostics(self):
        directory, _ = self.stage("codex")
        result = subprocess.run(["node", str(directory / "bin/codex.js"), "--version"],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"Missing optional dependency {NAME}-", result.stderr)
        self.assertIn("Reinstall DevoNow", result.stderr)
        preload = self.root / "unsupported.mjs"
        preload.write_text("Object.defineProperty(process,'platform',{value:'freebsd'});")
        result = subprocess.run(["node", "--import", str(preload), str(directory / "bin/codex.js")],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported platform: freebsd", result.stderr)

    def test_missing_native_binary_fails(self):
        vendor = self.root / "incomplete-vendor"
        (vendor / "aarch64-apple-darwin/codex").mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "Missing native binary"):
            builder.copy_native_binaries(vendor, self.root / "stage", ["codex"], {"aarch64-apple-darwin"})

    def test_offline_orchestrator_and_posix_installer(self):
        vendor = self.root / "vendor"
        for platform in builder.CODEX_PLATFORM_PACKAGES.values():
            target = platform["target_triple"]
            suffix = ".exe" if platform["os"] == "win32" else ""
            for component in builder.PACKAGE_NATIVE_COMPONENTS["codex-" + platform["npm_tag"]]:
                binary = vendor / target / builder.COMPONENT_DEST_DIR[component] / (component + suffix)
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("#!/bin/sh\necho fixture-native\n")
                binary.chmod(0o755)
        output = self.root / "archives"
        result = subprocess.run([sys.executable, "-B", str(REPO / "scripts/stage_npm_packages.py"),
                                 "--release-version", VERSION, "--package", "codex",
                                 "--vendor-src", str(vendor), "--output-dir", str(output)],
                                env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path.name for path in output.iterdir()}, {
            f"devnow-npm-{VERSION}.tgz",
            *(f"devnow-npm-{platform['npm_tag']}-{VERSION}.tgz"
              for platform in builder.CODEX_PLATFORM_PACKAGES.values()),
        })
        # Test the shell installer using intercepted downloads, never a real service.
        tools = self.root / "tools"
        tools.mkdir()
        curl = tools / "curl"
        curl.write_text("#!/bin/sh\n[ \"$2\" = \"$EXPECTED_URL\" ] || exit 91\n"
                        "cp \"$FIXTURE_ARCHIVE\" \"$4\"\n")
        curl.chmod(0o755)
        uname = tools / "uname"
        uname.write_text("#!/bin/sh\ncase \"$1\" in -s) echo Darwin;; -m) echo arm64;; *) exit 92;; esac\n")
        uname.chmod(0o755)
        install = self.root / "installed/bin"
        home = self.root / "home"
        home.mkdir(exist_ok=True)
        env = {**self.env, "DEVNOW_INSTALL_DIR": str(install),
               "PATH": f"{tools}:{install}:" + self.env["PATH"],
               "FIXTURE_ARCHIVE": str(output / f"devnow-npm-darwin-arm64-{VERSION}.tgz"),
               "EXPECTED_URL": f"https://github.com/DEV0N0W/DevNow-CLI/releases/download/rust-v{VERSION}/devnow-npm-darwin-arm64-{VERSION}.tgz"}
        result = subprocess.run(["/bin/sh", str(REPO / "scripts/install/install.sh"), VERSION],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((install / "devnow").is_file())
        self.assertFalse((install / "codex").exists())
        for document in ("LICENSE", "NOTICE"):
            self.assertEqual((install / "devnow-licenses" / document).read_bytes(),
                             (REPO / document).read_bytes())
        self.assertFalse((home / ".profile").exists())
        self.assertEqual(subprocess.check_output([str(install / "devnow")], env=env, text=True),
                         "fixture-native\n")
        # A malformed download must fail before replacing an existing installation.
        invalid = self.root / "missing-payload.tgz"
        with tarfile.open(invalid, "w:gz"):
            pass
        result = subprocess.run(["/bin/sh", str(REPO / "scripts/install/install.sh"), VERSION],
                                env={**env, "FIXTURE_ARCHIVE": str(invalid)},
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required file", result.stderr)
        self.assertEqual(subprocess.check_output([str(install / "devnow")], env=env, text=True),
                         "fixture-native\n")

    def test_ripgrep_archive_keeps_original_license_documents(self):
        spec = importlib.util.spec_from_file_location("native_deps", REPO / "devnow-cli/scripts/install_native_deps.py")
        native = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = native
        spec.loader.exec_module(native)
        for archive_format, platform, target, executable in (
            ("tar.gz", "macos-aarch64", "aarch64-apple-darwin", "rg"),
            ("zip", "windows-x86_64", "x86_64-pc-windows-msvc", "rg.exe"),
        ):
            with self.subTest(archive_format=archive_format):
                source = self.root / ("rg." + archive_format)
                contents = {f"ripgrep/{executable}": b"binary fixture",
                            "ripgrep/LICENSE-MIT": b"original MIT fixture",
                            "ripgrep/COPYING": b"original copying fixture",
                            "ripgrep/UNLICENSE": b"original unlicense fixture"}
                if archive_format == "tar.gz":
                    with tarfile.open(source, "w:gz") as tar:
                        for name, data in contents.items():
                            info = tarfile.TarInfo(name)
                            info.size = len(data)
                            tar.addfile(info, io.BytesIO(data))
                else:
                    with zipfile.ZipFile(source, "w") as archive:
                        for name, data in contents.items():
                            archive.writestr(name, data)
                def supply_fixture(_url, destination):
                    shutil.copy2(source, destination)
                with patch.object(native, "_download_file", supply_fixture):
                    binary = native._fetch_single_rg(self.root / "vendor", target, platform,
                        {"providers": [{"url": "https://fixture.invalid/rg." + archive_format}],
                         "format": archive_format, "path": "ripgrep/" + executable,
                         "size": source.stat().st_size, "hash": "sha256",
                         "digest": hashlib.sha256(source.read_bytes()).hexdigest()}, self.root / "manifest")
                for invalid_metadata, diagnostic in (({"size": 1}, "size mismatch"),
                                                       ({"digest": "0" * 64}, "digest mismatch")):
                    with patch.object(native, "_download_file", supply_fixture):
                        with self.assertRaisesRegex(RuntimeError, diagnostic):
                            native._fetch_single_rg(self.root / "vendor", target, platform,
                                {"providers": [{"url": "https://fixture.invalid/rg." + archive_format}],
                                 "format": archive_format, "path": "ripgrep/" + executable,
                                 **invalid_metadata}, self.root / "manifest")
                self.assertEqual(binary.read_bytes(), b"binary fixture")
                for document in ("LICENSE-MIT", "COPYING", "UNLICENSE"):
                    self.assertEqual((binary.parent / document).read_bytes(), contents["ripgrep/" + document])

    def test_foreign_artifact_run_is_rejected_before_writing(self):
        destination = self.root / "not-created"
        result = subprocess.run([sys.executable, "-B", str(REPO / "devnow-cli/scripts/install_native_deps.py"),
                                 "--workflow-url", "https://github.com/openai/codex/actions/runs/123",
                                 str(destination)], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected a workflow run", result.stderr)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
