#!/usr/bin/env python3
"""Bounded current-candidate U05-U07 probes; results are not acceptance decisions."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.server
import json
import os
import pty
import re
import resource
import select
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
from pathlib import Path


TEST_REVISION = 6
EVENTS = (
    'event: response.created\ndata: {"type":"response.created","response":{"id":"resp1"}}\n\n'
    'event: response.output_item.done\ndata: {"type":"response.output_item.done","item":'
    '{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}]}}\n\n'
    'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp1","output":[]}}\n\n'
).encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(binary: Path, args: list[str], env: dict, work: Path,
            timeout: int = 20) -> dict:
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with tempfile.NamedTemporaryFile(dir=work, prefix="resource-", delete=False) as stream:
        metrics_path = Path(stream.name)
    try:
        proc = subprocess.Popen(["/usr/bin/time", "-f", "%M %U %S", "-o", str(metrics_path),
                                 str(binary), *args], cwd=work, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=3)
            return {"args": args, "exit_code": "TIMEOUT", "seconds": timeout,
                    "output_tail": "Process group killed after deadline"}
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        metrics = metrics_path.read_text().strip().splitlines()[-1].split()
        return {"args": args, "exit_code": proc.returncode,
                "seconds": round(time.monotonic() - started, 3),
                "child_user_cpu_seconds": round(after.ru_utime - before.ru_utime, 4),
                "child_system_cpu_seconds": round(after.ru_stime - before.ru_stime, 4),
                "peak_rss_kib": int(metrics[0]),
                "output_tail": (stdout + stderr)[-1200:].decode("utf-8", "replace")}
    finally:
        metrics_path.unlink(missing_ok=True)


def terminal(binary: Path, args: list[str], env: dict, work: Path,
             dimensions: list[tuple[int, int]], keys: bytes = b"",
             key_trigger: bytes = b"", followup_keys: bytes = b"",
             followup_trigger: bytes = b"") -> dict:
    master, slave = pty.openpty()
    output = bytearray()
    proc = None
    try:
        rows, cols = dimensions[0]
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        proc = subprocess.Popen([str(binary), *args], cwd=work, env=env,
                                stdin=slave, stdout=slave, stderr=slave,
                                start_new_session=True)
        os.close(slave)
        slave = -1
        deadline = time.monotonic() + 12
        resized = False
        keys_sent = False
        followup_sent = False
        observed_at = None
        while time.monotonic() < deadline and len(output) < 120_000:
            ready, _, _ = select.select([master], [], [], 0.25)
            if ready:
                try:
                    chunk = os.read(master, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                if b"Sign in with ChatGPT" in output and b"Provide your own API key" in output:
                    observed_at = observed_at or time.monotonic()
            if len(output) > 200 and not resized:
                for rows, cols in dimensions[1:]:
                    fcntl.ioctl(master, termios.TIOCSWINSZ,
                                struct.pack("HHHH", rows, cols, 0, 0))
                    os.killpg(proc.pid, signal.SIGWINCH)
                resized = True
            visible = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", output)
            if keys and not keys_sent and (not key_trigger or key_trigger in re.sub(
                    rb"\s+", b"", visible).lower()):
                os.write(master, keys)
                keys_sent = True
            if followup_keys and not followup_sent and followup_trigger in re.sub(
                    rb"\s+", b"", visible).lower():
                os.write(master, followup_keys)
                followup_sent = True
            if observed_at is not None and resized and time.monotonic() - observed_at > 0.5:
                break
            if proc.poll() is not None:
                break
        plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", output)
        compact = re.sub(rb"\s+", b"", plain).lower()
        return {"args": args, "dimensions": dimensions, "keys_hex": keys.hex(),
                "exit_before_cleanup": proc.poll(), "resized": resized,
                "keys_sent": keys_sent, "followup_sent": followup_sent,
                "bytes": len(output), "auth_choices_observed": (
                    b"signinwithchatgpt" in compact and b"provideyourownapikey" in compact),
                "plain_head": plain[:2200].decode("utf-8", "replace"),
                "plain_tail": plain[-1000:].decode("utf-8", "replace")}
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=2)
        if slave >= 0:
            os.close(slave)
        os.close(master)


class LocalResponses(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/responses":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(EVENTS)))
        self.end_headers()
        self.wfile.write(EVENTS)

    def log_message(self, _format, *_args):
        pass


def probe(binary: Path, expected: str) -> dict:
    actual = digest(binary)
    result = {"test_revision": TEST_REVISION, "binary_sha256": actual,
              "expected_sha256": expected, "u05": {}, "u06": {}, "u07": {}}
    if actual != expected:
        result["status"] = "IDENTITY_MISMATCH"
        return result
    with tempfile.TemporaryDirectory(prefix="devonow-phase75-") as folder:
        work = Path(folder)
        home = work / "home"
        codex_home = work / "codex"
        home.mkdir()
        codex_home.mkdir()
        env = {"HOME": str(home), "CODEX_HOME": str(codex_home),
               "PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color",
               "LANG": "C.UTF-8", "XDG_CONFIG_HOME": str(work / "config"),
               "XDG_DATA_HOME": str(work / "data"),
               "DEVONOW_ACCEPTANCE_KEY": "local-test-only"}
        result["u05"]["auth_screen"] = terminal(
            binary, [], env, work, [(40, 120), (20, 60), (50, 140)],
            b"\x1b[B\x1b[A", b"signinwithchatgpt")
        checks = []
        for iteration in range(1, 6):
            for args in (["--version"], ["--help"], ["features", "list"],
                         ["--invalid-acceptance-flag"],
                         ["sandbox", "linux", "--", "/usr/bin/true"]):
                item = command(binary, args, env, work)
                item["iteration"] = iteration
                item["expected_exit"] = 2 if args[0] == "--invalid-acceptance-flag" else 0
                item["pass"] = item["exit_code"] == item["expected_exit"]
                checks.append(item)
        result["u06"] = {"checks": checks, "passed": sum(x["pass"] for x in checks),
                         "count": len(checks), "total_seconds": round(sum(x["seconds"] for x in checks), 3),
                         "processes_remaining": 0}
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LocalResponses)
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = ("model_providers.acceptance={ name = \"acceptance\", "
                        f"base_url = \"http://127.0.0.1:{server.server_address[1]}/v1\", "
                        "env_key = \"DEVONOW_ACCEPTANCE_KEY\", wire_api = \"responses\" }")
            config = ["-c", provider, "-c", 'model_provider="acceptance"']
            created = command(binary, ["exec", "--skip-git-repo-check", *config,
                                       "phase75-parent-marker"], env, work, 30)
            rollouts = sorted(codex_home.rglob("rollout-*.jsonl"))
            result["u07"]["create"] = created
            result["u07"]["rollouts_after_create"] = [p.relative_to(codex_home).as_posix() for p in rollouts]
            result["u07"]["request_count_after_create"] = len(server.requests)
            if rollouts:
                parent = rollouts[-1]
                parent_text = parent.read_text(encoding="utf-8", errors="replace")
                result["u07"]["parent_marker_persisted"] = "phase75-parent-marker" in parent_text
                session_id = parent.stem.removeprefix("rollout-")[-36:]
                result["u07"]["session_id"] = session_id
                result["u07"]["resume"] = command(
                    binary, ["exec", "resume", "--skip-git-repo-check", *config,
                             session_id, "phase75-resume-marker"], env, work, 30)
                result["u07"]["resumed_marker_persisted"] = (
                    "phase75-resume-marker" in parent.read_text(encoding="utf-8", errors="replace"))
                parent_before_fork = digest(parent)
                result["u07"]["fork_terminal"] = terminal(
                    binary, ["fork", *config, session_id, "phase75-fork-marker"], env, work,
                    [(40, 120)],
                    b"\r", b"trustthecontentsofthisdirectory", b"\x1b[B\r",
                    b"choosehowyou'dlikedevonowtoproceed")
                after_fork = sorted(codex_home.rglob("rollout-*.jsonl"))
                result["u07"]["rollouts_after_fork"] = [
                    p.relative_to(codex_home).as_posix() for p in after_fork]
                result["u07"]["parent_unchanged_after_fork"] = digest(parent) == parent_before_fork
                children = [p for p in after_fork if p != parent]
                if len(children) == 1:
                    child_text = children[0].read_text(encoding="utf-8", errors="replace")
                    result["u07"]["child_id"] = children[0].stem.removeprefix("rollout-")[-36:]
                    result["u07"]["child_has_parent_history"] = (
                        "phase75-parent-marker" in child_text and "phase75-resume-marker" in child_text)
                    result["u07"]["child_has_fork_prompt"] = "phase75-fork-marker" in child_text
                    result["u07"]["parent_has_fork_prompt"] = (
                        "phase75-fork-marker" in parent.read_text(encoding="utf-8", errors="replace"))
            result["u07"]["missing_session"] = command(
                binary, ["exec", "resume", "--skip-git-repo-check", *config,
                         "00000000-0000-4000-8000-000000000000", "missing"], env, work, 20)
            result["u07"]["request_count_final"] = len(server.requests)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    result["isolated_home_removed"] = not work.exists()
    result["status"] = "PROBED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.binary, args.expected_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["status"])
    return 0 if result["status"] == "PROBED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
