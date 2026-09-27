"""Tests for hooks/pre-push's syntax check and test gate (#10).

Each test builds a throwaway repository under ``tmp_path`` with a bare remote
beside it, installs the hook from this checkout, and pushes for real, so git
feeds the hook its stdin and runs it with git's own shell. The consumer layout
is the common one: this checkout's repokit_config.py vendored at
scripts/repokit-common/.

Safety: every git command runs with ``cwd`` inside ``tmp_path``, signing off,
and ``core.hooksPath`` pinned to the temp repository's own hooks directory, so
a global hooks path or a mutated hook can never reach a real repository. The
only remote is a bare repository under ``tmp_path``. The tests the hook runs
are files these tests write; none touch anything outside ``tmp_path``.

Ordered by consequence score, highest first.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pre-push"
CONFIG_TOOL = ROOT / "repokit_config.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

PASSING = "def test_ok():\n    assert True\n"
FAILING = "def test_bad():\n    assert False, 'deliberate failure'\n"


def _git(cwd, *args, hooks_dir=None, check=True):
    cmd = [
        "git",
        "-c", "user.email=hooktest@example.invalid",
        "-c", "user.name=hooktest",
        "-c", "commit.gpgsign=false",
        "-c", "tag.gpgsign=false",
    ]
    if hooks_dir is not None:
        cmd += ["-c", f"core.hooksPath={hooks_dir}"]
    cmd += list(args)
    # The hook prints UTF-8 (emoji); decode it as such on every platform.
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    """A consumer repository with the hook installed and a bare remote."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", str(remote))
    hooks = root / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    shutil.copy(HOOK, hooks / "pre-push")
    (hooks / "pre-push").chmod(0o755)
    vendored = root / "scripts" / "repokit-common"
    vendored.mkdir(parents=True)
    shutil.copy(CONFIG_TOOL, vendored / "repokit_config.py")
    _w(root / "README.md", "seed\n")
    return root, hooks, remote


def _push(repo, files, branch="main"):
    """Write ``files`` ({relative path: text}), commit on ``branch``, push it."""
    root, hooks, remote = repo
    current = _git(root, "branch", "--show-current").stdout.strip()
    if branch != current:
        _git(root, "checkout", "-q", "-b", branch)
    for rel, text in files.items():
        _w(root / rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change", hooks_dir=hooks)
    r = _git(root, "push", "-q", "origin", branch, hooks_dir=hooks, check=False)
    landed = _git(remote, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
    return r, r.stdout + r.stderr, landed.returncode == 0


def test_failing_tests_block_a_push_to_main_and_show_why(repo):
    """CONSEQUENCE: 9 (safety) -- a failing test stops a push to main, and the output names the failure."""
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING})
    assert r.returncode != 0 and not landed
    assert "BLOCKED: Cannot push to main with failing tests" in out
    assert "deliberate failure" in out
    assert "1 failed" in out


def test_a_runner_that_cannot_start_blocks_and_is_not_called_failing_tests(repo):
    """CONSEQUENCE: 9 (safety) -- a broken conftest stops the push on any branch, reported as a runner problem with pytest's own error."""
    r, out, landed = _push(repo, {
        "tests/conftest.py": "raise RuntimeError('conftest is broken')\n",
        "tests/test_a.py": PASSING,
    }, branch="feature")
    assert r.returncode != 0 and not landed
    assert "the test runner could not run" in out
    assert "conftest is broken" in out
    assert "Some tests failed" not in out


@pytest.mark.skipif(sys.version_info < (3, 11), reason="python -P needs 3.11+")
def test_a_py_package_at_the_root_does_not_shadow_pytest(repo):
    """CONSEQUENCE: 8 (behaviour) -- a project package named py/ (SmartResCalc) no longer breaks pytest's own `import py`."""
    r, out, landed = _push(repo, {
        "py/__init__.py": "",
        "tests/test_a.py": PASSING,
    })
    assert r.returncode == 0 and landed, out
    assert "All tests passed: 1 passed" in out


def test_without_dash_p_the_fallback_still_keeps_the_root_off_sys_path(repo, tmp_path, monkeypatch):
    """CONSEQUENCE: 6 (behaviour) -- on a Python older than 3.11 (simulated: a python that rejects -P) the py/ package still does not shadow pytest."""
    shim_dir = tmp_path / "shim"
    real = Path(sys.executable).as_posix()
    if len(real) > 1 and real[1] == ":":  # C:/x -> /c/x for git's sh
        real = "/" + real[0].lower() + real[2:]
    shim = _w(shim_dir / "python",
              "#!/bin/sh\n"
              'if [ "$1" = "-P" ]; then echo "Unknown option: -P" >&2; exit 2; fi\n'
              f'exec "{real}" "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(shim_dir) + os.pathsep + os.environ["PATH"])
    probe = subprocess.run(["sh", "-c", "python -P -c ''; echo rc=$?"], capture_output=True, text=True)
    if "rc=2" not in probe.stdout:
        pytest.skip("could not put a python shim in front of the real python")
    r, out, landed = _push(repo, {
        "py/__init__.py": "",
        "tests/test_a.py": PASSING,
    })
    assert r.returncode == 0 and landed, out
    assert "All tests passed: 1 passed" in out


def test_passing_tests_push_and_print_the_count(repo):
    """CONSEQUENCE: 7 (behaviour) -- a passing run pushes and says how many tests ran."""
    r, out, landed = _push(repo, {"tests/test_a.py": PASSING + "\n\ndef test_two():\n    pass\n"})
    assert r.returncode == 0 and landed, out
    assert "All tests passed: 2 passed" in out


def test_failing_tests_on_a_feature_branch_warn_and_push(repo):
    """CONSEQUENCE: 6 (behaviour) -- off main a failing test is reported, not blocked (unchanged policy)."""
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING}, branch="feature")
    assert r.returncode == 0 and landed, out
    assert "Some tests failed" in out
    assert "Consider fixing tests before pushing" in out


def test_failing_tests_block_a_push_to_master_too(repo):
    """CONSEQUENCE: 8 (safety) -- master is protected exactly like main."""
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING}, branch="master")
    assert r.returncode != 0 and not landed
    assert "BLOCKED: Cannot push to master with failing tests" in out


@pytest.mark.parametrize("code", [1, 3])
def test_test_command_replaces_pytest_and_its_failure_blocks_main(repo, code):
    """CONSEQUENCE: 8 (safety) -- any non-zero test-command exit (1 included) blocks main; pytest is not run at all."""
    r, out, landed = _push(repo, {
        ".repokit-common.toml": '[tool.repokit-common]\ntest-command = "python check.py"\n',
        "check.py": f"import sys\nprint('script says no')\nsys.exit({code})\n",
        "tests/test_a.py": PASSING,
    })
    assert r.returncode != 0 and not landed
    assert f"test-command failed (exit {code})" in out
    assert "script says no" in out
    assert "All tests passed" not in out and "scope:" not in out


def test_a_passing_test_command_pushes_without_running_pytest(repo):
    """CONSEQUENCE: 7 (behaviour) -- test-command wins over pytest: a failing pytest file beside it is not run."""
    r, out, landed = _push(repo, {
        "pyproject.toml": '[project]\nname = "p"\n\n[tool.repokit-common]\ntest-command = "python check.py && python check.py"\n',
        "check.py": "print('script ok')\n",
        "tests/test_a.py": FAILING,
    })
    assert r.returncode == 0 and landed, out
    assert "test-command passed" in out


def test_a_non_ascii_test_command_runs(repo):
    """CONSEQUENCE: 6 (behaviour) -- a setting with non-ASCII text (a check mark) is read and run, not reported as an unreadable config."""
    r, out, landed = _push(repo, {
        ".repokit-common.toml": '[tool.repokit-common]\ntest-command = "echo ✓ café"\n',
        "tests/test_a.py": PASSING,
    })
    assert r.returncode == 0 and landed, out
    assert "test-command passed" in out


def test_an_unreadable_config_blocks_the_push(repo):
    """CONSEQUENCE: 7 (safety) -- a malformed settings table stops the push instead of silently using defaults."""
    r, out, landed = _push(repo, {
        ".repokit-common.toml": '[tool.repokit-common]\ntest-command = "unterminated\n',
        "tests/test_a.py": PASSING,
    })
    assert r.returncode != 0 and not landed
    assert "settings could not be read" in out
    assert "cannot read" in out


def test_declared_testpaths_gate_the_push(repo):
    """CONSEQUENCE: 8 (behaviour) -- tests beside the code, declared in testpaths, gate the push (#10)."""
    r, out, landed = _push(repo, {
        "pytest.ini": "[pytest]\ntestpaths = pkg\n",
        "pkg/test_inline.py": FAILING,
    })
    assert r.returncode != 0 and not landed
    assert "testpaths declared in pytest.ini" in out
    assert "deliberate failure" in out


def test_one_offs_thinking_and_the_vendored_copy_are_not_collected(repo):
    """CONSEQUENCE: 7 (behaviour) -- moment-in-time scripts and repokit-common's own tests never gate a consumer's push."""
    r, out, landed = _push(repo, {
        "tests/test_a.py": PASSING,
        "tests/one-offs/test_scratch.py": FAILING,
        "tests/one-offs/thinking/test_idea.py": FAILING,
        "tests/thinking/test_idea.py": FAILING,
        "scripts/repokit-common/tests/test_vendored.py": FAILING,
    })
    assert r.returncode == 0 and landed, out
    assert "All tests passed: 1 passed" in out


def test_a_vendored_copy_mounted_under_tests_is_not_collected(repo):
    """CONSEQUENCE: 6 (behaviour) -- wherever the copy is mounted, even inside tests/, its own tests never gate the consumer."""
    root = repo[0]
    shutil.move(str(root / "scripts" / "repokit-common"), str(root / "tests" / "tools" / "repokit-common"))
    r, out, landed = _push(repo, {
        "tests/test_a.py": PASSING,
        "tests/tools/repokit-common/tests/test_vendored.py": FAILING,
    })
    assert r.returncode == 0 and landed, out
    assert "All tests passed: 1 passed" in out


def test_repokit_common_as_the_project_gates_its_own_tests(repo):
    """CONSEQUENCE: 7 (behaviour) -- with the config tool at the repository root (repokit-common itself) nothing is excluded as vendored."""
    root = repo[0]
    shutil.move(str(root / "scripts" / "repokit-common" / "repokit_config.py"), str(root / "repokit_config.py"))
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING})
    assert r.returncode != 0 and not landed
    assert "deliberate failure" in out


def test_no_tests_is_a_notice_and_the_push_continues(repo):
    """CONSEQUENCE: 6 (behaviour) -- zero configuration for a project with no tests."""
    r, out, landed = _push(repo, {"app.py": "x = 1\n"})
    assert r.returncode == 0 and landed, out
    assert "No test files found" in out


def test_test_files_without_tests_are_a_notice_not_a_failure(repo):
    """CONSEQUENCE: 6 (behaviour) -- pytest exit 5 (nothing collected) reads as no tests, not as failing tests."""
    r, out, landed = _push(repo, {"tests/test_empty.py": "X = 1\n"})
    assert r.returncode == 0 and landed, out
    assert "No tests collected" in out
    assert "failed" not in out


def test_a_root_level_syntax_error_blocks_the_push(repo):
    """CONSEQUENCE: 7 (safety) -- a broken version.py at the root is caught even when the package lives elsewhere."""
    r, out, landed = _push(repo, {
        "pkg/__init__.py": "",
        "version.py": "VERSION = (\n",
    })
    assert r.returncode != 0 and not landed
    assert "Python syntax errors found" in out
    assert "version.py" in out


def test_print_warning_false_silences_the_print_count(repo):
    """CONSEQUENCE: 4 (behaviour) -- a CLI project can turn off the print() warning; it stays on by default."""
    noisy = "".join(f"print({i})\n" for i in range(25))
    r, out, landed = _push(repo, {"pkg/__init__.py": "", "pkg/cli.py": noisy})
    assert r.returncode == 0 and landed, out
    assert "Many print() statements found (25 in pkg/)" in out
    r, out, landed = _push(repo, {
        ".repokit-common.toml": "[tool.repokit-common]\nprint-warning = false\n",
        "pkg/cli2.py": noisy,
    })
    assert r.returncode == 0 and landed, out
    assert "print() statements" not in out
