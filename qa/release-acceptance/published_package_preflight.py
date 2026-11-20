#!/usr/bin/env python3
"""Inspect a supplied published npm archive without granting U04 acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


PACKAGE_NAME = "@devn0w/devnow-agent"


def inspect_archive(archive: Path, expected_sha256: str, version: str,
                    expected_os: str | None = None, expected_cpu: str | None = None,
                    expected_target: str | None = None) -> dict:
    result = {"scenario": "U04", "kind": "PRELIMINARY_PACKAGE_PREFLIGHT",
              "archive": str(archive), "status": "BLOCKED", "checks": [],
              "remaining": ["published origin", "signature or publisher attestation",
                            "clean install", "installed CLI runtime", "uninstall or upgrade"]}
    if not archive.is_file():
        result["blocker"] = "Published package artifact is unavailable"
        return result
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    result["sha256"] = digest
    if digest.lower() != expected_sha256.lower():
        result["status"] = "PREFLIGHT_FAIL"
        result["blocker"] = "Archive SHA256 differs from independent release manifest"
        return result
    result["checks"].append("SHA256 matches independent manifest")
    try:
        with tarfile.open(archive, "r:gz") as package:
            members = package.getmembers()
            names = {member.name for member in members}
            if len(names) != len(members):
                raise ValueError("Archive contains duplicate member names")
            if any(not member.name.startswith("package/")
                   or ".." in Path(member.name).parts
                   or not (member.isfile() or member.isdir()) for member in members):
                raise ValueError("Archive contains an unsafe path or member type")
            member = package.getmember("package/package.json")
            if not member.isfile():
                raise ValueError("Package metadata is not a regular file")
            if member.size > 1024 * 1024:
                raise ValueError("Package metadata exceeds the inspection limit")
            metadata_stream = package.extractfile(member)
            if metadata_stream is None:
                raise ValueError("Cannot read package metadata")
            metadata = json.load(metadata_stream)
            if metadata.get("name") != PACKAGE_NAME or metadata.get("version") != version:
                raise ValueError("Package name or version does not match the release candidate")
            result["checks"].append("Package name and version match")
            if metadata.get("bin") is None and (metadata.get("os") is None or metadata.get("cpu") is None):
                raise ValueError("Neither CLI launcher nor complete platform metadata is present")
            if expected_os is not None and metadata.get("os") != [expected_os]:
                raise ValueError("Package operating system metadata does not match target")
            if expected_cpu is not None and metadata.get("cpu") != [expected_cpu]:
                raise ValueError("Package CPU metadata does not match target")
            if expected_os is not None or expected_cpu is not None:
                result["checks"].append("Package platform metadata matches target")
            if expected_target is not None:
                if expected_os is None or expected_cpu is None:
                    raise ValueError("Target triple requires expected OS and CPU metadata")
                executable = "codex.exe" if expected_os == "win32" else "codex"
                binary_name = f"package/vendor/{expected_target}/codex/{executable}"
                binary = package.getmember(binary_name)
                if not binary.isfile() or binary.size == 0:
                    raise ValueError("Native executable is missing or empty")
                if expected_os != "win32" and not binary.mode & 0o111:
                    raise ValueError("Native executable lacks execute permission")
                result["checks"].append("Native executable exists with required permissions")
            elif metadata.get("bin") is not None:
                if metadata["bin"] != {"devnow": "bin/codex.js"}:
                    raise ValueError("CLI bin metadata does not match documented command")
                launcher = package.getmember("package/bin/codex.js")
                if not launcher.isfile() or launcher.size == 0:
                    raise ValueError("CLI launcher is missing or empty")
                result["checks"].append("CLI launcher matches package metadata")
            for document in ("LICENSE", "NOTICE"):
                if f"package/{document}" not in names:
                    raise ValueError(f"Missing {document}")
                if not package.getmember(f"package/{document}").isfile():
                    raise ValueError(f"{document} is not a regular file")
            result["checks"].append("LICENSE and NOTICE present")
            result["package"] = {key: metadata.get(key) for key in ("name", "version", "os", "cpu", "bin")}
            result["vendor_members"] = sorted(name for name in names if name.startswith("package/vendor/"))
    except (OSError, tarfile.TarError, KeyError, ValueError, json.JSONDecodeError) as exc:
        result["status"] = "PREFLIGHT_FAIL"
        result["blocker"] = str(exc)
        return result
    result["status"] = "PREFLIGHT_PASS"
    result["blocker"] = "Preflight does not prove publication, signing, clean installation, or runtime behavior"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-os")
    parser.add_argument("--expected-cpu")
    parser.add_argument("--expected-target")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect_archive(args.archive, args.expected_sha256, args.version,
                             args.expected_os, args.expected_cpu, args.expected_target)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "PREFLIGHT_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
