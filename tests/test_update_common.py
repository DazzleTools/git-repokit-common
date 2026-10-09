"""Tests for update-common.sh's pull around the version stamp (A4).

The pre-commit hook rewrites the version source's ``__version__`` line on
every commit, so a consumer's tree is often dirty by exactly that line, and
``git subtree pull`` refuses a dirty tree. The script must pull through that
one change -- after saving a snapshot and never losing the stamp -- and refuse
any other change, touching nothing.

Each test builds a throwaway upstream and a throwaway consumer under
``tmp_path`` (a real ``git subtree add``), with the ``repokit-common`` remote
pointing at the throwaway upstream, so no network and no real repository is
involved. Ordered by consequence score, highest first.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = ("update-common.sh", "sync-versions.py", "repokit_config.py")

GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "protocol.file.allow=always"]
# For git run by code under test (the script, dz): the same identity and no
# signing, through the environment, which every child git process reads.
UNSIGNED_ENV = {
    "GIT_CONFIG_COUNT": "5",
    "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "tag.gpgsign", "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "user.email", "GIT_CONFIG_VALUE_2": "t@example.invalid",
    "GIT_CONFIG_KEY_3": "user.name", "GIT_CONFIG_VALUE_3": "t",
    "GIT_CONFIG_KEY_4": "protocol.file.allow", "GIT_CONFIG_VALUE_4": "always",
}

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

VERSION_PY = 'MAJOR = 0\nMINOR = 1\nPATCH = 0\nPHASE = ""\n__version__ = "0.1.0_main_1-20260101-abcdef12"\n'


def _git(cwd, *args, check=True):
    return subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def _bash():
    """git's own bash (Git for Windows ships one; WSL's bash would not see C:)."""
    git = shutil.which("git")
    if git and os.name == "nt":
        root = Path(git).resolve().parents[1]
        for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if cand.exists():
                return str(cand)
    return shutil.which("bash")


def _subtree_available():
    r = subprocess.run(["git", "subtree", "-h"], capture_output=True, text=True)
    return "usage" in (r.stdout + r.stderr).lower()


@pytest.fixture
def world(tmp_path):
    if _bash() is None or not _subtree_available():
        pytest.skip("bash or git subtree not available")
    # upstream: the three tools plus a marker, one commit
    up = tmp_path / "upstream"
    up.mkdir()
    for name in TOOLS:
        shutil.copy(REPO / name, up / name)
    (up / "VERSION").write_text("0.9.0\n", encoding="utf-8")
    _git(up, "init", "-q", "-b", "main")
    _git(up, "add", "-A")
    _git(up, "commit", "-q", "-m", "upstream v1")
    # consumer: a Python project with the version source, the subtree, the remote
    c = tmp_path / "consumer"
    (c / "mypkg").mkdir(parents=True)
    (c / "pyproject.toml").write_text('[tool.repokit-common]\nversion-source = "mypkg/_version.py"\n', encoding="utf-8")
    (c / "mypkg" / "_version.py").write_text(VERSION_PY, encoding="utf-8")
    (c / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(c, "init", "-q", "-b", "main")
    _git(c, "add", "-A")
    _git(c, "commit", "-q", "-m", "consumer")
    _git(c, "remote", "add", "repokit-common", up.as_posix())
    _git(c, "subtree", "add", "--prefix=scripts/repokit-common", "repokit-common", "main", "--squash")
    # a second upstream commit to pull
    (up / "NEW-UPSTREAM-FILE").write_text("v2\n", encoding="utf-8")
    _git(up, "add", "-A")
    _git(up, "commit", "-q", "-m", "upstream v2")
    return c, up


def _update(c):
    # The script's own git calls (subtree pull: a squash and a merge commit) must
    # never sign: on a machine with commit.gpgsign=true they would open a GPG
    # dialog mid-test (they did once, 2026-10-09). GIT_CONFIG_* reaches every
    # git the script and anything it calls (dz git-snapshot included) run.
    env = dict(os.environ, PATH=os.environ.get("PATH", ""))
    env.update(UNSIGNED_ENV)
    return subprocess.run([_bash(), "scripts/repokit-common/update-common.sh"], cwd=c,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def _stamp(c, value="0.1.0_main_2-20260102-fedcba98"):
    f = c / "mypkg" / "_version.py"
    f.write_text(VERSION_PY.replace("0.1.0_main_1-20260101-abcdef12", value), encoding="utf-8")


def test_a_tree_dirty_by_only_the_stamp_is_pulled_and_the_stamp_restored(world):
    """CONSEQUENCE: 9 (safety) -- AC6: the common case. Only the __version__
    line differs; the pull goes through, the upstream change arrives, a backup
    was saved first, and the version file is re-stamped (not left at HEAD's
    stale stamp, and not lost)."""
    c, up = world
    _stamp(c)
    r = _update(c)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (c / "scripts" / "repokit-common" / "NEW-UPSTREAM-FILE").exists()
    git_dir = Path(_git(c, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = c / git_dir
    snapshots = _git(c, "for-each-ref", "refs/snapshots", check=False).stdout.strip()
    assert (git_dir / "repokit-common-stamp.bak").exists() or snapshots, r.stdout
    text = (c / "mypkg" / "_version.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.0_main_' in text and "abcdef12" not in text   # re-stamped, not HEAD's
    assert "Re-stamped mypkg/_version.py" in r.stdout


def test_any_other_change_is_refused_and_nothing_is_touched(world):
    """CONSEQUENCE: 9 (safety) -- AC6: a real edit beside the stamp refuses the
    pull, names the file, and leaves the tree and the subtree exactly as they
    were."""
    c, up = world
    _stamp(c)
    (c / "mypkg" / "work.py").write_text("x = 1\n", encoding="utf-8")
    _git(c, "add", "mypkg/work.py")
    before = _git(c, "status", "--porcelain").stdout
    r = _update(c)
    assert r.returncode == 1
    assert "Refusing to pull" in r.stdout and "mypkg/work.py" in r.stdout
    assert not (c / "scripts" / "repokit-common" / "NEW-UPSTREAM-FILE").exists()
    assert _git(c, "status", "--porcelain").stdout == before


def test_a_version_file_edit_that_is_not_the_stamp_is_refused(world):
    """CONSEQUENCE: 8 (safety) -- a changed MINOR line in the version file is
    work, not a stamp: refused, the file kept as edited."""
    c, up = world
    f = c / "mypkg" / "_version.py"
    edited = VERSION_PY.replace("MINOR = 1", "MINOR = 2")
    f.write_text(edited, encoding="utf-8")
    r = _update(c)
    assert r.returncode == 1 and "Refusing to pull" in r.stdout
    assert f.read_text(encoding="utf-8") == edited


def test_a_clean_tree_pulls_as_before(world):
    """CONSEQUENCE: 6 (behaviour) -- nothing dirty: the plain pull, no
    snapshot, no re-stamp."""
    c, up = world
    r = _update(c)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (c / "scripts" / "repokit-common" / "NEW-UPSTREAM-FILE").exists()
    assert "Re-stamped" not in r.stdout and "Saved" not in r.stdout
