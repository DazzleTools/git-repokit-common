"""Tests for write_version_components' PHASE line: a bump rewrites the value only.

Before this fix every write replaced the rest of the PHASE line with a fixed
comment reading `None, "alpha", ...`, overwriting the project's own comment
and calling the stable value None although PHASE is "" when stable (found
bumping claude-bookmarks to v0.1.1, 2026-10-04).
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sync_versions_pc", REPO / "sync-versions.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)

BASE = {"major": 0, "minor": 1, "patch": 1, "phase": None, "pre_release_num": 1}
OWN = '# Per-MINOR feature set: "" (stable), "alpha", "beta", "rc1", etc.'


def _write(tmp_path, phase_line, components=BASE):
    f = tmp_path / "version.py"
    f.write_text(f"MAJOR = 0\nMINOR = 1\nPATCH = 0\n{phase_line}\n", encoding="utf-8")
    SV.write_version_components(f, components)
    return f.read_text(encoding="utf-8").splitlines()[3]


def test_bump_keeps_the_projects_own_comment(tmp_path):
    """CONSEQUENCE: 8 -- the anchor: the comment survives a bump verbatim."""
    assert _write(tmp_path, f'PHASE = ""  {OWN}') == f'PHASE = ""  {OWN}'


def test_phase_change_rewrites_only_the_value(tmp_path):
    """CONSEQUENCE: 8 -- setting a phase changes the value, not the comment."""
    line = _write(tmp_path, f'PHASE = ""  {OWN}', dict(BASE, phase="alpha"))
    assert line == f'PHASE = "alpha"  {OWN}'


def test_a_line_without_a_comment_gains_none(tmp_path):
    """CONSEQUENCE: 6 -- no comment in, no comment out (nothing invented)."""
    assert _write(tmp_path, 'PHASE = "beta"') == 'PHASE = ""'


def test_none_and_single_quoted_values_are_rewritten(tmp_path):
    """CONSEQUENCE: 6 -- the forms read_version_components accepts all write cleanly."""
    assert _write(tmp_path, "PHASE = None  # old") == 'PHASE = ""  # old'
    assert _write(tmp_path, "PHASE = 'alpha'  # q") == 'PHASE = ""  # q'


def test_unrecognised_value_falls_back_with_an_accurate_comment(tmp_path):
    """CONSEQUENCE: 5 -- an odd value is still replaced, and the comment no
    longer calls the stable value None."""
    line = _write(tmp_path, "PHASE = alpha")
    assert line.startswith('PHASE = ""  #')
    assert "None" not in line and '"" (stable)' in line
