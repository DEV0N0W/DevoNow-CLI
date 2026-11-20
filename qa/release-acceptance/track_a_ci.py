#!/usr/bin/env python3
"""Collect native Track A build provenance and run isolated offline checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from native_preflight import native_target, preflight, sha256


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "devnow-rs"
TARGETS = {"U02": "x86_64-pc-windows-msvc", "U03": "x86_64-apple-darwin"}
TEST_REVISION = 1
IGNORED = {"target", ".git", "node_modules", ".next", "dist", "build", ".DS_Store", "__pycache__"}


def source_digest(root: Path) -> str:
    """Match the accepted U01 harness algorithm without importing its Linux-only module."""
    digest = hashlib.sha256()
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in IGNORED)
        for filename in sorted(files):
            if filename in IGNORED:
                continue
            path = Path(parent) / filename
            digest.update(path.relative_to(root).as_posix().encode("utf-8", errors="surrogateescape") + b"\0")
            if path.is_symlink():
                digest.update(b"SYMLINK" + os.readlink(path).encode("utf-8", errors="surrogateescape"))
            else:
                digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def command_output(*args: str) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                            timeout=20, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def prebuild(scenario: str, expected_source_sha256: str) -> dict:
    target, blocker = native_target(scenario)
    expected_target = TARGETS[scenario]
    if target != expected_target:
        blocker = blocker or f"Expected {expected_target}, found {target}"
    result = {"scenario": scenario, "stage": "NATIVE_PREFLIGHT",
              "test_revision": TEST_REVISION,
              "status": "BLOCKED" if blocker else "HOST_VERIFIED",
              "blocker": blocker, "target": target,
              "host": {"os": platform.platform(), "machine": platform.machine(),
                       "runner_name": os.environ.get("RUNNER_NAME"),
                       "run_id": os.environ.get("GITHUB_RUN_ID"),
                       "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                       "cpu_count": os.cpu_count(),
                       "disk_free_bytes": shutil.disk_usage(ROOT).free}}
    if blocker:
        return result
    result["git_commit"] = command_output("git", "rev-parse", "HEAD")
    result["git_dirty"] = bool(command_output("git", "status", "--porcelain", "--", "devnow-rs"))
    result["host"]["os_caption"] = (command_output(
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance Win32_OperatingSystem).Caption") if scenario == "U02"
        else command_output("sw_vers", "-productVersion"))
    result["host"]["memory_bytes"] = int(command_output(
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory") if scenario == "U02"
        else command_output("sysctl", "-n", "hw.memsize"))
    result["source_sha256"] = source_digest(SOURCE)
    result["accepted_source_sha256"] = expected_source_sha256
    result["source_matches_accepted"] = result["source_sha256"] == expected_source_sha256
    result["cargo_lock_sha256"] = sha256(SOURCE / "Cargo.lock")
    result["rustc_version"] = command_output("rustc", "--version")
    result["cargo_version"] = command_output("cargo", "--version")
    result["build_command"] = (f"cargo build --locked -p codex-cli --bin codex "
                               f"--target {expected_target}")
    return result


def executable_architecture(binary: Path, scenario: str) -> str:
    with binary.open("rb") as stream:
        header = stream.read(4096)
        if scenario == "U02":
            if len(header) < 64 or header[:2] != b"MZ":
                raise ValueError("Windows executable has no DOS/PE header")
            offset = int.from_bytes(header[0x3c:0x40], "little")
            stream.seek(offset)
            coff = stream.read(6)
            if coff[:4] != b"PE\0\0" or len(coff) != 6:
                raise ValueError("Windows executable has no PE signature")
            machine = int.from_bytes(coff[4:6], "little")
            if machine != 0x8664:
                raise ValueError(f"Expected AMD64 PE machine 0x8664, found 0x{machine:04x}")
            return "PE AMD64"
        if len(header) < 8 or header[:4] != b"\xcf\xfa\xed\xfe":
            raise ValueError("Expected native 64-bit little-endian Mach-O")
        cpu = int.from_bytes(header[4:8], "little")
        if cpu != 0x01000007:
            raise ValueError(f"Expected x86_64 Mach-O CPU, found 0x{cpu:08x}")
        return "Mach-O x86_64"


def postbuild(scenario: str, binary: Path, prebuild_record: dict) -> dict:
    result = {"scenario": scenario, "stage": "BUILD_PROVENANCE", "binary": str(binary),
              "git_commit": prebuild_record["git_commit"],
              "source_sha256": prebuild_record["source_sha256"],
              "source_matches_accepted": prebuild_record["source_matches_accepted"],
              "build_command": prebuild_record["build_command"],
              "status": "BUILD_FAIL"}
    if not binary.is_file():
        result["blocker"] = "Build exited without the expected executable"
        return result
    result["executable_sha256"] = sha256(binary)
    try:
        result["architecture"] = executable_architecture(binary, scenario)
    except ValueError as exc:
        result["blocker"] = str(exc)
        return result
    result["status"] = "BUILD_PASS"
    result["build_exit_status"] = 0
    return result


def offline_checks(scenario: str, binary: Path, postbuild_record: dict) -> dict:
    result = preflight(scenario, binary, postbuild_record["executable_sha256"])
    result["stage"] = "OFFLINE_APPLICATION_CHECKS"
    result["source_matches_accepted"] = postbuild_record["source_matches_accepted"]
    result["git_commit"] = postbuild_record["git_commit"]
    return result


def source_gate(scenario: str, prebuild_record: dict) -> dict:
    matched = prebuild_record["source_matches_accepted"] and not prebuild_record["git_dirty"]
    return {"scenario": scenario, "stage": "CANDIDATE_SOURCE_COMPARISON",
            "status": "SOURCE_MATCH" if matched else "SOURCE_MISMATCH",
            "git_commit": prebuild_record["git_commit"],
            "source_sha256": prebuild_record["source_sha256"],
            "accepted_source_sha256": prebuild_record["accepted_source_sha256"],
            "git_dirty": prebuild_record["git_dirty"],
            "blocker": None if matched else "Checkout cannot be proven identical to accepted U01 source"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=TARGETS, required=True)
    parser.add_argument("--stage", choices=("prebuild", "postbuild", "checks", "source-gate"), required=True)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--prebuild-record", type=Path)
    parser.add_argument("--postbuild-record", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prebuild":
        if not args.expected_source_sha256:
            parser.error("--expected-source-sha256 is required for prebuild")
        result = prebuild(args.scenario, args.expected_source_sha256)
    elif args.stage == "postbuild":
        if args.binary is None or args.prebuild_record is None:
            parser.error("--binary and --prebuild-record are required for postbuild")
        result = postbuild(args.scenario, args.binary,
                           json.loads(args.prebuild_record.read_text()))
    elif args.stage == "checks":
        if args.binary is None or args.postbuild_record is None:
            parser.error("--binary and --postbuild-record are required for checks")
        result = offline_checks(args.scenario, args.binary,
                                json.loads(args.postbuild_record.read_text()))
    else:
        if args.prebuild_record is None:
            parser.error("--prebuild-record is required for source-gate")
        result = source_gate(args.scenario, json.loads(args.prebuild_record.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"stage": result["stage"], "status": result["status"],
                      "scenario": result["scenario"]}))
    return 0 if result["status"] in {"HOST_VERIFIED", "BUILD_PASS", "PREFLIGHT_PASS", "SOURCE_MATCH"} else 2


if __name__ == "__main__":
    sys.exit(main())
