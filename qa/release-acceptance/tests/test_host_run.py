"""Check guest-home discovery without starting Lima or changing retained evidence."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "host-run.sh"


class HostRunTest(unittest.TestCase):
    def test_uses_discovered_guest_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(SCRIPT, root / "host-run.sh")
            (root / "suite").mkdir()
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_lima = fake_bin / "limactl"
            fake_lima.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$FAKE_LIMA_CALLS"\n'
                'if [ "$1" = shell ] && [ "$4" = sh ]; then\n'
                '  printf %s "$FAKE_GUEST_HOME"\n'
                'fi\n'
            )
            fake_lima.chmod(0o755)
            calls = root / "calls"
            for guest_home in ("/home/qa-alpha", "/opt/qa-beta"):
                with self.subTest(guest_home=guest_home):
                    calls.write_text("")
                    env = {
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_LIMA_CALLS": str(calls),
                        "FAKE_GUEST_HOME": guest_home,
                    }
                    result = subprocess.run(
                        ["bash", str(root / "host-run.sh"), "report"],
                        env=env, capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    recorded = calls.read_text()
                    self.assertIn(f"{guest_home}/devonow-acceptance-suite", recorded)
                    self.assertIn(
                        f"{guest_home}/.local/state/devonow-acceptance", recorded
                    )


if __name__ == "__main__":
    unittest.main()
