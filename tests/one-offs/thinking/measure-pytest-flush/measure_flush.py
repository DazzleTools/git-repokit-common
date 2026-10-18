"""Does pytest's progress (dots, `s`, `F`) reach a PIPE as it happens?

The pre-push hook is about to stream pytest through `tee` so the person
sees progress during a push (today it captures everything and prints one
summary line after the run). Python block-buffers stdout when it is not a
terminal, so the dots might arrive in one burst at the end. This measures
the arrival time of each chunk pytest writes to a pipe, with and without
PYTHONUNBUFFERED=1, over a throwaway suite of 6 tests that sleep 0.4 s each.

    python measure_flush.py

Prints, per variant, the offset in seconds at which each chunk arrived. A
streaming run shows chunks spaced ~0.4 s apart; a buffered run shows them
all at the end.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUITE = """
import time
import pytest

@pytest.mark.parametrize("n", range(6))
def test_slow(n):
    time.sleep(0.4)
    assert True

@pytest.mark.skip(reason="one skip for the 's'")
def test_skipped():
    pass
"""


def run(label, extra_env):
    with tempfile.TemporaryDirectory(prefix="rk-flush-") as d:
        tests = Path(d, "tests")
        tests.mkdir()
        (tests / "test_slow.py").write_text(SUITE, encoding="utf-8")
        env = {**os.environ, **extra_env}
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        t0 = time.monotonic()
        proc = subprocess.Popen([sys.executable, "-P", "-m", "pytest", "-q", "--color=no",
                                 "-p", "no:cacheprovider", "tests"],
                                cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        arrivals = []
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            arrivals.append((round(time.monotonic() - t0, 2), chunk.decode("utf-8", "replace")))
        proc.wait()
        print(f"\n== {label}: exit {proc.returncode}, {len(arrivals)} chunks ==")
        for t, text in arrivals:
            print(f"  t+{t:5.2f}s  {text!r}")


if __name__ == "__main__":
    run("default (stdout is a pipe)", {})
    run("PYTHONUNBUFFERED=1", {"PYTHONUNBUFFERED": "1"})
