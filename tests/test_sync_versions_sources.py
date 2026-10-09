"""Tests for sync-versions.py's version-source kinds and the new-version link.

A version source is a Python file (as always), a plain text file holding
``x.y.z[-phase]`` (a ``VERSION`` file -- repokit-common's own), or a C/C++
header of ``#define`` lines (the C/C++ template's ``version.h``). The last two
carry no ``__version__`` stamp and are edited on their bytes. Also here:
``versioning = "off"`` and the compare link a new version gets (A6).

Each test runs the real script end to end in a throwaway git project with the
script vendored at scripts/, as a hook would run it. Ordered by consequence
score, highest first.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "sync-versions.py"

HEADER = (
    b"\xef\xbb\xbf"                                   # a BOM, as Visual Studio writes
    b"#ifndef MY_TOOL_VERSION_H\r\n"
    b"#define MY_TOOL_VERSION_H\r\n"
    b"/* \xe9dition: a stray cp1252 byte in a comment must survive */\r\n"
    b"#define MY_TOOL_VERSION_MAJOR 0\r\n"
    b"#define MY_TOOL_VERSION_MINOR 1\r\n"
    b"#define MY_TOOL_VERSION_PATCH 0\r\n"
    b'#define MY_TOOL_VERSION_PHASE ""\r\n'
    b'#define MY_TOOL_VERSION_STRING "0.1.0"\r\n'
    b"#endif\r\n"
)

CHANGELOG = """\
# Changelog

## [Unreleased]

## [0.3.7] - 2026-10-09

### Added
- a thing

## [0.3.6] - 2026-10-08

[Unreleased]: https://github.com/acme/tool/compare/v0.3.6...HEAD
[0.3.6]: https://github.com/acme/tool/compare/v0.3.5...v0.3.6
"""


def _project(tmp_path, config, files):
    """A throwaway git project: ``config`` is the .repokit-common.toml body,
    ``files`` {relative path: bytes or str}."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(TOOL, root / "scripts" / "sync-versions.py")
    shutil.copy(REPO / "repokit_config.py", root / "scripts" / "repokit_config.py")
    (root / ".repokit-common.toml").write_text("[tool.repokit-common]\n" + config, encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"],
                ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)
    return root


def _run(root, *args):
    return subprocess.run([sys.executable, "scripts/sync-versions.py", *args],
                          cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)


PLAIN = 'version-source = "VERSION"\nrepo-url = "https://github.com/acme/tool"\ntag-format = "human"\n'
HEADER_CFG = 'version-source = "include/my_tool/version.h"\nrepo-url = "https://github.com/acme/tool"\n'


# --- the C header: bytes preserved ------------------------------------------

def test_a_header_bump_changes_only_the_version_text(tmp_path):
    """CONSEQUENCE: 9 (safety) -- the anchor for the C/C++ layer: a bump of a
    version.h rewrites the four version defines and not one other byte -- the
    BOM, the CRLF endings and a non-UTF-8 byte in a comment all survive."""
    root = _project(tmp_path, HEADER_CFG, {"include/my_tool/version.h": HEADER})
    r = _run(root, "--bump", "minor")
    assert r.returncode == 0, r.stdout + r.stderr
    got = (root / "include/my_tool/version.h").read_bytes()
    expected = (HEADER.replace(b"_VERSION_MINOR 1", b"_VERSION_MINOR 2")
                      .replace(b'_VERSION_STRING "0.1.0"', b'_VERSION_STRING "0.2.0"'))
    assert got == expected
    assert _run(root, "--check").returncode == 0


def test_a_header_set_and_phase_write_every_define(tmp_path):
    """CONSEQUENCE: 7 (behaviour) -- --set and --phase reach MAJOR, MINOR,
    PATCH, PHASE and STRING; the human form carries the phase."""
    root = _project(tmp_path, HEADER_CFG, {"include/my_tool/version.h": HEADER})
    r = _run(root, "--set", "1.2.3", "--phase", "beta", "--force")
    assert r.returncode == 0, r.stdout + r.stderr
    text = (root / "include/my_tool/version.h").read_bytes().decode("latin-1")
    for line in ("_VERSION_MAJOR 1", "_VERSION_MINOR 2", "_VERSION_PATCH 3",
                 '_VERSION_PHASE "beta"', '_VERSION_STRING "1.2.3-beta"'):
        assert line in text, line


HEADER_FULL = HEADER.replace(
    b'#define MY_TOOL_VERSION_PHASE ""\r\n',
    b'#define MY_TOOL_VERSION_PHASE ""\r\n#define MY_TOOL_VERSION_PRE_RELEASE_NUM 1\r\n#define MY_TOOL_PROJECT_PHASE "alpha"\r\n')


def test_a_header_with_pre_release_num_and_project_phase_round_trips(tmp_path):
    """CONSEQUENCE: 8 (behaviour) -- parity with _version.py: --pre-num lands in
    the header's PRE_RELEASE_NUM define, --phase leaves PROJECT_PHASE alone
    (read-only, as in Python), and -v reports the project phase it read.
    Measured 2026-10-09 before the fix: the define was present and unread, and
    --pre-num 2 exited 0 having changed nothing."""
    root = _project(tmp_path, HEADER_CFG, {"include/my_tool/version.h": HEADER_FULL})
    r = _run(root, "--pre-num", "2")
    assert r.returncode == 0 and "not stored" not in r.stderr, r.stdout + r.stderr
    got = (root / "include/my_tool/version.h").read_bytes()
    assert got == HEADER_FULL.replace(b"_VERSION_PRE_RELEASE_NUM 1", b"_VERSION_PRE_RELEASE_NUM 2")
    r = _run(root, "--phase", "beta", "-v")
    assert r.returncode == 0, r.stdout + r.stderr
    text = (root / "include/my_tool/version.h").read_bytes().decode("latin-1")
    assert '_VERSION_PHASE "beta"' in text and '_VERSION_STRING "0.1.0-beta"' in text
    assert '_PROJECT_PHASE "alpha"' in text                      # never written by the tool
    assert "PEP 440: 0.1.0b1" in r.stdout                        # the counter feeds the PEP 440 form


def test_a_pre_num_that_cannot_land_is_said_not_swallowed(tmp_path):
    """CONSEQUENCE: 8 (safety) -- a flag either lands or is reported: on a header
    without the define, a plain VERSION file, or a _version.py without the line,
    --pre-num used to exit 0 silently. The file is still untouched; the warning
    names the kind's own fix."""
    cases = [
        (HEADER_CFG, "include/my_tool/version.h", HEADER, "add `#define <PREFIX>_VERSION_PRE_RELEASE_NUM 1`"),
        (PLAIN, "VERSION", "0.3.6\n", "one-line VERSION file holds no pre-release number"),
        ('version-source = "mypkg/_version.py"\n', "mypkg/_version.py",
         'MAJOR = 0\nMINOR = 3\nPATCH = 1\nPHASE = ""\n__version__ = "0.3.1"\n', "add a line `PRE_RELEASE_NUM = 1`"),
    ]
    for i, (cfg, rel, content, hint) in enumerate(cases):
        root = _project(tmp_path / str(i), cfg, {rel: content})
        before = (root / rel).read_bytes()
        r = _run(root, "--pre-num", "2", "--no-git-ver")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Warning: --pre-num 2 not stored" in r.stderr and hint in r.stderr, (rel, r.stderr)
        assert (root / rel).read_bytes() == before, rel


# --- the plain VERSION file ---------------------------------------------------

def test_a_plain_version_file_is_bumped_and_checked_with_no_stamp(tmp_path):
    """CONSEQUENCE: 8 (behaviour) -- AC4: repokit-common's own shape. A bump
    rewrites x.y.z, --check passes afterwards, and nothing is said about a
    __version__ string, because the file has none."""
    root = _project(tmp_path, PLAIN, {"VERSION": "0.3.6\n"})
    r = _run(root, "--bump", "patch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "VERSION").read_bytes() == b"0.3.7\n"
    assert "__version__" not in r.stdout
    check = _run(root, "--check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_a_plain_file_keeps_its_bom_and_line_ending_and_carries_a_phase(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- the bytes around the version are kept;
    x.y.z-phase reads and writes."""
    root = _project(tmp_path, PLAIN, {"VERSION": b"\xef\xbb\xbf0.3.6-alpha\r\n"})
    r = _run(root, "--bump", "minor")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "VERSION").read_bytes() == b"\xef\xbb\xbf0.4.0-alpha\r\n"


def test_a_python_source_still_gets_its_stamp(tmp_path):
    """CONSEQUENCE: 8 (safety) -- Python behaviour kept: the .py kind keeps
    writing __version__ with git metadata, exactly as before the other kinds
    existed."""
    cfg = 'version-source = "mypkg/_version.py"\n'
    root = _project(tmp_path, cfg, {"mypkg/_version.py": 'MAJOR = 0\nMINOR = 3\nPATCH = 1\nPHASE = ""\n__version__ = "0.3.1"\n'})
    r = _run(root, "--bump", "patch")
    assert r.returncode == 0, r.stdout + r.stderr
    text = (root / "mypkg/_version.py").read_text(encoding="utf-8")
    assert "PATCH = 2" in text and '__version__ = "0.3.2_main_' in text


# --- versioning = "off" -------------------------------------------------------

def test_versioning_off_does_nothing_and_exits_0(tmp_path):
    """CONSEQUENCE: 8 (behaviour) -- a project with no version source sets
    versioning = "off": --check passes, --auto is silent, nothing is looked for
    (git-repokit's own per-commit warning goes away with this)."""
    root = _project(tmp_path, 'versioning = "off"\n', {"README.md": "x\n"})
    auto = _run(root, "--auto")
    assert auto.returncode == 0 and auto.stdout.strip() == "" and auto.stderr.strip() == ""
    check = _run(root, "--check")
    assert check.returncode == 0 and "versioning is off" in check.stdout


# --- the compare link for a new version (A6) ---------------------------------

def test_a_new_version_with_a_heading_gets_its_compare_link(tmp_path):
    """CONSEQUENCE: 7 (behaviour) -- AC5: a heading ## [0.3.7] with no link
    gets [0.3.7]: .../compare/v0.3.6...v0.3.7 right after [Unreleased], whose
    own link moves on to v0.3.7...HEAD; the older links are untouched."""
    root = _project(tmp_path, PLAIN, {"VERSION": "0.3.7\n", "CHANGELOG.md": CHANGELOG})
    r = _run(root)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.endswith(
        "[Unreleased]: https://github.com/acme/tool/compare/v0.3.7...HEAD\n"
        "[0.3.7]: https://github.com/acme/tool/compare/v0.3.6...v0.3.7\n"
        "[0.3.6]: https://github.com/acme/tool/compare/v0.3.5...v0.3.6\n")
    assert _run(root).returncode == 0
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == text   # idempotent


def test_no_link_is_added_for_a_version_without_a_heading(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- a bump before the entry is written adds
    no dangling link; the missing heading is reported as before."""
    root = _project(tmp_path, PLAIN, {"VERSION": "0.3.6\n", "CHANGELOG.md": CHANGELOG.replace("## [0.3.7] - 2026-10-09\n\n### Added\n- a thing\n\n", "")})
    r = _run(root, "--bump", "patch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no ## [0.3.7] header" in r.stdout
    assert "[0.3.7]:" not in (root / "CHANGELOG.md").read_text(encoding="utf-8")
