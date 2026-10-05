"""Test for conftest.py at the repokit-common root: a consumer's bare `pytest`
does not collect the vendored copy's own suite.

Builds a throwaway consumer under ``tmp_path``; git runs only there.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_a_consumers_bare_pytest_skips_the_vendored_suite(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- in a consumer, `pytest` at the root runs
    the consumer's tests only; the vendored suite still runs when named."""
    proj = tmp_path / "proj"
    vend = proj / "scripts" / "repokit-common"
    (proj / "tests").mkdir(parents=True)
    (vend / "tests").mkdir(parents=True)
    shutil.copy(REPO / "conftest.py", vend / "conftest.py")
    (proj / "tests" / "test_mine.py").write_text("def test_mine():\n    pass\n", encoding="utf-8")
    (vend / "tests" / "test_vendored.py").write_text("def test_vendored():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)

    def collected(*args):
        r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                            "-p", "no:cacheprovider", *args],
                           cwd=proj, capture_output=True, text=True)
        return r.stdout

    bare = collected()
    assert "test_mine" in bare and "test_vendored" not in bare
    assert "test_vendored" in collected("scripts/repokit-common/tests")
