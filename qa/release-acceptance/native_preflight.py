#!/usr/bin/env python3
"""Run preliminary offline CLI checks only on a matching native host."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


TEST_REVISION = 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def native_target(scenario: str) -> tuple[str | None, str | None]:
    machine = platform.machine().lower()
    if scenario == "U02" and sys.platform == "win32":
        if machine in {"amd64", "x86_64"}:
            return "x86_64-pc-windows-msvc", None
        if machine in {"arm64", "aarch64"}:
            return "aarch64-pc-windows-msvc", None
    if scenario == "U03" and sys.platform == "darwin" and machine == "x86_64":
        translated = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"],
                                    capture_output=True, text=True, timeout=5, check=False)
        if translated.stdout.strip() == "1":
            return None, "Rosetta translation is not native Intel hardware"
        return "x86_64-apple-darwin", None
    return None, f"{scenario} requires a native matching host; found {sys.platform}/{machine}"


def run(binary: Path, args: list[str], env: dict[str, str], cwd: Path) -> dict:
    try:
        result = subprocess.run([str(binary), *args], cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, errors="replace", timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"args": args, "status": "FAIL", "details": str(exc)}
    output = result.stdout + result.stderr
    if args == ["--version"]:
        valid = result.returncode == 0 and output.strip().lower().startswith("devnow ")
    elif args == ["--invalid-acceptance-flag"]:
        valid = result.returncode != 0 and "unexpected argument" in output.lower()
    elif args == ["completion", "bash"]:
        valid = result.returncode == 0 and len(output) > 200
    elif args == ["features", "list"]:
        valid = result.returncode == 0 and "unified_exec" in output
    else:
        valid = result.returncode == 0 and "usage:" in output.lower()
    return {"args": args, "status": "PASS" if valid else "FAIL",
            "exit_code": result.returncode, "output_tail": output[-2000:]}


def preflight(scenario: str, binary: Path | None, expected_sha256: str | None) -> dict:
    target, blocker = native_target(scenario)
    result = {"scenario": scenario, "kind": "PRELIMINARY_NATIVE_PREFLIGHT",
              "test_revision": TEST_REVISION,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "host": {"platform": platform.platform(), "machine": platform.machine()},
              "target": target, "checks": [], "status": "BLOCKED" if blocker else "PENDING",
              "blocker": blocker}
    if blocker:
        return result
    if binary is None or not binary.is_file():
        result["status"] = "BLOCKED"
        result["blocker"] = "Candidate executable path is missing"
        return result
    digest = sha256(binary)
    result["binary"] = {"path": str(binary.resolve()), "sha256": digest}
    if expected_sha256 is None:
        result["status"] = "BLOCKED"
        result["blocker"] = "Candidate artifact digest must be supplied from independent build provenance"
        return result
    if digest.lower() != expected_sha256.lower():
        result["status"] = "PREFLIGHT_FAIL"
        result["blocker"] = "Candidate artifact digest mismatch"
        return result
    with tempfile.TemporaryDirectory(prefix="devnow-native-preflight-") as folder:
        work = Path(folder)
        codex_home = work / "codex"
        codex_home.mkdir(mode=0o700)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(work),
               "CODEX_HOME": str(codex_home)}
        if sys.platform == "win32":
            env["USERPROFILE"] = str(work)
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
            env["APPDATA"] = str(work / "AppData" / "Roaming")
            env["LOCALAPPDATA"] = str(work / "AppData" / "Local")
            env["TEMP"] = str(work)
            env["TMP"] = str(work)
            env["COMSPEC"] = os.environ.get("COMSPEC", "")
            (work / "AppData" / "Roaming").mkdir(parents=True)
            (work / "AppData" / "Local").mkdir(parents=True)
        for args in (["--version"], ["--help"], ["exec", "--help"],
                     ["resume", "--help"], ["fork", "--help"],
                     ["features", "list"], ["completion", "bash"],
                     ["--invalid-acceptance-flag"]):
            result["checks"].append(run(binary, args, env, work))
    result["status"] = ("PREFLIGHT_PASS" if all(check["status"] == "PASS" for check in result["checks"])
                        else "PREFLIGHT_FAIL")
    result["blocker"] = "Original scenario criteria and remaining native security/TUI checks required"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("U02", "U03"), required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = preflight(args.scenario, args.binary, args.expected_sha256)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "PREFLIGHT_PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
