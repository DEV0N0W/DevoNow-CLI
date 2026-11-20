#!/usr/bin/env python3
"""DevoNow CLI incremental acceptance runner (Ubuntu 24.04 ARM64).

Works only on the disposable Lima guest/source copy. Standard-library Python 3.
Previous chat-derived results are explicitly marked CARRIED_FORWARD, not rerun.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.server
import json
import os
import platform
import pty
import re
import select
import signal
import shutil
import socket
import subprocess
import sys
import termios
import tempfile
import threading
import time
import struct
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

HARNESS_VERSION = "1.0.0"
HOME = Path.home()
SOURCE = HOME / "devonow-linux-test" / "devnow-rs"
BINARY = SOURCE / "target" / "debug" / "codex"
STATE_DIR = HOME / ".local" / "state" / "devonow-acceptance"
TMP_DIR = STATE_DIR / "tmp"
LOG_DIR = STATE_DIR / "logs"
REPORT_DIR = STATE_DIR / "reports"
STATE_FILE = STATE_DIR / "state.json"

PRIOR_LINUX = {
    "u01_native_arm64_build": ("Native Ubuntu 24.04 ARM64 build", "Prior terminal: cargo build --locked -p codex-cli succeeded"),
    "u01_binary_execution": ("Linux binary starts", "Prior terminal: ELF aarch64 and devnow 0.0.0"),
    "u01_cli_smoke": ("CLI help, features, exec help, Bash completion", "Prior terminal: Phase 14.2.40 PASS"),
    "u01_argument_validation": ("CLI input validation and prompt classification", "Prior terminal: Phases 14.2.41/42A PASS"),
    "u01_tui_auth_screen": ("Interactive TUI startup", "Prior screenshot: authentication selection screen appeared"),
    "u01_landlock_execution": ("Landlock /usr/bin/id execution", "Prior terminal: Phase 14.2.45 PASS"),
    "u01_landlock_filesystem": ("Landlock allowed and blocked writes", "Prior terminal: Phase 14.2.46 PASS"),
    "u01_landlock_ipv4_loopback": ("Landlock blocked tested IPv4 loopback TCP", "Prior terminal: Phase 14.2.47 PASS"),
}
CURRENT_EVIDENCE = {
    "u01_native_arm64_build": ("u01_native_arm64_build_current",),
    "u01_cli_smoke": ("u01_binary_execution_current", "u01_cli_smoke_current",
                      "u01_completion_zsh", "u01_completion_fish"),
    "u01_tui_auth_screen": ("u01_tui_auth_screen_current",),
    "u01_binary_execution": ("u01_binary_execution_current",),
    "u01_landlock_execution": ("u01_landlock_execution_current",),
    "u01_landlock_filesystem": ("u01_landlock_readonly_cwd", "u01_landlock_allowed_write_current",
                                "u01_landlock_symlink_escape"),
    "u01_landlock_ipv4_loopback": ("u01_landlock_ipv4_current",),
}
APPROVED_ARGUMENT_REPLACEMENT = (
    "u01_argument_validation_current", "u01_prompt_routing_current"
)
PRIOR_GLOBAL = {
    "u05_terminal_accessibility": ("U05 accessibility", "Previously accepted on earlier test environment"),
    "u06_extended_stability": ("U06 extended stability", "Previously accepted on earlier test environment"),
    "u07_session_resume_fork": ("U07 resume/fork", "Previously accepted on earlier test environment"),
}
NON_LINUX = {
    "U02 Windows": ("PENDING", "Requires Windows test environment"),
    "U03 macOS Intel": ("PENDING", "Requires real Intel environment or justified equivalent"),
    "U04 published package": ("BLOCKED", "Requires a release artifact/package to install"),
    "A01-A10 cloud": ("BLOCKED", "External prerequisites not yet met"),
}
SCENARIO_REQUIREMENTS = {
    "U02": ("Windows", "Native Windows CLI and sandbox acceptance", "Windows x64 or ARM64 test host and matching build"),
    "U03": ("macOS Intel", "Native Intel macOS CLI acceptance", "Intel Mac on supported macOS and matching build"),
    "U04": ("Published package", "Published artifact integrity, install, version, and clean-host execution", "Actual published release artifact"),
    "U05": ("Terminal accessibility", "Previously accepted accessibility scenario", "Check current-build applicability"),
    "U06": ("Extended stability", "Previously accepted extended stability scenario", "Check current-build applicability"),
    "U07": ("Session resume and fork", "Previously accepted resume/fork scenario", "Check current-build applicability"),
}
for cloud_number in range(1, 11):
    SCENARIO_REQUIREMENTS[f"A{cloud_number:02}"] = (
        "Cloud", "Detailed original criterion unavailable in supplied evidence",
        "Original checklist, authorized account, credentials, cost approval, external services")


class TestFailure(Exception):
    pass


class TestBlocked(Exception):
    pass


class TestSkipped(Exception):
    pass


@dataclass
class Outcome:
    status: str
    details: str


@dataclass
class TestCase:
    test_id: str
    description: str
    fn: Callable[["Context"], str]
    extended: bool = False


class Context:
    def __init__(self, env_id: str, state: dict | None = None):
        self.env_id = env_id
        self.state = state or {}
        self.current_id = ""
        self.events: list[str] = []
        self.default_env = os.environ.copy()
        self.default_env["PATH"] = f"{HOME / '.cargo' / 'bin'}:{self.default_env.get('PATH', '')}"

    def record(self, msg: str) -> None:
        self.events.append(msg)

    def command(self, argv: list[str], *, cwd: Path | None = None,
                env: dict[str, str] | None = None, timeout: int = 30,
                separate_stderr: bool = False,
                stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
        if not argv:
            raise TestFailure("Empty command")
        self.record("$ " + " ".join(argv))
        try:
            proc = subprocess.run(argv, cwd=cwd, env=env or self.default_env,
                                  stdin=subprocess.DEVNULL if stdin_text is None else None,
                                  input=stdin_text, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE if separate_stderr else subprocess.STDOUT,
                                  text=True, errors="replace",
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise TestFailure(f"Command timed out after {timeout}s: {argv[:4]}") from exc
        except OSError as exc:
            raise TestBlocked(f"Cannot invoke {argv[0]}: {exc}") from exc
        self.record(f"exit={proc.returncode}")
        self.record(proc.stdout[-12000:])
        if separate_stderr and proc.stderr:
            self.record("[stderr] " + proc.stderr[-12000:])
        return proc


def require(condition: bool, msg: str) -> None:
    if not condition:
        raise TestFailure(msg)


def run_cli(ctx: Context, args: list[str], *, cwd: Path | None = None,
            env: dict[str, str] | None = None, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    return ctx.command([str(BINARY), *args], cwd=cwd, env=env, timeout=timeout)


def read_system_value(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "unavailable"


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def source_digest(root: Path) -> str:
    """Hash source filenames and file bytes. Exclude only generated/cache trees."""
    ignore = {"target", ".git", "node_modules", ".next", "dist", "build", ".DS_Store", "__pycache__"}
    h = hashlib.sha256()
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in ignore)
        base = Path(parent)
        for filename in sorted(files):
            if filename in ignore:
                continue
            path = base / filename
            rel = path.relative_to(root).as_posix()
            h.update(rel.encode("utf-8", errors="surrogateescape") + b"\x00")
            if path.is_symlink():
                h.update(b"SYMLINK" + os.readlink(path).encode("utf-8", errors="surrogateescape"))
            else:
                h.update(bytes.fromhex(digest_file(path)))
    return h.hexdigest()


def apparmor_config_digest() -> str:
    root = Path("/etc/apparmor.d")
    if not root.is_dir():
        return "not-present"
    h = hashlib.sha256()
    try:
        for parent, dirs, files in os.walk(root, topdown=True):
            dirs[:] = sorted(d for d in dirs if d not in {"cache", "disable", ".git"})
            for name in sorted(files):
                p = Path(parent) / name
                rel = p.relative_to(root).as_posix()
                h.update(rel.encode() + b"\x00")
                try:
                    if p.is_symlink():
                        h.update(os.readlink(p).encode())
                    elif p.is_file():
                        h.update(bytes.fromhex(digest_file(p)))
                except OSError:
                    h.update(b"unreadable")
    except OSError:
        return "unavailable"
    return h.hexdigest()


def fingerprint() -> tuple[dict, str]:
    if sys.platform != "linux" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise SystemExit("ERROR: Runner must execute INSIDE the Ubuntu ARM64 VM.")
    if os.geteuid() == 0:
        raise SystemExit("ERROR: Do not run the acceptance harness as root.")
    if not (SOURCE / "Cargo.toml").is_file() or not (SOURCE / "Cargo.lock").is_file():
        raise SystemExit(f"ERROR: Missing source snapshot at {SOURCE}.")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        raise SystemExit(f"ERROR: Missing executable at {BINARY}.")
    if SOURCE == STATE_DIR or SOURCE in STATE_DIR.parents or STATE_DIR in SOURCE.parents:
        raise SystemExit("ERROR: State folder must not be inside the source snapshot.")
    data = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "os_release": read_system_value("/etc/os-release"),
        "apparmor_userns": read_system_value("/proc/sys/kernel/apparmor_restrict_unprivileged_userns"),
        "apparmor_enabled": read_system_value("/sys/module/apparmor/parameters/enabled"),
        "apparmor_profiles_sha256": apparmor_config_digest(),
        "source_sha256": source_digest(SOURCE),
        "binary_sha256": digest_file(BINARY),
        "cargo_lock_sha256": digest_file(SOURCE / "Cargo.lock"),
    }
    signature = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data, signature


def load_state(env_id: str) -> dict:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if data.get("schema") != 1:
            raise SystemExit("ERROR: Unsupported state version. Preserve state and upgrade carefully.")
        return data
    now = utc_now()
    # These are imported from prior terminal transcripts, NOT re-executed or
    # cryptographically attested to the current binary when those tests ran.
    carried = {}
    for test_id, (name, evidence) in {**PRIOR_LINUX, **PRIOR_GLOBAL}.items():
        carried[test_id] = {
            "name": name, "status": "CARRIED_FORWARD", "evidence": evidence,
            "scope": "linux" if test_id.startswith("u01_") else "earlier_environment",
            "assumed_import_fingerprint": env_id if test_id.startswith("u01_") else None,
            "provenance": "prior conversation; original execution fingerprint not captured",
        }
    return {
        "schema": 1, "version": HARNESS_VERSION, "created": now,
        "imported_linux_fingerprint": env_id,
        "carried": carried,
        "results": {
            "u01_default_bubblewrap": {
                "status": "FAIL", "kind": "KNOWN_BLOCKER",
                "description": "Default Bubblewrap loopback initialization",
                "details": "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted (Phase 14.2.48)",
                "provenance": "prior conversation, not rerun by harness",
                "fingerprint": env_id,
                "last_executed_at": None,
            }
        },
        "history": [{"at": now, "event": "Imported previous acceptance evidence without rerunning"}],
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def test_linkage(ctx: Context) -> str:
    if not shutil.which("ldd"):
        raise TestBlocked("ldd not present")
    p = ctx.command(["ldd", str(BINARY)], timeout=20)
    require(p.returncode == 0, f"ldd returned {p.returncode}")
    require("not found" not in p.stdout.lower(), "Missing runtime shared library")
    require("libc.so" in p.stdout or "ld-linux" in p.stdout, "Unexpected ldd output")
    return "All reported ELF shared-library dependencies resolve"


def test_cargo_metadata(ctx: Context) -> str:
    if not shutil.which("cargo") and not (HOME / ".cargo" / "bin" / "cargo").exists():
        raise TestBlocked("Cargo unavailable")
    p = ctx.command(["cargo", "metadata", "--locked", "--offline", "--no-deps", "--format-version", "1"], cwd=SOURCE, timeout=90, separate_stderr=True)
    require(p.returncode == 0, "Offline Cargo metadata failed")
    try:
        metadata = json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise TestFailure("Cargo metadata not valid JSON") from exc
    packages = {x["name"] for x in metadata["packages"]}
    require("codex-cli" in packages, "codex-cli absent from Cargo workspace metadata")
    require("codex-linux-sandbox" in packages, "codex-linux-sandbox absent from metadata")
    return f"Workspace metadata valid; {len(packages)} packages; no source compilation"


def test_completion(ctx: Context, shell: str) -> str:
    p = run_cli(ctx, ["completion", shell], timeout=20)
    require(p.returncode == 0, f"{shell} completion command failed")
    require(len(p.stdout) > 200, f"{shell} completion output unexpectedly short")
    require("devnow" in p.stdout.lower() or "codex" in p.stdout.lower(), "Completion lacks recognizable CLI name")
    return f"{shell} shell completion generated ({len(p.stdout.splitlines())} lines)"


def test_revision(test_id: str) -> int:
    if test_id == "u01_native_arm64_build_current":
        return 2
    if test_id == "u01_binary_execution_current":
        return 2
    if test_id == "u01_argument_validation_current":
        return 6
    if test_id == "u01_prompt_routing_current":
        return 2
    if test_id == "u01_tui_auth_screen_current":
        return 4
    if test_id == "u01_cli_smoke_current":
        return 2
    return 2 if test_id in {"u01_mcp_list_isolated_home", "u01_sandbox_unit_tests",
                            "u01_landlock_ipv6_loopback"} else 1


def test_mcp_list(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="isolated-mcp-", dir=TMP_DIR) as folder:
        work = Path(folder)
        env = ctx.default_env.copy()
        env["HOME"] = str(work)
        codex_home = work / "codex"
        codex_home.mkdir(mode=0o700)
        (codex_home / "config.toml").write_text("[tui]\nanimations = false\n", encoding="utf-8")
        env["CODEX_HOME"] = str(codex_home)
        env["XDG_CONFIG_HOME"] = str(work / "xdg-config")
        env["XDG_DATA_HOME"] = str(work / "xdg-data")
        p = run_cli(ctx, ["mcp", "list"], cwd=work, env=env, timeout=20)
        require(p.returncode == 0, f"MCP list failed: exit {p.returncode}")
        return "MCP configuration listing succeeds in disposable HOME/CODEX_HOME"


def test_help(ctx: Context, command: str) -> str:
    p = run_cli(ctx, [command, "--help"], timeout=20)
    require(p.returncode == 0, f"{command} help exited {p.returncode}")
    require("usage:" in p.stdout.lower(), "Missing usage information")
    return f"{command} command exposes offline help"


def test_binary_execution_current(ctx: Context) -> str:
    result = run_cli(ctx, ["--version"])
    require(result.returncode == 0 and
            bool(re.fullmatch(r"devnow\s+\d+\.\d+\.\d+(?:[-+][\w.]+)?", result.stdout.strip())),
            "Current Linux executable did not identify itself with a semantic version")
    return f"Current Linux executable started: {result.stdout.strip()[:120]}"


def test_cli_smoke_current(ctx: Context) -> str:
    for args in (["--help"], ["exec", "--help"]):
        result = run_cli(ctx, args)
        require(result.returncode == 0 and "usage:" in result.stdout.lower(),
                f"CLI help failed for {' '.join(args)}")
        require("devnow" in result.stdout.lower(), f"CLI identity missing from {' '.join(args)} help")
    with tempfile.TemporaryDirectory(prefix="features-list-", dir=TMP_DIR) as folder:
        work = Path(folder)
        env = ctx.default_env.copy()
        env.update({"HOME": str(work), "CODEX_HOME": str(work / "codex")})
        (work / "codex").mkdir(mode=0o700)
        features = run_cli(ctx, ["features", "list"], cwd=work, env=env)
    require(features.returncode == 0, f"Offline feature listing exited {features.returncode}")
    require(bool(re.search(r"(?m)^unified_exec\s+\S+\s+(true|false)$", features.stdout)),
            "Feature listing lacks the expected named feature, stage, and state")
    test_completion(ctx, "bash")
    return "Current top-level/exec help, isolated feature listing, and Bash completion passed"


def test_argument_validation_current(ctx: Context) -> str:
    cases = [
        (["--invalid-acceptance-flag"], "unexpected argument"),
        (["completion", "unsupported-shell"], "invalid value"),
        (["features", "enable"], "required arguments"),
        (["exec", "--invalid-acceptance-flag"], "unexpected argument"),
        (["exec", "--skip-git-repo-check"], "no prompt provided"),
        (["exec", "--skip-git-repo-check", "-"], "no prompt provided via stdin"),
    ]
    with tempfile.TemporaryDirectory(prefix="argument-validation-", dir=TMP_DIR) as folder:
        work = Path(folder)
        env = {"PATH": ctx.default_env["PATH"], "HOME": str(work),
               "CODEX_HOME": str(work / "codex"), "LANG": "C.UTF-8"}
        (work / "codex").mkdir(mode=0o700)
        for args, diagnostic in cases:
            result = run_cli(ctx, args, cwd=work, env=env)
            require(result.returncode != 0, f"{' '.join(args)} unexpectedly succeeded")
            require(diagnostic in result.stdout.lower(),
                    f"{' '.join(args)} lacked expected diagnostic {diagnostic!r}")
        master, slave = pty.openpty()
        proc = None
        try:
            proc = subprocess.Popen([str(BINARY), "exec", "--skip-git-repo-check"],
                                    cwd=work, env=env, stdin=slave, stdout=slave,
                                    stderr=slave, start_new_session=True)
            os.close(slave)
            slave = -1
            output = bytearray()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and len(output) < 16_384:
                ready, _, _ = select.select([master], [], [], 0.25)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                elif proc.poll() is not None:
                    break
            if proc.poll() is None:
                raise TestFailure("Interactive missing-prompt probe timed out")
            exit_code = proc.wait(timeout=1)
            diagnostic = output.decode("utf-8", "replace")
            ctx.record(f"PTY exit={exit_code}: {diagnostic}")
            require(exit_code == 1 and "No prompt provided." in diagnostic,
                    "Interactive TTY missing-prompt validation did not return expected guidance")
        finally:
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)
            if slave >= 0:
                os.close(slave)
            os.close(master)
    return "Six argument checks and interactive TTY missing-prompt rejection passed"


class PromptCaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/responses":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.server.requests.append(body)
        events = (
            'event: response.created\ndata: {"type":"response.created","response":{"id":"resp1"}}\n\n'
            'event: response.output_item.done\ndata: {"type":"response.output_item.done","item":'
            '{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}]}}\n\n'
            'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp1","output":[]}}\n\n'
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(events)))
        self.end_headers()
        self.wfile.write(events)

    def log_message(self, _format, *_args):
        pass


def test_prompt_routing_current(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="prompt-routing-", dir=TMP_DIR) as folder:
        work = Path(folder)
        codex_home = work / "codex"
        codex_home.mkdir(mode=0o700)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PromptCaptureHandler)
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = {"PATH": ctx.default_env["PATH"], "HOME": str(work),
                   "CODEX_HOME": str(codex_home), "LANG": "C.UTF-8",
                   "DEVONOW_ACCEPTANCE_KEY": "local-test-only"}
            port = server.server_address[1]
            provider = ("model_providers.acceptance={ name = \"acceptance\", "
                        f"base_url = \"http://127.0.0.1:{port}/v1\", "
                        "env_key = \"DEVONOW_ACCEPTANCE_KEY\", wire_api = \"responses\" }")
            common = ["exec", "--skip-git-repo-check", "-c", provider,
                      "-c", 'model_provider="acceptance"']
            for args, stdin_text, expected in (
                (["positional-prompt-marker"], None, "positional-prompt-marker"),
                (["-"], "stdin-prompt-marker\n", "stdin-prompt-marker\n"),
            ):
                result = ctx.command([str(BINARY), *common, *args], cwd=work,
                                     env=env, timeout=30, stdin_text=stdin_text)
                require(result.returncode == 0, f"Local prompt route exited {result.returncode}")
                require(len(server.requests) == 1, "Expected exactly one local Responses request")
                body = server.requests.pop()
                user_texts = [entry.get("text") for item in body.get("input", [])
                              if item.get("type") == "message" and item.get("role") == "user"
                              for entry in item.get("content", [])
                              if entry.get("type") == "input_text"]
                ctx.record(f"local /v1/responses user text: {user_texts!r}")
                prompt_texts = [text for text in user_texts if "prompt-marker" in text]
                require(prompt_texts == [expected],
                        f"Prompt routed incorrectly: expected {expected!r}, got {prompt_texts!r}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    return "Positional and stdin prompts reached only the local Responses endpoint"


def build_native(state: dict) -> None:
    """Retain a complete native build attempt before testing its resulting binary."""
    before = source_digest(SOURCE)
    lock = digest_file(SOURCE / "Cargo.lock")
    command = ["cargo", "build", "--locked", "--offline", "-j", "1", "-p", "codex-cli"]
    clean_command = ["cargo", "clean", "-p", "codex-cli"]
    env = os.environ.copy()
    env["PATH"] = f"{HOME / '.cargo' / 'bin'}:{env.get('PATH', '')}"
    env["CARGO_BUILD_JOBS"] = "1"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    artifact_dir = STATE_DIR / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    previous_binary = artifact_dir / f"codex-before-build-{digest_file(BINARY)}"
    if not previous_binary.exists():
        shutil.copy2(BINARY, previous_binary)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="native-build-",
                                     suffix=".log", dir=LOG_DIR, delete=False) as log:
        record = {"started_at": utc_now(), "source_sha256": before,
                  "cargo_lock_sha256": lock, "command": command,
                  "clean_command": clean_command, "previous_binary": str(previous_binary),
                  "cwd": str(SOURCE), "log": log.name,
                  "ubuntu": read_system_value("/etc/os-release"),
                  "machine": platform.machine()}
        for tool in ("rustc", "cargo"):
            version = subprocess.run([tool, "--version"], env=env, cwd=SOURCE,
                                     capture_output=True, text=True, check=False)
            record[f"{tool}_version"] = version.stdout.strip()
            log.write(f"{tool} --version: exit={version.returncode} {version.stdout}{version.stderr}\n")
        log.write(f"started_at={record['started_at']}\ncommand={' '.join(command)}\n")
        log.flush()
        try:
            log.write(f"clean_command={' '.join(clean_command)}\n")
            log.flush()
            clean = subprocess.run(clean_command, cwd=SOURCE, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, timeout=120, check=False)
            record["clean_exit_status"] = clean.returncode
            if clean.returncode == 0:
                with subprocess.Popen(command, cwd=SOURCE, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    try:
                        record["exit_status"] = proc.wait(timeout=3600)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                        record["exit_status"] = "TIMEOUT"
            else:
                record["exit_status"] = "NOT_RUN: cargo clean failed"
        except subprocess.TimeoutExpired:
            record["exit_status"] = "NOT_RUN: cargo clean timed out"
        except OSError as exc:
            record["exit_status"] = f"START_ERROR: {exc}"
            log.write(f"Build start failed: {exc}\n")
        if record["exit_status"] != 0:
            shutil.copy2(previous_binary, BINARY)
        record["finished_at"] = utc_now()
        record["source_unchanged"] = source_digest(SOURCE) == before
        record["lock_unchanged"] = digest_file(SOURCE / "Cargo.lock") == lock
        if BINARY.is_file():
            record["binary_sha256"] = digest_file(BINARY)
            architecture = subprocess.run(["file", "-b", str(BINARY)], capture_output=True,
                                          text=True, check=False)
            record["binary_architecture"] = architecture.stdout.strip()
        log.write(f"\nfinished_at={record['finished_at']} exit_status={record['exit_status']}\n")
        log.write(f"binary_sha256={record.get('binary_sha256', 'missing')}\n")
    state.setdefault("builds", []).append(record)
    state["history"].append({"at": utc_now(), "event": "Native build attempt", "build": record})
    atomic_json(STATE_FILE, state)


def test_native_build_current(ctx: Context) -> str:
    matches = [build for build in ctx.state.get("builds", [])
               if build.get("source_sha256") == source_digest(SOURCE)
               and build.get("cargo_lock_sha256") == digest_file(SOURCE / "Cargo.lock")
               and build.get("binary_sha256") == digest_file(BINARY)]
    if not matches:
        raise TestBlocked("No successful native build record binds this source to the tested executable")
    build = matches[-1]
    require(build.get("exit_status") == 0, "Native build did not exit successfully")
    require(build.get("clean_exit_status") == 0, "Native package clean did not succeed")
    require(build.get("source_unchanged") and build.get("lock_unchanged"),
            "Source or lockfile changed during native build")
    require("aarch64" in build.get("binary_architecture", "").lower(),
            "Built executable is not AArch64 ELF")
    require("elf" in build["binary_architecture"].lower(), "Built executable is not ELF")
    ctx.record(json.dumps(build, sort_keys=True))
    return f"Native build exit=0; source/lock/binary bound by {build['log']}"


def test_tui_auth_screen_current(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="tui-auth-", dir=TMP_DIR) as folder:
        work = Path(folder)
        home = work / "home"
        home.mkdir(mode=0o700)
        codex_home = work / "codex"
        codex_home.mkdir(mode=0o700)
        env = {"PATH": ctx.default_env["PATH"], "HOME": str(home),
               "CODEX_HOME": str(codex_home), "TERM": "xterm-256color",
               "COLORTERM": "truecolor", "LANG": "C.UTF-8",
               "XDG_CONFIG_HOME": str(work / "config"),
               "XDG_DATA_HOME": str(work / "data")}
        master, slave = pty.openpty()
        output = bytearray()
        plain = ""
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            proc = subprocess.Popen([str(BINARY)], cwd=work, env=env, stdin=slave,
                                    stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            slave = -1
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and len(output) < 100_000:
                ready, _, _ = select.select([master], [], [], 0.25)
                if ready:
                    try:
                        chunk = os.read(master, 8192)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                    plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", output).decode("utf-8", "replace")
                    compact = re.sub(r"\s+", "", plain).lower()
                    if "signinwithchatgpt" in compact and "provideyourownapikey" in compact:
                        break
                if proc.poll() is not None:
                    break
            ctx.record(output.decode("utf-8", "replace")[:12000])
            require(proc.poll() is None, f"TUI exited before auth selection: {proc.returncode}")
            compact = re.sub(r"\s+", "", plain).lower()
            require("signinwithchatgpt" in compact and "provideyourownapikey" in compact,
                    "Authentication selection choices did not appear in TUI output")
        finally:
            if slave >= 0:
                os.close(slave)
            if 'proc' in locals() and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=3)
            os.close(master)
    return "Interactive authentication selection rendered in isolated PTY"


def test_landlock_execution_current(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="landlock-id-", dir=TMP_DIR) as folder:
        result = run_cli(ctx, ["--enable", "use_legacy_landlock", "sandbox", "linux", "--",
                               "/usr/bin/id", "-u"], cwd=Path(folder))
    require(result.returncode == 0 and result.stdout.strip().isdigit(), "Landlock failed to execute /usr/bin/id -u")
    return "Current Landlock sandbox executed /usr/bin/id -u"


def test_readonly_cwd(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="readonly-cwd-", dir=TMP_DIR) as folder:
        work = Path(folder)
        file = work / "must-not-create.txt"
        p = run_cli(ctx, ["--enable", "use_legacy_landlock", "sandbox", "linux", "--",
                          "/bin/sh", "-c", 'printf "SHOULD_NOT_WRITE\\n" > must-not-create.txt'], cwd=work, timeout=25)
        require(p.returncode != 0, "Read-only sandbox unexpectedly allowed working-directory write")
        require(not file.exists(), "Read-only sandbox created working-directory file")
        require(bool(re.search(r"denied|not permitted|read.only", p.stdout, re.I)),
                "Write failed without clear permission-related diagnostic")
    return "Default Landlock read-only mode denied write to working directory"


def test_landlock_allowed_write_current(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="landlock-allowed-", dir=TMP_DIR) as folder:
        work = Path(folder)
        result = run_cli(ctx, ["--enable", "use_legacy_landlock", "sandbox", "linux", "--full-auto", "--",
                               "/bin/sh", "-c", 'printf "WRITE\\n" > allowed.txt'], cwd=work)
        target = work / "allowed.txt"
        require(result.returncode == 0 and target.is_file() and
                target.read_text(encoding="utf-8") == "WRITE\n",
                "Landlock did not permit authorized working-directory write")
    return "Current Landlock sandbox permitted authorized working-directory write"


def test_symlink_escape(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="symlink-escape-", dir=TMP_DIR) as folder:
        root = Path(folder)
        allowed = root / "allowed"
        blocked = root / "blocked"
        allowed.mkdir()
        blocked.mkdir()
        protected = blocked / "protected.txt"
        protected.write_text("ORIGINAL\n", encoding="utf-8")
        link = allowed / "escape-link"
        link.symlink_to(protected)
        p = run_cli(ctx, ["--enable", "use_legacy_landlock", "sandbox", "linux", "--full-auto", "--",
                          "/bin/sh", "-c", 'printf "INTRUSION\\n" > escape-link'], cwd=allowed, timeout=25)
        require(p.returncode != 0, "Symlink escape write was allowed")
        require(protected.read_text(encoding="utf-8") == "ORIGINAL\n", "Protected file changed through symlink")
        require(bool(re.search(r"denied|not permitted|read.only", p.stdout, re.I)),
                "Symlink write failed without clear permission-related diagnostic")
    return "Landlock blocked symlink-based write to protected sibling directory"


class Ipv6Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True


class Ipv4Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


class MarkerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/marker":
            self.send_error(404)
            return
        data = b"DEVONOW_LOOPBACK_TEST\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format, *_args):
        pass


def test_ipv6_loopback(ctx: Context) -> str:
    return test_loopback(ctx, "::1", legacy_landlock=True)


def test_bubblewrap(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="bwrap-check-", dir=TMP_DIR) as folder:
        p = run_cli(ctx, ["sandbox", "linux", "--", "/usr/bin/true"], cwd=Path(folder), timeout=25)
        require(p.returncode == 0, f"Default Bubblewrap failed: {p.stdout.strip()[-1000:]}")
        return "Default Bubblewrap executed /usr/bin/true"


def bubblewrap_shell(ctx: Context, cwd: Path, script: str, *, writable_cwd: bool = False) -> subprocess.CompletedProcess[str]:
    args = ["sandbox", "linux"]
    if writable_cwd:
        args.append("--full-auto")
    return run_cli(ctx, [*args, "--", "/bin/sh", "-c", script], cwd=cwd, timeout=25)


def test_bubblewrap_readonly(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="bwrap-readonly-", dir=TMP_DIR) as folder:
        work = Path(folder)
        target = work / "probe.txt"
        script = 'printf "PROBE_STARTED\\n"; printf "WRITE\\n" > probe.txt'
        control = ctx.command(["/bin/sh", "-c", script], cwd=work)
        require(control.returncode == 0 and target.is_file() and
                target.read_text(encoding="utf-8") == "WRITE\n",
                "Write control failed outside sandbox")
        target.unlink()
        result = bubblewrap_shell(ctx, work, script)
        require("PROBE_STARTED" in result.stdout, "Bubblewrap did not start the read-only probe")
        require(result.returncode != 0 and not target.exists(), "Bubblewrap allowed read-only working-directory write")
    return "Default Bubblewrap denied a verified working-directory write"


def test_bubblewrap_outside_write(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="bwrap-outside-", dir=TMP_DIR) as folder:
        root = Path(folder)
        allowed, blocked = root / "allowed", root / "blocked"
        allowed.mkdir()
        blocked.mkdir()
        script = 'printf "PROBE_STARTED\\n"; printf "WRITE\\n" > ../blocked/probe.txt'
        target = blocked / "probe.txt"
        control = ctx.command(["/bin/sh", "-c", script], cwd=allowed)
        require(control.returncode == 0 and target.is_file() and
                target.read_text(encoding="utf-8") == "WRITE\n",
                "Outside-write control failed outside sandbox")
        target.unlink()
        allowed_result = bubblewrap_shell(ctx, allowed, 'printf "WRITE\\n" > allowed.txt', writable_cwd=True)
        require(allowed_result.returncode == 0 and (allowed / "allowed.txt").is_file() and
                (allowed / "allowed.txt").read_text(encoding="utf-8") == "WRITE\n",
                "Bubblewrap did not permit authorized working-directory write")
        result = bubblewrap_shell(ctx, allowed, script, writable_cwd=True)
        require("PROBE_STARTED" in result.stdout, "Bubblewrap did not start the outside-write probe")
        require(result.returncode != 0 and not target.exists(), "Bubblewrap allowed write outside authorized directory")
    return "Default Bubblewrap allowed working-directory write and denied sibling-directory write"


def test_bubblewrap_symlink(ctx: Context) -> str:
    with tempfile.TemporaryDirectory(prefix="bwrap-symlink-", dir=TMP_DIR) as folder:
        root = Path(folder)
        allowed, blocked = root / "allowed", root / "blocked"
        allowed.mkdir()
        blocked.mkdir()
        protected = blocked / "protected.txt"
        protected.write_text("ORIGINAL\n", encoding="utf-8")
        (allowed / "escape-link").symlink_to(protected)
        script = 'printf "PROBE_STARTED\\n"; printf "INTRUSION\\n" > escape-link'
        control = ctx.command(["/bin/sh", "-c", script], cwd=allowed)
        require(control.returncode == 0 and protected.read_text(encoding="utf-8") == "INTRUSION\n",
                "Symlink control failed outside sandbox")
        protected.write_text("ORIGINAL\n", encoding="utf-8")
        result = bubblewrap_shell(ctx, allowed, script, writable_cwd=True)
        require("PROBE_STARTED" in result.stdout, "Bubblewrap did not start the symlink probe")
        require(result.returncode != 0 and protected.read_text(encoding="utf-8") == "ORIGINAL\n",
                "Bubblewrap allowed symlink escape write")
    return "Default Bubblewrap denied a verified symlink escape write"


def test_loopback(ctx: Context, address: str, *, legacy_landlock: bool = False) -> str:
    if not shutil.which("curl"):
        raise TestBlocked("curl not installed")
    server_type = Ipv6Server if ":" in address else Ipv4Server
    try:
        server = server_type((address, 0), MarkerHandler)
    except OSError as exc:
        raise TestSkipped(f"{address} loopback unavailable: {exc}") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        host = f"[{address}]" if ":" in address else address
        args = ["curl", "--noproxy", "*", "-fsS", "--max-time", "3", f"http://{host}:{port}/marker"]
        control = ctx.command(args, timeout=8)
        if control.returncode != 0 or control.stdout.strip() != "DEVONOW_LOOPBACK_TEST":
            raise TestSkipped(f"{address} control request failed outside sandbox")
        with tempfile.TemporaryDirectory(prefix="loopback-net-", dir=TMP_DIR) as folder:
            sandbox_args = ["--enable", "use_legacy_landlock"] if legacy_landlock else []
            policy_args = ["--full-auto"] if legacy_landlock else []
            result = run_cli(ctx, [*sandbox_args, "sandbox", "linux", *policy_args, "--", "/bin/sh", "-c",
                                   'printf "PROBE_STARTED\\n"; exec "$@"', "sh", *args], cwd=Path(folder), timeout=12)
        label = "Landlock" if legacy_landlock else "Default Bubblewrap"
        require("PROBE_STARTED" in result.stdout, f"{label} did not start the network probe")
        require(result.returncode != 0 and "DEVONOW_LOOPBACK_TEST" not in result.stdout,
                f"{label} allowed {address} loopback request")
        require(bool(re.search(r"failed to connect|couldn.t connect|network is unreachable|not permitted|denied",
                               result.stdout, re.I)),
                f"{label} network probe failed for a reason other than connection denial")
        return f"{label} denied verified {address} loopback request"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_sandbox_units(ctx: Context) -> str:
    if not (HOME / ".cargo" / "bin" / "cargo").exists():
        raise TestBlocked("Cargo not found")
    env = ctx.default_env.copy()
    env["CARGO_BUILD_JOBS"] = "1"
    env["CARGO_INCREMENTAL"] = "0"
    env["CARGO_PROFILE_TEST_DEBUG"] = "0"
    metadata = ctx.command(["cargo", "metadata", "--locked", "--offline", "--no-deps", "--format-version", "1"],
                           cwd=SOURCE, env=env, timeout=90, separate_stderr=True)
    require(metadata.returncode == 0, "Cannot inspect Cargo test targets")
    info = json.loads(metadata.stdout)
    pkg = next((p for p in info["packages"] if p["name"] == "codex-linux-sandbox"), None)
    require(pkg is not None, "Missing Linux sandbox package")
    has_library = any("lib" in t.get("kind", []) or "rlib" in t.get("kind", [])
                      for t in pkg.get("targets", []))
    argv = ["cargo", "test", "--locked", "-p", "codex-linux-sandbox"]
    if has_library:
        argv.append("--lib")
    result = ctx.command(argv, cwd=SOURCE, env=env, timeout=1800)
    require(result.returncode == 0, "Linux sandbox package tests failed")
    return "codex-linux-sandbox package tests completed successfully"


QUICK_TESTS = [
    TestCase("u01_native_arm64_build_current", "Native build provenance for tested executable", test_native_build_current),
    TestCase("u01_binary_execution_current", "Current Linux executable startup", test_binary_execution_current),
    TestCase("u01_cli_smoke_current", "Current CLI offline smoke tests", test_cli_smoke_current),
    TestCase("u01_argument_validation_current", "Current CLI argument rejection", test_argument_validation_current),
    TestCase("u01_prompt_routing_current", "Current nonempty prompt routing to local endpoint", test_prompt_routing_current),
    TestCase("u01_tui_auth_screen_current", "Isolated interactive authentication selection", test_tui_auth_screen_current),
    TestCase("u01_landlock_execution_current", "Current Landlock command execution", test_landlock_execution_current),
    TestCase("u01_landlock_ipv4_current", "Current Landlock IPv4 loopback isolation", lambda c: test_loopback(c, "127.0.0.1", legacy_landlock=True)),
    TestCase("u01_landlock_allowed_write_current", "Current Landlock authorized write", test_landlock_allowed_write_current),
    TestCase("u01_runtime_linkage", "ELF runtime dependencies", test_linkage),
    TestCase("u01_cargo_metadata", "Offline Cargo workspace metadata", test_cargo_metadata),
    TestCase("u01_completion_zsh", "Zsh completion generation", lambda c: test_completion(c, "zsh")),
    TestCase("u01_completion_fish", "Fish completion generation", lambda c: test_completion(c, "fish")),
    TestCase("u01_mcp_list_isolated_home", "MCP configuration in isolated HOME", test_mcp_list),
    TestCase("u01_resume_help", "Linux resume command registration", lambda c: test_help(c, "resume")),
    TestCase("u01_fork_help", "Linux fork command registration", lambda c: test_help(c, "fork")),
    TestCase("u01_landlock_readonly_cwd", "Landlock read-only working directory", test_readonly_cwd),
    TestCase("u01_landlock_symlink_escape", "Landlock symlink escape prevention", test_symlink_escape),
    TestCase("u01_landlock_ipv6_loopback", "Landlock IPv6 loopback isolation", test_ipv6_loopback),
    TestCase("u01_default_bubblewrap", "Default Bubblewrap command execution", test_bubblewrap),
    TestCase("u01_default_bubblewrap_readonly", "Default Bubblewrap read-only filesystem", test_bubblewrap_readonly),
    TestCase("u01_default_bubblewrap_outside_write", "Default Bubblewrap authorized write boundary", test_bubblewrap_outside_write),
    TestCase("u01_default_bubblewrap_symlink", "Default Bubblewrap symlink escape prevention", test_bubblewrap_symlink),
    TestCase("u01_default_bubblewrap_ipv4", "Default Bubblewrap IPv4 loopback isolation", lambda c: test_loopback(c, "127.0.0.1")),
    TestCase("u01_default_bubblewrap_ipv6", "Default Bubblewrap IPv6 loopback isolation", lambda c: test_loopback(c, "::1")),
]
EXTENDED_TESTS = [
    TestCase("u01_sandbox_unit_tests", "Cargo Linux sandbox package tests", test_sandbox_units, extended=True),
]
ALL_TESTS = QUICK_TESTS + EXTENDED_TESTS


def write_log(test_id: str, events: list[str], outcome: str, details: str) -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=f"{test_id}-",
                                     suffix=".log", dir=LOG_DIR, delete=False) as file:
        file.write("\n".join([f"Test: {test_id}", f"Status: {outcome}",
                              f"Details: {details}", "", *events]) + "\n")
        return file.name


def run_test(test: TestCase, ctx: Context) -> dict:
    ctx.current_id = test.test_id
    ctx.events = []
    now = utc_now()
    try:
        details = test.fn(ctx)
        status = "PASS"
    except TestSkipped as exc:
        status, details = "SKIPPED", str(exc)
    except TestBlocked as exc:
        status, details = "BLOCKED", str(exc)
    except TestFailure as exc:
        status, details = "FAIL", str(exc)
    except Exception as exc:
        status, details = "FAIL", f"Unexpected {type(exc).__name__}: {exc}"
        ctx.record(traceback.format_exc())
    log = write_log(test.test_id, ctx.events, status, details)
    return {"status": status, "description": test.description, "details": details,
            "last_executed_at": now, "fingerprint": ctx.env_id,
            "harness_version": HARNESS_VERSION, "test_revision": test_revision(test.test_id),
            "provenance": "AUTOMATED", "log": log}


def get_carried_status(info: dict, current_env_id: str) -> str:
    if info["scope"] == "linux" and info.get("assumed_import_fingerprint") != current_env_id:
        return "STALE_PRIOR_EVIDENCE"
    return "CARRIED_FORWARD"


def evaluate_acceptance(state: dict, env_id: str, source_integrity_ok: bool = True) -> dict:
    checks = []
    unresolved = []
    for test in ALL_TESTS:
        info = state["results"].get(test.test_id)
        if info is None:
            status, detail = "PENDING", "Not yet run"
        elif (info.get("fingerprint") != env_id
              or info.get("harness_version") != HARNESS_VERSION
              or info.get("test_revision", 1) != test_revision(test.test_id)
              or (info.get("status") == "PASS" and info.get("provenance") != "AUTOMATED")):
            status, detail = "STALE", "Prior result requires rerun for this build or test revision"
        else:
            status, detail = info["status"], info.get("details", "")
            if info.get("kind") == "KNOWN_BLOCKER":
                detail += " — imported known blocker; not silently retried"
        checks.append({"test_id": test.test_id, "description": test.description,
                       "status": status, "details": detail, "mandatory": not test.extended})
        if not test.extended and status != "PASS":
            unresolved.append({"test_id": test.test_id, "status": status})
    check_statuses = {check["test_id"]: check["status"] for check in checks}
    replacement_status = ("PASS" if all(check_statuses.get(test_id) == "PASS"
                                         for test_id in APPROVED_ARGUMENT_REPLACEMENT)
                          else "PENDING")
    evidence_gaps = [test_id for test_id, info in state["carried"].items()
                     if info["scope"] == "linux" and
                     not (test_id == "u01_argument_validation" and replacement_status == "PASS") and
                     not (CURRENT_EVIDENCE.get(test_id) and
                          all(check_statuses.get(replacement) == "PASS"
                              for replacement in CURRENT_EVIDENCE[test_id]))]
    automated_gate = "PASS" if not unresolved and source_integrity_ok else "PENDING"
    return {"automated_mandatory_gate": automated_gate,
            "full_u01": "NOT ACCEPTED" if automated_gate != "PASS" or evidence_gaps else "ACCEPTED",
            "unresolved_mandatory": unresolved, "historical_evidence_gaps": evidence_gaps,
            "approved_replacement": {"criterion": "u01_argument_validation",
                                     "status": replacement_status,
                                     "checks": list(APPROVED_ARGUMENT_REPLACEMENT),
                                     "basis": "Acceptance-owner-approved replacement; original Phases 14.2.41/42A unrecovered"},
            "source_integrity_ok": source_integrity_ok, "checks": checks}


def scenario_dashboard(state: dict, acceptance: dict) -> list[dict]:
    u01 = {"id": "U01", "name": "Ubuntu ARM64", "status": acceptance["full_u01"],
           "automated_result": acceptance["automated_mandatory_gate"],
           "evidence_complete": acceptance["full_u01"] == "ACCEPTED",
           "provenance": "current automated checks; approved argument replacement; original phases historical",
           "blocking_requirements": acceptance["historical_evidence_gaps"] +
                                    [item["test_id"] for item in acceptance["unresolved_mandatory"]],
           "next_action": ("Retain current evidence for release review"
                           if acceptance["full_u01"] == "ACCEPTED"
                           else "Run pending checks in Ubuntu ARM64; inspect unresolved evidence")}
    rows = [u01]
    for scenario_id, (name, requirement, prerequisite) in SCENARIO_REQUIREMENTS.items():
        historical = scenario_id in {"U05", "U06", "U07"}
        status = ("PREVIOUSLY ACCEPTED" if historical else
                  "PENDING" if scenario_id in {"U02", "U03"} else "BLOCKED")
        rows.append({"id": scenario_id, "name": name, "status": status,
                     "requirement": requirement, "automated_result": "NOT RUN",
                     "evidence_complete": False,
                     "provenance": "earlier environment; current release unverified" if historical else "none",
                     "blocking_requirements": [prerequisite],
                     "next_action": prerequisite})
    return rows


def report(state: dict, env: dict, env_id: str, counts: dict, acceptance: dict) -> str:
    def clean(x: object) -> str:
        return str(x).replace("|", "\\|").replace("\n", " ")
    lines = [
        "# DevoNow CLI — Incremental Release Acceptance",
        "",
        f"Generated: {utc_now()} UTC",
        "",
        f"**U01 overall: {acceptance['full_u01']}**",
        f"**Automated mandatory gate: {acceptance['automated_mandatory_gate']}**",
        "",
        "This report differentiates historical user-supplied evidence from tests actually executed by this harness.",
        "Historical results were **not** independently attested to the original source/binary hashes.",
        "",
        "## Environment identity",
        "",
        f"- Target: `{clean(env['platform'])}` / `{clean(env['machine'])}`",
        f"- Source digest: `{env['source_sha256']}`",
        f"- Executable digest: `{env['binary_sha256']}`",
        f"- Environment fingerprint: `{env_id}`",
        f"- AppArmor user namespace restriction: `{env['apparmor_userns']}`",
        "",
    ]
    if state.get("builds"):
        build = state["builds"][-1]
        lines.extend(["## Latest native build attempt", "",
                      f"- Started: `{clean(build['started_at'])}`; finished: `{clean(build['finished_at'])}`",
                      f"- Command: `{' '.join(build['command'])}`; exit: `{clean(build['exit_status'])}`",
                      f"- Toolchain: `{clean(build['rustc_version'])}` / `{clean(build['cargo_version'])}`",
                      f"- Source: `{clean(build['source_sha256'])}`; lockfile: `{clean(build['cargo_lock_sha256'])}`",
                      f"- Executable: `{clean(build.get('binary_sha256', 'missing'))}` / `{clean(build.get('binary_architecture', 'missing'))}`",
                      f"- Retained log: `{clean(build['log'])}`", ""])
    lines.extend([
        "## U01 — Carried-forward manual evidence (NOT re-executed)",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ])
    for test_id, info in state["carried"].items():
        if info["scope"] == "linux":
            lines.append(f"| `{test_id}` | {get_carried_status(info, env_id)} | {clean(info['evidence'])} |")
    replacement = acceptance["approved_replacement"]
    lines.extend(["", "## Approved replacement for historical argument criterion", "",
                  f"- Status: **{replacement['status']}**",
                  f"- Basis: {replacement['basis']}",
                  f"- Required current checks: {', '.join(replacement['checks'])}", ""])
    lines.extend(["", "## U01 — Automated and tracked checks", "",
                  "| Check | Status | Evidence / disposition |",
                  "|---|---|---|"])
    for check in acceptance["checks"]:
        lines.append(f"| `{check['test_id']}` | **{clean(check['status'])}** | {clean(check['details'])[:200]} |")
    lines.extend(["", "## Seventeen-scenario dashboard", "",
                  "ACCEPTED means all current required evidence passes. PREVIOUSLY ACCEPTED preserves earlier signoff only. PENDING has a known validation path. BLOCKED lacks a required external prerequisite. NOT ACCEPTED has unresolved current checks or evidence.",
                  "", "| ID | Status | Automated | Complete | Provenance | Blocker | Next action |",
                  "|---|---|---|---|---|---|---|"])
    for row in scenario_dashboard(state, acceptance):
        lines.append(f"| {row['id']} | {row['status']} | {row['automated_result']} | "
                     f"{row['evidence_complete']} | {clean(row['provenance'])} | "
                     f"{clean(', '.join(row['blocking_requirements']))} | {clean(row['next_action'])} |")
    lines.extend(["", "## Other scenarios", "",
                  "| Scenario | State | Next dependency |", "|---|---|---|"])
    for key, info in state["carried"].items():
        if info["scope"] == "earlier_environment":
            lines.append(f"| `{key}` | CARRIED_FORWARD / previously ACCEPTED | {clean(info['evidence'])} |")
    for key, (status, dep) in NON_LINUX.items():
        lines.append(f"| {key} | {status} | {dep} |")
    lines.extend(["", "## Execution summary", "",
                  f"- New checks executed this invocation: {counts.get('executed', 0)}",
                  f"- Cached checks skipped this invocation: {counts.get('cached', 0)}",
                  f"- Tests held for unchanged failure/blocker: {counts.get('held', 0)}",
                  f"- Outstanding mandatory U01 checks: {len(acceptance['unresolved_mandatory'])}",
                  f"- Historical U01 evidence gaps: {len(acceptance['historical_evidence_gaps'])}",
                  f"- Source snapshot integrity: {'PASS' if acceptance['source_integrity_ok'] else 'FAIL'}",
                  "- Extended unit tests are **opt-in** and do not block the automated mandatory gate.",
                  "- PASS from a manual transcript is labeled CARRIED_FORWARD, not a new automated PASS.",
                  "- A changed snapshot/binary/security environment invalidates applicable cached results.",
                  "- Never disable AppArmor or bypass sandbox protection to make a check pass.", ""])
    if acceptance["historical_evidence_gaps"]:
        lines.extend(["## Remaining U01 evidence gaps", ""])
        lines.extend(f"- `{test_id}` requires current evidence" for test_id in acceptance["historical_evidence_gaps"])
        lines.append("")
    return "\n".join(lines)


def report_payload(state: dict, env: dict, env_id: str, counts: dict,
                   source_integrity_ok: bool, acceptance: dict) -> dict:
    return {"generated": utc_now(), "environment": env, "fingerprint": env_id,
            "counts": counts, "carried": state["carried"], "results": state["results"],
            "builds": state.get("builds", []),
            "other_scenarios": NON_LINUX, "scenarios": scenario_dashboard(state, acceptance),
            "source_integrity_ok": source_integrity_ok,
            "acceptance": acceptance}


def terminal_summary(acceptance: dict, counts: dict) -> str:
    return (f"Executed: {counts['executed']} | Cached: {counts['cached']} | Held: {counts['held']}\n"
            f"Automated mandatory gate: {acceptance['automated_mandatory_gate']} "
            f"({len(acceptance['unresolved_mandatory'])} outstanding)\n"
            f"U01: {acceptance['full_u01']} "
            f"({len(acceptance['historical_evidence_gaps'])} historical evidence gaps)\n"
            f"Approved argument replacement: {acceptance['approved_replacement']['status']}\n"
            "Scenarios: U01 current evaluation; U05-U07 previously accepted; "
            "U02-U03 pending; U04/A01-A10 blocked")


def cache_disposition(old: dict | None, test: TestCase, env_id: str, retry: bool) -> str:
    if retry:
        return "RUN"
    if not old or old.get("fingerprint") != env_id or old.get("harness_version") != HARNESS_VERSION:
        return "RUN"
    if old.get("test_revision", 1) != test_revision(test.test_id):
        return "RUN"
    if old["status"] == "PASS":
        return "CACHED" if old.get("provenance") == "AUTOMATED" else "RUN"
    if old["status"] in {"FAIL", "BLOCKED", "SKIPPED"}:
        return "HELD"
    return "RUN"


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental acceptance harness (guest VM only)")
    parser.add_argument("--mode", choices=["pending", "report", "retry-bubblewrap", "extended", "build"], default="pending")
    args = parser.parse_args()

    print("=== DevoNow CLI incremental acceptance ===", flush=True)
    print(f"Mode: {args.mode}", flush=True)
    if args.mode == "build":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        pre_env, pre_id = fingerprint()
        state = load_state(pre_id)
        if not STATE_FILE.exists():
            atomic_json(STATE_FILE, state)
        build_native(state)
    env, env_id = fingerprint()
    print(f"Source SHA256: {env['source_sha256'][:16]}...", flush=True)
    print(f"Binary SHA256: {env['binary_sha256'][:16]}...", flush=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state(env_id)
    # Persist the original imported baseline immediately, even in report-only mode.
    if not STATE_FILE.exists():
        atomic_json(STATE_FILE, state)
    ctx = Context(env_id, state)
    counts = {"executed": 0, "cached": 0, "held": 0}

    if args.mode == "retry-bubblewrap":
        selected = [test for test in QUICK_TESTS if test.test_id.startswith("u01_default_bubblewrap")]
    elif args.mode == "report":
        selected = []
    elif args.mode == "extended":
        selected = ALL_TESTS
    else:
        selected = QUICK_TESTS

    for test in selected:
        old = state["results"].get(test.test_id)
        disposition = cache_disposition(old, test, env_id,
                                        args.mode == "retry-bubblewrap" or
                                        (args.mode == "build" and test.test_id == "u01_native_arm64_build_current"))
        if disposition == "CACHED":
            counts["cached"] += 1
            print(f"CACHED  {test.test_id}: PASS (same build and environment)", flush=True)
            continue
        if disposition == "HELD":
            counts["held"] += 1
            print(f"HELD    {test.test_id}: {old['status']} (unchanged; no implicit rerun)", flush=True)
            continue
        print(f"RUN     {test.test_id} ...", flush=True)
        outcome = run_test(test, ctx)
        if old is not None:
            state["history"].append({"at": utc_now(), "event": f"Superseded {test.test_id}",
                                     "result": old})
        state["results"][test.test_id] = outcome
        counts["executed"] += 1
        state["history"].append({"at": utc_now(), "event": f"{test.test_id}: {outcome['status']}",
                                 "fingerprint": env_id})
        atomic_json(STATE_FILE, state)
        print(f"{outcome['status']:7} {test.test_id}: {outcome['details']}", flush=True)

    # Enforce no source changes, including unexpected changes caused by tests.
    end_digest = source_digest(SOURCE)
    if end_digest != env["source_sha256"]:
        state["history"].append({"at": utc_now(), "event": "CRITICAL: SOURCE SNAPSHOT CHANGED DURING HARNESS"})
        atomic_json(STATE_FILE, state)
        print("CRITICAL: Source snapshot content changed during test execution", file=sys.stderr)
        integrity_failure = True
    else:
        integrity_failure = False
        print("PASS: Source snapshot content unchanged", flush=True)

    acceptance = evaluate_acceptance(state, env_id, not integrity_failure)
    text_report = report(state, env, env_id, counts, acceptance)
    report_json = report_payload(state, env, env_id, counts, not integrity_failure, acceptance)
    (REPORT_DIR / "latest-summary.md").write_text(text_report, encoding="utf-8")
    atomic_json(REPORT_DIR / "latest-results.json", report_json)
    print("\n=== Acceptance summary ===")
    print(terminal_summary(acceptance, counts))
    print(f"State: {STATE_FILE}")
    print(f"Report: {REPORT_DIR / 'latest-summary.md'}")
    if integrity_failure:
        return 3
    if any(state["results"].get(t.test_id, {}).get("status") == "FAIL"
           and state["results"][t.test_id].get("fingerprint") == env_id for t in selected):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
