"""Tests for sync-versions.py, centred on _load_config()'s parser fallback.

The contract these exist for: when ``pyproject.toml`` IS found but no TOML
parser can be imported -- no stdlib ``tomllib`` (Python 3.11+) and no ``tomli``
package -- ``_load_config()`` returns the placeholder defaults. Returning the
defaults is right; doing it in silence is not. The user's next symptom is
``Cannot find $PACKAGE_NAME/_version.py. Run from project root.`` from
``find_project_root()``, which names the wrong cause entirely: the version
source is missing only because the config that would have renamed it was never
read. One warning line at the moment of the failed import is what connects the
two.

Two arrangement notes that shape every test here:

* ``_load_config()`` walks up from ``Path(__file__).resolve().parent`` of the
  *script*, not from the working directory, so ``chdir`` cannot steer it.
  Pointing the loaded module's ``__file__`` at a temp tree is what does.
* the parser is chosen by ``import`` at call time, so a ``None`` entry in
  ``sys.modules`` (which makes ``import X`` raise ``ImportError``) reproduces a
  parser-less environment on any Python version, including this 3.12 one.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "sync-versions.py"


def _load():
    spec = importlib.util.spec_from_file_location("sync_versions", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SV = _load()

# The placeholder tuple _load_config() falls back to, spelled out so a silent
# change to any default shows up here as well.
DEFAULTS = (
    "$PACKAGE_NAME/_version.py",
    "CHANGELOG.md",
    "https://github.com/$GITHUB_ORG/$PROJECT_NAME",
    "v",
    "pep440",
)

CONFIGURED = """\
[tool.repokit-common]
version-source = "mypkg/_version.py"
changelog = "CHANGELOG.md"
repo-url = "https://github.com/acme/mypkg"
tag-prefix = "v"
tag-format = "human"
"""


def _point_at(monkeypatch, script_path):
    """Make _load_config() walk up from ``script_path`` instead of the repo."""
    monkeypatch.setattr(SV, "__file__", str(script_path))


@pytest.fixture
def pyproject(tmp_path, monkeypatch):
    """A temp project whose pyproject.toml the walk-up will find.

    Returns the (not yet written) pyproject.toml path; each test writes the
    body it needs. The script sits one level down, so the search hits this
    pyproject.toml on its second step and never escapes tmp_path.
    """
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    _point_at(monkeypatch, root / "scripts" / "sync-versions.py")
    return root / "pyproject.toml"


@pytest.fixture
def no_pyproject(tmp_path, monkeypatch):
    """A temp tree deep enough that all five walk-up steps stay inside it."""
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    _point_at(monkeypatch, deep / "sync-versions.py")
    return deep


@pytest.fixture
def no_parser(monkeypatch):
    """Neither tomllib nor tomli importable, whatever the real Python has."""
    monkeypatch.setitem(sys.modules, "tomllib", None)
    monkeypatch.setitem(sys.modules, "tomli", None)


# --- the bug: the unreadable pyproject.toml must be announced --------------

def test_missing_parser_is_reported_to_stderr(pyproject, no_parser, capsys):
    """ANCHOR. Silence here is the defect; the file must be named on stderr."""
    pyproject.write_text(CONFIGURED, encoding="utf-8")

    SV._load_config()

    err = capsys.readouterr().err
    assert err.strip(), "no warning at all: the failed parser import was silent"
    assert "pyproject.toml" in err


def test_missing_parser_warning_names_the_pyproject_path(pyproject, no_parser, capsys):
    """ANCHOR. 'a pyproject somewhere' is not actionable -- give the path found."""
    pyproject.write_text(CONFIGURED, encoding="utf-8")

    SV._load_config()

    err = capsys.readouterr().err
    assert str(pyproject) in err, f"path not in warning: {err!r}"


def test_missing_parser_warning_names_both_remedies(pyproject, no_parser, capsys):
    """ANCHOR. The two ways out are Python 3.11+ and the tomli package."""
    pyproject.write_text(CONFIGURED, encoding="utf-8")

    SV._load_config()

    err = capsys.readouterr().err
    assert "3.11" in err, f"Python 3.11+ not offered: {err!r}"
    assert "tomli" in err, f"the tomli package not offered: {err!r}"


def test_missing_parser_warning_is_one_line(pyproject, no_parser, capsys):
    """ANCHOR. One line, per the contract -- a paragraph on stderr is noise."""
    pyproject.write_text(CONFIGURED, encoding="utf-8")

    SV._load_config()

    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one warning line, got {lines!r}"


def test_missing_parser_still_returns_the_placeholder_defaults(pyproject, no_parser):
    """GUARD. Warning instead of raising: the return value must not change."""
    pyproject.write_text(CONFIGURED, encoding="utf-8")

    assert SV._load_config() == DEFAULTS


def test_default_version_source_still_drives_the_project_root_error(monkeypatch):
    """GUARD. The downstream message stays as it is -- the warning explains it,
    it does not replace it."""
    monkeypatch.setattr(SV, "VERSION_SOURCE", DEFAULTS[0])

    def _no_git(*a, **kw):
        raise FileNotFoundError("git not on PATH")

    # Stubbed so the test cannot reach a real repository: the assertion is
    # about the message, and no git process is needed to produce it.
    monkeypatch.setattr(SV.subprocess, "run", _no_git)

    with pytest.raises(FileNotFoundError) as exc:
        SV.find_project_root()

    assert "Cannot find $PACKAGE_NAME/_version.py" in str(exc.value)


# --- what must not change --------------------------------------------------

def test_parser_available_reads_the_config_and_says_nothing(pyproject, capsys):
    """GUARD. The working path: parsed values returned, stderr untouched."""
    pyproject.write_text(CONFIGURED, encoding="utf-8")

    cfg = SV._load_config()

    assert cfg == (
        "mypkg/_version.py",
        "CHANGELOG.md",
        "https://github.com/acme/mypkg",
        "v",
        "human",
    )
    assert capsys.readouterr().err == ""


def test_no_pyproject_anywhere_warns_about_nothing(no_pyproject, no_parser, capsys):
    """GUARD. No pyproject means nothing went unread -- a warning here would
    fire on every project that simply has no config."""
    cfg = SV._load_config()

    assert cfg == DEFAULTS
    assert capsys.readouterr().err == ""


def test_pyproject_without_the_table_is_silent(pyproject, capsys):
    """GUARD. A readable pyproject with no [tool.repokit-common] is a normal
    state, not a failure."""
    pyproject.write_text('[project]\nname = "mypkg"\n', encoding="utf-8")

    cfg = SV._load_config()

    assert cfg == DEFAULTS
    assert capsys.readouterr().err == ""


def test_unknown_tag_format_warning_still_fires(pyproject, capsys):
    """GUARD. The other warning in this function must keep working."""
    pyproject.write_text(
        '[tool.repokit-common]\ntag-format = "banana"\n', encoding="utf-8")

    cfg = SV._load_config()

    err = capsys.readouterr().err
    assert "banana" in err
    assert cfg[4] == "pep440", "unknown tag-format must fall back to pep440"
