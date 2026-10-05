"""Tests for the fallback config file, .repokit-common.toml: the header rule.

A project that is not a Python package keeps its settings in
.repokit-common.toml, under the same [tool.repokit-common] header a
pyproject.toml uses, so the file is ordinary TOML that says what its keys are
for and can hold other tables too. Before 0.3.5 a file written without the
header was found and then read as empty, with no warning: no version source,
no private patterns, no extra targets (found by claude-bookmarks, the first
non-Python consumer). Now a key outside any table stops the tools with a
reason.

Each test builds a throwaway project under ``tmp_path``; git runs only there,
with signing off. Ordered by consequence score, highest first.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("repokit_config", REPO / "repokit_config.py")
RC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RC)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

SETTINGS = 'version-source = "version.py"\nprivate-patterns = ["secret/"]\n'
VERSION_PY = 'MAJOR = 0\nMINOR = 1\nPATCH = 2\nPHASE = ""\n__version__ = "0.1.2"\n'


def _project(tmp_path, config_text):
    """A git project with repokit-common vendored at scripts/repokit-common/."""
    root = tmp_path / "proj"
    vend = root / "scripts" / "repokit-common"
    vend.mkdir(parents=True)
    for name in ("sync-versions.py", "repokit_config.py"):
        shutil.copy(REPO / name, vend / name)
    (root / ".repokit-common.toml").write_text(config_text, encoding="utf-8")
    (root / "version.py").write_text(VERSION_PY, encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"],
                ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)
    return root, vend


def _sync(root, *args):
    return subprocess.run(
        [sys.executable, "scripts/repokit-common/sync-versions.py", *args],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)


@pytest.mark.parametrize("text", [
    SETTINGS,                                                   # no header at all
    'tag-format = "human"\n\n[tool.repokit-common]\n' + SETTINGS,  # one loose key beside it
])
def test_a_key_outside_the_header_stops_both_tools_with_a_reason(tmp_path, capsys, text):
    """CONSEQUENCE: 9 (safety) -- the file is never silently read as empty or
    partial: the hooks' reader and sync-versions.py both exit 2 and name the
    loose key and the header it belongs under."""
    root, vend = _project(tmp_path, text)
    assert RC.main(["--shell", "version-source", "--start", str(vend)]) == 2
    err = capsys.readouterr().err
    assert "[tool.repokit-common]" in err
    r = _sync(root, "--check", "--no-git-ver")
    assert r.returncode == 2 and "[tool.repokit-common]" in r.stderr
    loose = "tag-format" if text.startswith("tag-format") else "private-patterns, version-source"
    assert loose in err and loose in r.stderr


def test_the_header_form_works_beside_other_tables(tmp_path, capsys):
    """CONSEQUENCE: 8 (behaviour) -- the documented form reaches both tools,
    other tables in the file are left alone, and in a pyproject.toml only the
    table counts, as before."""
    root, vend = _project(
        tmp_path, '[tool.other-tool]\nmode = "x"\n\n[tool.repokit-common]\n' + SETTINGS)
    assert _sync(root, "--check", "--no-git-ver").returncode == 0
    assert RC.main(["--shell", "version-source", "private-patterns", "--start", str(vend)]) == 0
    out = capsys.readouterr().out
    assert "REPOKIT_VERSION_SOURCE=version.py" in out and "secret/" in out
    data = {"project": {"name": "p"}, "tool": {"repokit-common": {"changelog": "C.md"}}}
    assert RC.table_of(data, tmp_path / "pyproject.toml") == {"changelog": "C.md"}
