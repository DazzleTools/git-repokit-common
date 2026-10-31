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


def _git(cwd, *args, hooks_dir=None, check=True, env=None):
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
                          encoding="utf-8", errors="replace", check=check, env=env)


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
    shutil.copy(HOOK.parent / "lib.sh", hooks / "lib.sh")  # the hook sources it from beside itself
    shutil.copytree(HOOK.parent / "profiles", hooks / "profiles")  # and each language's profile
    (hooks / "pre-push").chmod(0o755)
    vendored = root / "scripts" / "repokit-common"
    vendored.mkdir(parents=True)
    shutil.copy(CONFIG_TOOL, vendored / "repokit_config.py")
    _w(root / "README.md", "seed\n")
    return root, hooks, remote


def _push(repo, files, branch="main", env=None):
    """Write ``files`` ({relative path: text}), commit on ``branch``, push it (with ``env`` when given)."""
    root, hooks, remote = repo
    current = _git(root, "branch", "--show-current").stdout.strip()
    if branch != current:
        _git(root, "checkout", "-q", "-b", branch)
    for rel, text in files.items():
        _w(root / rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change", hooks_dir=hooks)
    r = _git(root, "push", "-q", "origin", branch, hooks_dir=hooks, check=False, env=env)
    landed = _git(remote, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
    return r, r.stdout + r.stderr, landed.returncode == 0


def test_failing_tests_block_a_push_to_main_and_show_why(repo):
    """CONSEQUENCE: 9 (safety) -- a failing test stops a push to main, and the output names the failure."""
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING})
    assert r.returncode != 0 and not landed
    assert "BLOCKED: Cannot push to main with failing tests" in out
    assert "deliberate failure" in out
    assert "1 failed" in out


BROKEN_CONFTEST = {
    "tests/conftest.py": "raise RuntimeError('conftest is broken')\n",
    "tests/test_a.py": PASSING,
}


def test_a_runner_that_cannot_start_blocks_a_gated_branch(repo):
    """CONSEQUENCE: 9 (safety) -- a broken conftest stops a push to a gated branch (staging), reported as a runner problem with pytest's own error."""
    r, out, landed = _push(repo, BROKEN_CONFTEST, branch="staging")
    assert r.returncode != 0 and not landed
    assert "The test runner could not run" in out
    assert "conftest is broken" in out
    assert "Some tests failed" not in out
    assert "BLOCKED: Cannot push to staging until the tests can run" in out


def test_a_runner_that_cannot_start_warns_on_an_ungated_branch(repo):
    """CONSEQUENCE: 7 (behaviour) -- off the gated branches the same problem is reported, with pytest's error, and the push goes through (#14)."""
    r, out, landed = _push(repo, BROKEN_CONFTEST, branch="feature")
    assert r.returncode == 0 and landed, out
    assert "The test runner could not run" in out and "conftest is broken" in out
    assert "feature is not a gated branch" in out


def test_strict_branches_setting_replaces_the_default_set(repo):
    """CONSEQUENCE: 7 (behaviour) -- strict-branches patterns decide the gate: release/* blocks, and main is no longer gated once the setting omits it."""
    cfg = {".repokit-common.toml": '[tool.repokit-common]\nstrict-branches = ["release/*"]\n'}
    r, out, landed = _push(repo, {**cfg, "tests/test_a.py": FAILING}, branch="release/1.0")
    assert r.returncode != 0 and not landed
    assert "BLOCKED: Cannot push to release/1.0 with failing tests" in out
    r, out, landed = _push(repo, {}, branch="main")
    assert r.returncode == 0 and landed, out
    assert "main is not a gated branch" in out


def test_failing_tests_block_live_by_default(repo):
    """CONSEQUENCE: 8 (safety) -- live (git-repokit's production branch) is in the default gated set."""
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING}, branch="live")
    assert r.returncode != 0 and not landed
    assert "BLOCKED: Cannot push to live with failing tests" in out


def test_the_print_count_ignores_the_vendored_copy_and_tests(repo):
    """CONSEQUENCE: 4 (behaviour) -- with no package directory, prints in the vendored repokit-common copy and in tests/ are not counted."""
    noisy = "".join(f"print({i})\n" for i in range(25))
    r, out, landed = _push(repo, {"scripts/repokit-common/noisy.py": noisy,
                                  "tests/test_a.py": PASSING + noisy.replace("print", "    print").join(["def helper():\n", ""])})
    assert r.returncode == 0 and landed, out
    assert "print() statements" not in out


def test_the_python_profile_runs_as_before_with_no_setting(repo):
    """CONSEQUENCE: 8 (safety) -- AC2: a Python package that sets nothing is
    detected as python and gets exactly the old checks: a pdb statement blocks
    the push, named as the python profile's."""
    r, out, landed = _push(repo, {"pyproject.toml": '[project]\nname = "p"\n',
                                  "mypkg/__init__.py": "import pdb\n",
                                  "tests/test_a.py": PASSING})
    assert r.returncode != 0 and not landed
    assert "Product languages: python" in out
    assert "Debugger statements found (python)" in out and "pdb statements" in out


def test_a_typescript_project_gets_its_own_checks_and_loses_the_python_warning(repo):
    """CONSEQUENCE: 8 (behaviour) -- AC3: languages = ["typescript"]: a
    debugger statement blocks the push; the Python package warning is gone even
    though a pyproject.toml with [project] is present; and once the statement
    is removed the push goes through."""
    cfg = {".repokit-common.toml": '[tool.repokit-common]\nlanguages = ["typescript"]\n',
           "pyproject.toml": '[project]\nname = "tooling"\n', "tests/test_a.py": PASSING}
    r, out, landed = _push(repo, {**cfg, "src/index.ts": "export const x = 1;\n  debugger;\n"})
    assert r.returncode != 0 and not landed
    assert "Product languages: typescript" in out
    assert "Debugger statements found (typescript)" in out
    assert "No Python package directory" not in out
    r, out, landed = _push(repo, {"src/index.ts": "export const x = 1;\n"})
    assert r.returncode == 0 and landed, out
    assert "No Python package directory" not in out and "pdb" not in out


def test_a_c_cpp_project_is_detected_and_runs_no_product_checks(repo):
    """CONSEQUENCE: 7 (behaviour) -- a CMake project with no setting is detected
    as c-cpp: the Python checks (pdb, print count, and since 0.4.3 the syntax
    check, Q261023-01) do not run on its tooling scripts; the tests still do."""
    noisy = "import pdb\n" + "".join(f"print({i})\n" for i in range(25))
    r, out, landed = _push(repo, {"CMakeLists.txt": "project(demo)\n", "tools/gen.py": noisy,
                                  "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "Product languages: c-cpp" in out
    assert "c-cpp: no product checks (the build and tests are the gate)" in out   # its profile, not the fallback
    assert "Debugger statements found" not in out and "print() statements" not in out
    assert "Checking Python syntax" not in out
    assert "All tests passed" in out


BROKEN_PY = "def broken(:\n    pass\n"


def test_python_syntax_still_runs_for_a_project_that_is_python_only_by_default(repo):
    """CONSEQUENCE: 9 (safety) -- a project that declares nothing and shows no
    markers is python by default (9 of 50 consumers, M1) and keeps the syntax
    check: a broken tooling script still stops the push. Anchor: red if the
    step keyed on the declared or detected languages only."""
    r, out, landed = _push(repo, {"tools/gen.py": BROKEN_PY, "tests/test_a.py": PASSING})
    assert r.returncode != 0 and not landed
    assert "Product languages: python" in out
    assert "Python syntax errors found" in out


def test_a_declared_javascript_project_gets_no_python_syntax_step(repo):
    """CONSEQUENCE: 8 (behaviour) -- Q261023-01: languages = ["javascript"]
    runs no Python syntax check, so a Python file it carries is not compiled
    and the push goes through."""
    r, out, landed = _push(repo, {
        ".repokit-common.toml": '[tool.repokit-common]\nlanguages = ["javascript"]\n',
        "tools/gen.py": BROKEN_PY, "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "Product languages: javascript" in out
    assert "Checking Python syntax" not in out and "Python syntax" not in out


def test_a_python_check_command_replaces_the_syntax_check_and_its_failure_blocks_main(repo):
    """CONSEQUENCE: 8 (safety) -- check-command.python replaces the syntax
    check (a broken file it does not look at passes) and its non-zero exit
    blocks a gated branch, with the command's own output shown."""
    cfg = ('[tool.repokit-common]\n\n[tool.repokit-common.check-command]\n'
           'python = "python lint.py"\n')
    r, out, landed = _push(repo, {
        ".repokit-common.toml": cfg, "tools/gen.py": BROKEN_PY, "tests/test_a.py": PASSING,
        "lint.py": "import sys\nprint('lint says no')\nsys.exit(1)\n"})
    assert r.returncode != 0 and not landed
    assert "check-command: python lint.py" in out and "lint says no" in out
    assert "python check-command failed (exit 1)" in out
    assert "BLOCKED: Cannot push to main with a failing python check" in out
    assert "Checking Python syntax" not in out


def test_a_failing_check_command_warns_on_an_ungated_branch(repo):
    """CONSEQUENCE: 6 (behaviour) -- off the gated branches a failing
    check-command is reported and the push goes through, as failing tests are."""
    cfg = '[tool.repokit-common]\ncheck-command.python = "python lint.py"\n'
    r, out, landed = _push(repo, {
        ".repokit-common.toml": cfg, "tests/test_a.py": PASSING,
        "lint.py": "import sys\nsys.exit(3)\n"}, branch="feature")
    assert r.returncode == 0 and landed, out
    assert "python check-command failed (exit 3)" in out
    assert "feature is not a gated branch" in out


def test_an_empty_check_command_turns_the_python_step_off(repo):
    """CONSEQUENCE: 6 (behaviour) -- check-command.python = "" turns the
    syntax check off, and says so."""
    cfg = '[tool.repokit-common]\ncheck-command.python = ""\n'
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "tools/gen.py": BROKEN_PY,
                                  "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "python: check step off (check-command is empty)" in out
    assert "Checking Python syntax" not in out


def test_a_passing_python_check_command_is_the_whole_step(repo):
    """CONSEQUENCE: 7 (behaviour) -- once check-command.python passes, the
    syntax check does not run after it: the command replaces the default, it
    is not added in front of it."""
    cfg = '[tool.repokit-common]\ncheck-command.python = "echo lint-ok"\n'
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "tools/gen.py": BROKEN_PY,
                                  "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "python check-command passed" in out
    assert "Checking Python syntax" not in out


def test_a_missing_profiles_folder_stops_the_push(repo):
    """CONSEQUENCE: 9 (safety) -- without hooks/profiles/ every language's
    checks would vanish silently (a broken Python file would push); the hook
    refuses instead and says how to repair the install."""
    shutil.rmtree(repo[1] / "profiles")
    r, out, landed = _push(repo, {"tools/gen.py": BROKEN_PY, "tests/test_a.py": PASSING})
    assert r.returncode != 0 and not landed
    assert "profiles/ is not beside it" in out


def test_profiles_are_found_when_the_hook_is_run_by_a_relative_path_from_a_subfolder(repo):
    """CONSEQUENCE: 7 (safety) -- pre-push cds to the repository root before
    loading profiles, so profiles/ must be found from the hooks folder
    resolved before the cd, not from a relative $0 (here ../.git/hooks/pre-push
    run from sub/): the checks run, and a broken Python file is still caught."""
    root, hooks, _ = repo
    _w(root / "tools" / "gen.py", BROKEN_PY)
    (root / "sub").mkdir()
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c", hooks_dir=hooks)
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not found")
    r = subprocess.run([bash, "../.git/hooks/pre-push", "origin", "unused"], cwd=root / "sub",
                       input=f"refs/heads/main {sha} refs/heads/main {'0' * 40}\n",
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    assert "profiles/ is not beside it" not in out, out
    assert r.returncode != 0 and "Python syntax errors found" in out, out


def test_a_two_language_project_runs_both_profiles(repo):
    """CONSEQUENCE: 8 (behaviour) -- languages = ["typescript", "python"] (the
    claude-bookmarks shape: a TypeScript plugin with Python tooling and tests)
    loads both profiles: typescript's debugger check stops a debugger
    statement, and once it is gone python's syntax check still runs."""
    cfg = '[tool.repokit-common]\nlanguages = ["typescript", "python"]\n'
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "tests/test_a.py": PASSING,
                                  "plugin/src/index.ts": "export const x = 1;\n  debugger;\n"})
    assert r.returncode != 0 and not landed
    assert "Python syntax check passed" in out
    assert "Debugger statements found (typescript)" in out
    r, out, landed = _push(repo, {"plugin/src/index.ts": "export const x = 1;\n"})
    assert r.returncode == 0 and landed, out
    assert "Python syntax check passed" in out
    assert "typescript: no product checks" not in out and "python: no product checks" not in out


def test_a_new_profile_file_is_picked_up_without_a_hook_change(repo):
    """CONSEQUENCE: 7 (behaviour) -- a language gains checks by adding
    hooks/profiles/<language>.sh (repokit-common's own, or later a pack's):
    its product step runs, and a language with no profile says so."""
    _w(repo[1] / "profiles" / "rust.sh", 'rk_profile_rust_product() {\n    echo "  RUST-PRODUCT ran"\n}\n')
    cfg = '[tool.repokit-common]\nlanguages = ["rust", "zig"]\n'
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "RUST-PRODUCT ran" in out
    assert "zig: no product checks for this language yet" in out
    assert "No such file" not in out           # zig has no profile file, and none is sourced


def test_a_language_name_cannot_reach_outside_the_profiles_folder(repo):
    """CONSEQUENCE: 8 (safety) -- languages are names, not paths: "../evil"
    does not source hooks/evil.sh."""
    _w(repo[1] / "evil.sh", 'echo "EVIL-SOURCED"\n')
    cfg = '[tool.repokit-common]\nlanguages = ["../evil"]\n'
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "EVIL-SOURCED" not in out


@pytest.mark.parametrize("profile", sorted((HOOK.parent / "profiles").glob("*.sh")), ids=lambda p: p.name)
def test_profiles_are_posix_sh(profile):
    """CONSEQUENCE: 7 (safety) -- pre-commit runs under sh and sources every
    profile, so a bash-only construct would break commits on a system whose sh
    is not bash (dash on Debian and Ubuntu)."""
    import re
    code = "\n".join(line.split("#", 1)[0] for line in profile.read_text(encoding="utf-8").splitlines())
    # "[[ " is bash's test; "[[:space:]]" (a regex class inside a grep pattern) is not.
    for name, pattern in (("[[ test", r"\[\[\s"), ("array", r"\w\+?=\("), ("PIPESTATUS", r"PIPESTATUS"),
                          ("here-string", r"<<<"), ("function keyword", r"^\s*function\s"),
                          ("indirect expansion", r"\$\{!")):
        assert not re.search(pattern, code, re.MULTILINE), f"{profile.name} uses a bash {name}"


PARADOX_CFG = '[tool.repokit-common]\nlanguages = ["paradox"]\nparadox-game = "ck3"\n'
DESCRIPTOR = 'version="1.0.0"\nname="Demo"\nsupported_version="1.20.*"\n'


def _stub_tiger(tmp_path, name="ck3-tiger", fatal=0, error=0, fail=False, old=False):
    """A fake Tiger on its own PATH folder that behaves as the real one was
    measured to (tests/one-offs/thinking/measure-tiger, ck3-tiger 1.19.0):
    ck3/imperator take the descriptor.mod FILE and vic3 the mod FOLDER, and
    anything else cannot run (exit 1); a run that can start ends with the
    summary line and exits 0 whatever it found. ``old`` adds Tiger's
    "PLEASE UPDATE!" banner; ``fail`` makes it unable to run."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / name
    wants = '[ -d "$t" ]' if name.startswith("vic3") else 'case "$t" in *.mod) [ -f "$t" ] ;; *) false ;; esac'
    stub.write_text(
        "#!/bin/sh\n"
        'echo "TIGER-RAN $*"\n'
        't="$1"; [ "$1" = --no-color ] && t="$2"\n'
        f'{wants} || {{ echo "cannot read $t"; exit 1; }}\n'
        + ("exit 1\n" if fail else "")
        + ('echo "PLEASE UPDATE!"\n' if old else "")
        + f'echo "fatal: {fatal}, error: {error}, warning: 3, untidy: 0, tips: 0"\nexit 0\n',
        encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    return {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}


def _tiger_report(repo, name="ck3-tiger"):
    return (repo[0] / ".git" / f"repokit-{name}.txt").read_text(encoding="utf-8")


paradox_tiger_absent = pytest.mark.skipif(
    shutil.which("ck3-tiger") is not None, reason="a real ck3-tiger is on PATH")


def test_a_paradox_mod_is_linted_by_tiger_and_gets_no_python_checks(repo, tmp_path):
    """CONSEQUENCE: 8 (behaviour) -- languages = ["paradox"] with paradox-game
    = "ck3": ck3-tiger runs on mod/descriptor.mod (the file, as ck3-tiger
    takes it), without colour in captured output; the push shows its summary
    and where the full report is; no Python syntax check runs, so a broken
    tooling script does not stop the push."""
    env = _stub_tiger(tmp_path)
    r, out, landed = _push(repo, {".repokit-common.toml": PARADOX_CFG, "mod/descriptor.mod": DESCRIPTOR,
                                  "tools/link_mod.py": BROKEN_PY}, env=env)
    assert r.returncode == 0 and landed, out
    assert "Product languages: paradox" in out
    assert "Linting the mod with ck3-tiger (mod/descriptor.mod)" in out
    assert "[OK] ck3-tiger: fatal: 0, error: 0, warning: 3" in out
    assert "full report:" in out and "repokit-ck3-tiger.txt" in out
    assert "TIGER-RAN --no-color mod/descriptor.mod" in _tiger_report(repo)
    assert "TIGER-RAN" not in out                        # the report is not streamed into the push
    assert "Checking Python syntax" not in out
    assert "paradox: no debugger or print checks" in out


def test_tiger_findings_are_summarized_and_never_block(repo, tmp_path):
    """CONSEQUENCE: 7 (behaviour) -- Tiger is advisory: findings on main
    (Tiger still exits 0) are shown as its summary with a warning, an old
    Tiger's version banner becomes one note, and the push goes through."""
    env = _stub_tiger(tmp_path, fatal=2, error=5, old=True)
    r, out, landed = _push(repo, {".repokit-common.toml": PARADOX_CFG, "mod/descriptor.mod": DESCRIPTOR}, env=env)
    assert r.returncode == 0 and landed, out
    assert "[!] ck3-tiger: fatal: 2, error: 5, warning: 3, untidy: 0, tips: 0 (not blocking)" in out
    assert "ck3-tiger is older than the game it found" in out


def test_a_tiger_that_cannot_run_is_reported_and_never_blocks(repo, tmp_path):
    """CONSEQUENCE: 7 (behaviour) -- Tiger exits 1 only when it cannot run (a
    bad path, no game): the push says the mod was not linted, shows Tiger's
    own words, and goes through."""
    env = _stub_tiger(tmp_path, fail=True)
    r, out, landed = _push(repo, {".repokit-common.toml": PARADOX_CFG, "mod/descriptor.mod": DESCRIPTOR}, env=env)
    assert r.returncode == 0 and landed, out
    assert "ck3-tiger could not run (exit 1) -- the mod was not linted; not blocking" in out
    assert "TIGER-RAN" in out                            # its own output, shown because it failed


@paradox_tiger_absent
def test_a_paradox_mod_without_tiger_installed_skips_cleanly(repo):
    """CONSEQUENCE: 7 (behaviour) -- with no ck3-tiger on PATH the push goes
    through and says how to get a linter."""
    r, out, landed = _push(repo, {".repokit-common.toml": PARADOX_CFG, "mod/descriptor.mod": DESCRIPTOR})
    assert r.returncode == 0 and landed, out
    assert "paradox: ck3-tiger is not on PATH -- linter skipped" in out


@pytest.mark.parametrize("cfg_extra, files, expected", [
    ('paradox-game = "vic3"\n', {"descriptor.mod": DESCRIPTOR}, "Linting the mod with vic3-tiger (.)"),
    ('paradox-game = "stellaris"\n', {"mod/descriptor.mod": DESCRIPTOR}, "paradox: no default linter for stellaris"),
    ("", {"mod/descriptor.mod": DESCRIPTOR}, 'paradox: set paradox-game (e.g. "ck3") to choose a linter'),
    ('paradox-game = "ck3"\n', {"mod/readme.txt": "x\n"}, "paradox: no descriptor.mod in mod/ or at the root"),
])
def test_the_paradox_game_and_the_mod_folder_choose_the_linter(repo, tmp_path, cfg_extra, files, expected):
    """CONSEQUENCE: 6 (behaviour) -- paradox-game picks the Tiger build (vic3
    lints a mod whose descriptor.mod sits at the root); a game with no Tiger,
    no game, or no descriptor.mod each say why nothing ran, and the push goes through."""
    env = _stub_tiger(tmp_path, name="vic3-tiger")
    cfg = '[tool.repokit-common]\nlanguages = ["paradox"]\n' + cfg_extra
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, **files}, env=env)
    assert r.returncode == 0 and landed, out
    assert expected in out
    if "Linting" in expected:
        # vic3-tiger takes the mod folder (here the root), not the descriptor file
        assert "vic3-tiger: fatal: 0, error: 0" in out
        assert "TIGER-RAN --no-color ." in _tiger_report(repo, "vic3-tiger")
    else:
        # a skip says why once, and nothing runs after it
        assert "is not on PATH" not in out and "Linting the mod" not in out and "could not run" not in out


def test_a_paradox_check_command_replaces_tiger(repo, tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- check-command.paradox replaces the Tiger
    default, and gates like any check-command."""
    env = _stub_tiger(tmp_path)
    cfg = PARADOX_CFG + 'check-command.paradox = "echo my-own-lint && exit 1"\n'
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "mod/descriptor.mod": DESCRIPTOR}, env=env)
    assert r.returncode != 0 and not landed
    assert "my-own-lint" in out and "Linting the mod" not in out
    assert not (repo[0] / ".git" / "repokit-ck3-tiger.txt").exists()
    assert "BLOCKED: Cannot push to main with a failing paradox check" in out


@pytest.mark.parametrize("lang", ["javascript", "c-cpp"])
def test_a_check_command_gives_a_language_without_a_default_a_step(repo, lang):
    """CONSEQUENCE: 6 (behaviour) -- a language with no default check runs the
    one the project configures, including a name with a hyphen (c-cpp's
    variable is REPOKIT_CHECK_COMMAND_C_CPP)."""
    cfg = (f'[tool.repokit-common]\nlanguages = ["{lang}"]\n'
           f'check-command.{lang} = "echo lint-would-run"\n')
    r, out, landed = _push(repo, {".repokit-common.toml": cfg, "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert f"Checking {lang}..." in out and "lint-would-run" in out
    assert f"{lang} check-command passed" in out


def test_a_push_git_rejected_says_nothing_to_push(repo):
    """CONSEQUENCE: 3 (behaviour) -- when git passes no refs (it rejected them all), the hook says so instead of calling it a tag-only push."""
    root, hooks, remote = repo
    _push(repo, {"tests/test_a.py": PASSING})
    _w(root / "other.txt", "x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ahead", hooks_dir=hooks)
    _git(root, "push", "-q", "origin", "main", hooks_dir=hooks)
    _git(root, "reset", "-q", "--hard", "HEAD~1")  # this tmp_path repository only
    _w(root / "diverged.txt", "x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "diverged", hooks_dir=hooks)
    r = _git(root, "push", "origin", "main", hooks_dir=hooks, check=False)  # non-fast-forward
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "Tag-only" not in out
    assert "Nothing to push" in out


def test_captured_output_is_plain_text(repo):
    """CONSEQUENCE: 5 (behaviour) -- output that is not a terminal (IDE panels, CI, tools) uses [OK]/[X] markers and no escape codes."""
    r, out, landed = _push(repo, {"tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "[OK] All tests passed" in out
    assert "\x1b" not in out and "✓" not in out


@pytest.mark.parametrize("var", ["FORCE_COLOR", "PY_COLORS"])
def test_a_colour_forcing_environment_keeps_the_summary_plain(repo, var):
    """CONSEQUENCE: 5 (behaviour) -- FORCE_COLOR or PY_COLORS (set by CI and some terminals) cannot put pytest's escape codes into the summary the hook prints."""
    # One variable at a time: drop any colour settings inherited from the shell
    # running the suite (Claude Code exports FORCE_COLOR) so each case stands alone.
    env = {k: v for k, v in os.environ.items() if k not in ("FORCE_COLOR", "PY_COLORS", "NO_COLOR")}
    env[var] = "1"
    r, out, landed = _push(repo, {"tests/test_a.py": PASSING}, env=env)
    assert r.returncode == 0 and landed, out
    assert "[OK] All tests passed" in out and "1 passed" in out
    assert "\x1b" not in out


def test_output_rich_setting_forces_symbols_and_colour(repo):
    """CONSEQUENCE: 4 (behaviour) -- output = "rich" gives the symbols and colour even when captured."""
    r, out, landed = _push(repo, {".repokit-common.toml": '[tool.repokit-common]\noutput = "rich"\n',
                                  "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "✓" in out and "\x1b[" in out


def test_the_environment_beats_the_output_setting(repo):
    """CONSEQUENCE: 4 (behaviour) -- REPOKIT_OUTPUT=plain wins over output = "rich" for one run."""
    env = dict(os.environ, REPOKIT_OUTPUT="plain")
    r, out, landed = _push(repo, {".repokit-common.toml": '[tool.repokit-common]\noutput = "rich"\n',
                                  "tests/test_a.py": PASSING}, env=env)
    assert r.returncode == 0 and landed, out
    assert "[OK] All tests passed" in out and "\x1b" not in out


def test_an_empty_strict_branches_override_ungates_one_push(repo):
    """CONSEQUENCE: 6 (behaviour) -- REPOKIT_STRICT_BRANCHES= loosens the gate for one run, even though the default would block main."""
    # An explicit environment: on Windows, setting a variable to "" inside this
    # Python process deletes it, while a child's environment block keeps it --
    # which is what `REPOKIT_STRICT_BRANCHES= git push` from a shell does.
    env = dict(os.environ, REPOKIT_STRICT_BRANCHES="")
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING}, branch="main", env=env)
    assert r.returncode == 0 and landed, out
    assert "main is not a gated branch" in out


@pytest.mark.skipif(sys.version_info < (3, 11), reason="python -P needs 3.11+")
def test_a_py_package_at_the_root_does_not_shadow_pytest(repo):
    """CONSEQUENCE: 8 (behaviour) -- a project package named py/ (SmartResCalc) no longer breaks pytest's own `import py`."""
    r, out, landed = _push(repo, {
        "py/__init__.py": "",
        "tests/test_a.py": PASSING,
    })
    assert r.returncode == 0 and landed, out
    assert "All tests passed" in out and "1 passed" in out


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
    assert "All tests passed" in out and "1 passed" in out


def test_passing_tests_push_and_print_the_count(repo):
    """CONSEQUENCE: 7 (behaviour) -- a passing run pushes and says how many tests ran
    (pytest's own closing line, shown as it happens; the hook's verdict no longer repeats it)."""
    r, out, landed = _push(repo, {"tests/test_a.py": PASSING + "\n\ndef test_two():\n    pass\n"})
    assert r.returncode == 0 and landed, out
    assert "All tests passed" in out and "2 passed" in out


def test_progress_is_shown_while_the_tests_run(repo):
    """CONSEQUENCE: 6 (behaviour) -- pytest's progress (dots, `s`, the percentage) reaches the
    person during the run instead of a blank screen and one summary line at the end (0.4.1)."""
    r, out, landed = _push(repo, {"tests/test_a.py": PASSING + "\n\ndef test_two():\n    pass\n"})
    assert r.returncode == 0 and landed, out
    assert "[100%]" in out


def test_a_failure_is_shown_once_not_twice(repo):
    """CONSEQUENCE: 5 (behaviour) -- with the output streamed, the hook no longer reprints
    pytest's tail or its counts: the closing "1 failed" line appears exactly once."""
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING})
    assert r.returncode != 0 and not landed
    assert "deliberate failure" in out and "Some tests failed" in out
    assert out.count("1 failed in") == 1, out


def test_the_syntax_check_leaves_no_bytecode_in_the_project(repo):
    """CONSEQUENCE: 7 (safety) -- compileall's bytecode goes to a throwaway folder, never
    beside the sources: in a template tree it was copied into every project made from it
    (git-repokit 0.7.2 found seven such files in its output)."""
    root = repo[0]
    r, out, landed = _push(repo, {"mypkg/__init__.py": "x = 1\n", "mypkg/mod.py": "y = 2\n",
                                  "tests/test_a.py": PASSING})
    assert r.returncode == 0 and landed, out
    assert "Python syntax check passed" in out
    # pytest writes tests/__pycache__ for the tests it runs; the check is compileall's
    # output beside the package and at the root, which the old hook left behind.
    assert not (root / "mypkg" / "__pycache__").exists()
    assert not (root / "__pycache__").exists()


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
    assert "All tests passed" in out and "1 passed" in out


def test_a_vendored_copy_mounted_under_tests_is_not_collected(repo):
    """CONSEQUENCE: 6 (behaviour) -- wherever the copy is mounted, even inside tests/, its own tests never gate the consumer."""
    root = repo[0]
    shutil.move(str(root / "scripts" / "repokit-common"), str(root / "tests" / "tools" / "repokit-common"))
    r, out, landed = _push(repo, {
        "tests/test_a.py": PASSING,
        "tests/tools/repokit-common/tests/test_vendored.py": FAILING,
    })
    assert r.returncode == 0 and landed, out
    assert "All tests passed" in out and "1 passed" in out


def test_repokit_common_as_the_project_gates_its_own_tests(repo):
    """CONSEQUENCE: 7 (behaviour) -- with the config tool at the repository root (repokit-common itself) nothing is excluded as vendored."""
    root = repo[0]
    shutil.move(str(root / "scripts" / "repokit-common" / "repokit_config.py"), str(root / "repokit_config.py"))
    r, out, landed = _push(repo, {"tests/test_a.py": FAILING})
    assert r.returncode != 0 and not landed
    assert "deliberate failure" in out


def test_no_tests_is_a_notice_and_the_push_continues(repo):
    """CONSEQUENCE: 6 (behaviour) -- zero configuration for a project with no
    tests: a notice. A project that is not a Python package (TypeScript, C,
    Rust) gets no warning about a missing package; one that declares itself a
    package in pyproject.toml still does."""
    r, out, landed = _push(repo, {"app.py": "x = 1\n"})
    assert r.returncode == 0 and landed, out
    assert "No test files found" in out
    assert "No Python package" not in out
    r, out, landed = _push(repo, {"pyproject.toml": '[project]\nname = "p"\n'})
    assert r.returncode == 0 and landed, out
    assert "No Python package directory found" in out


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
