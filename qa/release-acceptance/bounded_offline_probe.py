#!/usr/bin/env python3
"""Bounded, isolated CLI repetition probe; never a U06 acceptance result."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from native_preflight import run, sha256


COMMANDS = (["--version"], ["--help"], ["features", "list"])


def probe(binary: Path, expected_sha256: str, iterations: int) -> dict:
    if not 1 <= iterations <= 20:
        raise ValueError("Iterations must be between 1 and 20")
    result = {"scenario": "U06", "kind": "PRELIMINARY_OFFLINE_STABILITY",
              "binary": str(binary), "iterations": iterations, "checks": [],
              "status": "BLOCKED", "blocker": None}
    if not binary.is_file():
        result["blocker"] = "Executable is unavailable"
        return result
    result["sha256"] = sha256(binary)
    if result["sha256"].lower() != expected_sha256.lower():
        result["status"] = "PREFLIGHT_FAIL"
        result["blocker"] = "Executable SHA256 differs from independent digest"
        return result
    with tempfile.TemporaryDirectory(prefix="devnow-stability-") as folder:
        work = Path(folder)
        codex_home = work / "codex"
        codex_home.mkdir(mode=0o700)
        env = {"HOME": str(work), "CODEX_HOME": str(codex_home),
               "PATH": os.environ.get("PATH", "")}
        for iteration in range(1, iterations + 1):
            for args in COMMANDS:
                check = run(binary.resolve(), list(args), env, work)
                check["iteration"] = iteration
                result["checks"].append(check)
    result["temporary_home_removed"] = not work.exists()
    result["status"] = ("PREFLIGHT_PASS" if all(check["status"] == "PASS"
                                             for check in result["checks"])
                        and result["temporary_home_removed"]
                        else "PREFLIGHT_FAIL")
    result["blocker"] = "Original U06 workload, duration, and thresholds are unavailable"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = probe(args.binary, args.expected_sha256, args.iterations)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "PREFLIGHT_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
