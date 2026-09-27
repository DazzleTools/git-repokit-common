"""Tests for install-hooks.sh: existing hooks are backed up before replacement.

Safety: the installer writes into whatever repository git resolves from its
working directory, so every run happens with ``cwd`` inside a ``tmp_path``
repository, GIT_DIR and GIT_WORK_TREE removed from the environment, and a
check beforehand that git resolves the hooks directory inside ``tmp_path``.
The installer is run from this checkout, which it only reads.

Ordered by consequence score, highest first.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install-hooks.sh"
HOOKS = ("pre-commit", "post-commit", "pre-push")

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _bash():
    """Git's own bash on Windows (never WSL's System32 bash); bash on PATH elsewhere."""
    if sys.platform == "win32":
        git = Path(shutil.which("git")).resolve()
        # git.exe lives in <Git>/cmd, <Git>/bin or <Git>/mingw64/bin; bash in <Git>/bin.
        for base in list(git.parents)[:3]:
            for cand in (base / "bin" / "bash.exe", base / "usr" / "bin" / "bash.exe"):
                if cand.is_file():
                    return str(cand)
        return None
    return shutil.which("bash")


def _env():
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, env=_env(),
                          capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    bash = _bash()
    if bash is None:
        pytest.skip("git's bash not found")
    root = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    (root / "README.md").write_text("seed\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "seed")
    return root, bash


def _hooks_dir(where, tmp_path):
    common = Path(_git(where, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    hooks = common / "hooks"
    assert tmp_path.resolve() in hooks.resolve().parents, f"refusing to install outside tmp_path: {hooks}"
    hooks.mkdir(exist_ok=True)
    return hooks


def _install(where, bash):
    # Bytes, not text: text-mode stdin on Windows sends "y\r\n", and the
    # installer's prompt then reads "y\r" and cancels.
    r = subprocess.run([bash, str(INSTALLER)], cwd=where, env=_env(), input=b"y\n",
                       capture_output=True)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    assert r.returncode == 0, out
    return out


def _backups(hooks, name):
    return sorted(hooks.glob(f"{name}.backup-*"))


def test_an_existing_hook_is_saved_before_it_is_replaced(repo, tmp_path):
    """CONSEQUENCE: 8 (safety) -- a project's own hook is kept as <hook>.backup-<timestamp>, content intact, and the new hook is installed."""
    root, bash = repo
    hooks = _hooks_dir(root, tmp_path)
    for name in HOOKS:
        (hooks / name).write_text(f"#!/bin/sh\n# the project's own {name}\n", encoding="utf-8")
    out = _install(root, bash)
    for name in HOOKS:
        saved = _backups(hooks, name)
        assert len(saved) == 1, (name, out)
        assert saved[0].read_text(encoding="utf-8") == f"#!/bin/sh\n# the project's own {name}\n"
        assert (hooks / name).read_bytes() == (ROOT / "hooks" / name).read_bytes()
    assert "saved as pre-commit.backup-" in out


def test_a_worktree_install_backs_up_the_shared_hooks(repo, tmp_path):
    """CONSEQUENCE: 7 (safety) -- from a git worktree the shared hooks directory is the one backed up and replaced."""
    root, bash = repo
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "release", str(wt))
    hooks = _hooks_dir(wt, tmp_path)
    assert hooks == _hooks_dir(root, tmp_path)
    (hooks / "pre-push").write_text("#!/bin/sh\n# old\n", encoding="utf-8")
    _install(wt, bash)
    assert [p.read_text(encoding="utf-8") for p in _backups(hooks, "pre-push")] == ["#!/bin/sh\n# old\n"]


def test_a_fresh_install_makes_no_backups(repo, tmp_path):
    """CONSEQUENCE: 4 (behaviour) -- nothing to replace, nothing to back up."""
    root, bash = repo
    hooks = _hooks_dir(root, tmp_path)
    for name in HOOKS:
        (hooks / name).unlink(missing_ok=True)
    _install(root, bash)
    assert not list(hooks.glob("*.backup-*"))
    for name in HOOKS:
        assert (hooks / name).read_bytes() == (ROOT / "hooks" / name).read_bytes()


def test_reinstalling_identical_hooks_makes_no_backups(repo, tmp_path):
    """CONSEQUENCE: 4 (behaviour) -- running the installer twice does not pile up copies of the same hook."""
    root, bash = repo
    hooks = _hooks_dir(root, tmp_path)
    _install(root, bash)
    out = _install(root, bash)
    assert not list(hooks.glob("*.backup-*")), out
    assert "already up to date" in out
