"""Tests for sync-versions.py's extra targets ([[tool.repokit-common.extra-targets]]).

Two layers: the target logic on temp files (sync_extra_target and its
helpers), then the real script run end to end in a throwaway git project, so
--bump, --check, --auto staging and the exit codes are exercised as a hook
would see them. Ordered by consequence score, highest first, within each layer.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "sync-versions.py"
_spec = importlib.util.spec_from_file_location("sync_versions_et", TOOL)
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)

STABLE = {"major": 0, "minor": 3, "patch": 2, "phase": None,
          "pre_release_num": 1, "project_phase": None}
ALPHA = dict(STABLE, phase="alpha")

PLUGIN = '{\n  "name": "demo",\n  "version": "0.3.1",\n  "description": "x"\n}\n'
MARKET = ('{\n  "name": "cat",\n  "version": "0.3.1",\n  "plugins": [\n'
          '    {"name": "demo", "version": "0.3.1", "source": "./"}\n  ]\n}\n')


def _target(tmp_path, text, name="plugin.json", raw=None):
    f = tmp_path / name
    f.write_bytes(raw if raw is not None else text.encode("utf-8"))
    return f


def _sync(tmp_path, spec, components=STABLE, **kw):
    return SV.sync_extra_target(spec, components, tmp_path, **kw)


# --- target logic --------------------------------------------------------

def test_update_changes_only_the_version_string(tmp_path):
    """CONSEQUENCE: 9 (safety) -- the anchor: the field gets the new
    version and not one other byte of the file changes."""
    f = _target(tmp_path, PLUGIN)
    assert _sync(tmp_path, {"path": "plugin.json"}) == "updated"
    assert f.read_text(encoding="utf-8") == PLUGIN.replace("0.3.1", "0.3.2")


def test_a_refused_target_is_left_byte_identical(tmp_path):
    """CONSEQUENCE: 9 (safety) -- a target that cannot be handled safely
    is never half-written: match="one" on a file with two fields refuses and
    leaves every byte in place."""
    f = _target(tmp_path, MARKET, "marketplace.json")
    before = f.read_bytes()
    with pytest.raises(SV.TargetError, match="2 'version' fields"):
        _sync(tmp_path, {"path": "marketplace.json"})
    assert f.read_bytes() == before


def test_check_mode_reports_stale_and_writes_nothing(tmp_path):
    """CONSEQUENCE: 8 (safety) -- --check never writes; a stale target is
    reported as stale."""
    f = _target(tmp_path, PLUGIN)
    before = f.read_bytes()
    assert _sync(tmp_path, {"path": "plugin.json"}, check=True) == "stale"
    assert f.read_bytes() == before


@pytest.mark.parametrize("text, message", [
    ('{"name": "x"}\n', "no 'version' field"),
    ('{"version": 3}\n', "not a string"),
    ('{"version": "1", "version": "2"}\n', "twice in one object"),
    ('{"version": "1",}\n', "invalid JSON"),
    # The parse cross-check: "version" is "version", a real field the
    # in-place edit cannot reach, so the file is refused as unsafe to edit,
    # not reported as having no version or edited around.
    pytest.param('{\n  "\\u0076ersion": "0.3.1"\n}\n', "cannot locate", id="escaped-key"),
])
def test_unsafe_files_are_refused_untouched(tmp_path, text, message):
    """CONSEQUENCE: 8 (safety) -- missing field, non-string value, duplicate
    key, invalid JSON, or a field the edit cannot see: refused with a reason,
    file unchanged."""
    f = _target(tmp_path, text)
    with pytest.raises(SV.TargetError, match=message):
        _sync(tmp_path, {"path": "plugin.json"})
    assert f.read_text(encoding="utf-8") == text


def test_a_path_outside_the_project_is_refused(tmp_path):
    """CONSEQUENCE: 8 (safety) -- a target may not reach outside the root."""
    (tmp_path / "proj").mkdir()
    _target(tmp_path, PLUGIN, "outside.json")
    with pytest.raises(SV.TargetError, match="outside the project root"):
        SV.sync_extra_target({"path": "../outside.json"}, STABLE, tmp_path / "proj")


def test_dry_run_reports_the_update_and_writes_nothing(tmp_path):
    """CONSEQUENCE: 7 (safety) -- --dry-run says it would update and leaves
    the file alone."""
    f = _target(tmp_path, PLUGIN)
    before = f.read_bytes()
    assert _sync(tmp_path, {"path": "plugin.json"}, dry_run=True) == "updated"
    assert f.read_bytes() == before


def test_a_version_text_inside_another_string_is_not_touched(tmp_path):
    """CONSEQUENCE: 7 (safety) -- an escaped "version" inside some other
    string value is not a field and stays as written."""
    text = ('{\n  "note": "set \\"version\\": \\"9.9.9\\" by hand",\n'
            '  "version": "0.3.1"\n}\n')
    f = _target(tmp_path, text)
    _sync(tmp_path, {"path": "plugin.json"})
    out = f.read_text(encoding="utf-8")
    assert '\\"9.9.9\\"' in out and '"version": "0.3.2"' in out


def test_crlf_line_endings_survive_the_edit(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- a CRLF file stays CRLF, so a bump is a
    one-line diff on Windows checkouts too."""
    crlf = PLUGIN.replace("\n", "\r\n")
    f = _target(tmp_path, None, raw=crlf.encode("utf-8"))
    _sync(tmp_path, {"path": "plugin.json"})
    assert f.read_bytes() == crlf.replace("0.3.1", "0.3.2").encode("utf-8")


def test_match_all_updates_every_field(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- match="all" reaches the nested copy a
    marketplace.json carries, so none is left stale."""
    f = _target(tmp_path, MARKET, "marketplace.json")
    _sync(tmp_path, {"path": "marketplace.json", "match": "all"})
    assert f.read_text(encoding="utf-8") == MARKET.replace("0.3.1", "0.3.2")


def test_format_human_carries_the_phase_and_base_drops_it(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- "human" writes 0.3.2-alpha; "base"
    writes 0.3.2, for browser manifests that reject a phase suffix."""
    f = _target(tmp_path, PLUGIN)
    _sync(tmp_path, {"path": "plugin.json"}, ALPHA)
    assert '"0.3.2-alpha"' in f.read_text(encoding="utf-8")
    g = _target(tmp_path, PLUGIN, "manifest.json")
    _sync(tmp_path, {"path": "manifest.json", "format": "base"}, ALPHA)
    assert '"0.3.2"' in g.read_text(encoding="utf-8")


@pytest.mark.parametrize("spec, message", [
    ({"path": "plugin.json", "feild": "version"}, "unknown key"),
    ({"path": "plugin.json", "match": "every"}, "match ="),
    ({"path": "plugin.json", "type": "toml"}, "type ="),
    ({"path": "plugin.json", "format": "pep440"}, "format ="),
    ({"type": "json"}, "missing 'path'"),
    ("plugin.json", "must be a table"),
])
def test_bad_entries_are_named_not_guessed(tmp_path, spec, message):
    """CONSEQUENCE: 6 (behaviour) -- a typo or a wrong value in the config is
    an error naming the problem, never a silent no-op that leaves the target
    stale."""
    _target(tmp_path, PLUGIN)
    with pytest.raises(SV.TargetError, match=message):
        _sync(tmp_path, spec)


def test_a_utf8_bom_survives_the_edit(tmp_path):
    """CONSEQUENCE: 5 (behaviour) -- a leading BOM is kept, not dropped or
    doubled."""
    bom = b"\xef\xbb\xbf"
    f = _target(tmp_path, None, raw=bom + PLUGIN.encode("utf-8"))
    _sync(tmp_path, {"path": "plugin.json"})
    assert f.read_bytes() == bom + PLUGIN.replace("0.3.1", "0.3.2").encode("utf-8")


def test_a_missing_file_is_named(tmp_path):
    """CONSEQUENCE: 5 (behaviour) -- a declared target that does not exist
    says so instead of being skipped."""
    with pytest.raises(SV.TargetError, match="file not found"):
        _sync(tmp_path, {"path": "nope.json"})


def test_match_first_updates_only_the_first_field(tmp_path):
    """CONSEQUENCE: 4 (behaviour) -- match="first" leaves later fields alone."""
    f = _target(tmp_path, MARKET, "marketplace.json")
    _sync(tmp_path, {"path": "marketplace.json", "match": "first"})
    text = f.read_text(encoding="utf-8")
    assert text.count('"0.3.2"') == 1 and text.count('"0.3.1"') == 1


def test_an_in_sync_target_is_not_rewritten(tmp_path):
    """CONSEQUENCE: 4 (behaviour) -- idempotence: a target already at the
    version reports ok and is not written (its mtime does not move)."""
    f = _target(tmp_path, PLUGIN.replace("0.3.1", "0.3.2"))
    mtime = f.stat().st_mtime_ns
    assert _sync(tmp_path, {"path": "plugin.json"}) == "ok"
    assert f.stat().st_mtime_ns == mtime


# --- end to end ----------------------------------------------------------

VERSION_PY = 'MAJOR = 0\nMINOR = 3\nPATCH = 1\nPHASE = ""\n__version__ = "0.3.1"\n'


def _project(tmp_path, targets_toml):
    """A throwaway git project with the script vendored at scripts/."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    (root / "mypkg").mkdir()
    shutil.copy(TOOL, root / "scripts" / "sync-versions.py")
    shutil.copy(REPO / "repokit_config.py", root / "scripts" / "repokit_config.py")
    (root / "pyproject.toml").write_text(
        '[tool.repokit-common]\nversion-source = "mypkg/_version.py"\n'
        + targets_toml, encoding="utf-8")
    (root / "mypkg" / "_version.py").write_text(VERSION_PY, encoding="utf-8")
    (root / "plugin.json").write_text(PLUGIN, encoding="utf-8")
    (root / "marketplace.json").write_text(MARKET, encoding="utf-8")
    # As real projects do: the script's own import writes scripts/__pycache__.
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"],
                ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)
    return root


def _run(root, *args):
    return subprocess.run(
        [sys.executable, "scripts/sync-versions.py", *args],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)


PLUGIN_TARGET = '\n[[tool.repokit-common.extra-targets]]\npath = "plugin.json"\n'
BOTH_TARGETS = PLUGIN_TARGET + (
    '\n[[tool.repokit-common.extra-targets]]\npath = "marketplace.json"\n'
    'match = "all"\n')


def test_check_exits_1_while_a_target_is_stale_and_0_once_synced(tmp_path):
    """CONSEQUENCE: 9 (safety) -- the pre-push / CI gate: --check fails on
    a stale target and passes after a sync."""
    root = _project(tmp_path, PLUGIN_TARGET)
    (root / "mypkg" / "_version.py").write_text(
        VERSION_PY.replace("PATCH = 1", "PATCH = 2"), encoding="utf-8")
    stale = _run(root, "--check", "--no-git-ver")
    assert stale.returncode == 1 and "plugin.json" in stale.stdout
    assert _run(root, "--no-git-ver").returncode == 0
    assert _run(root, "--check", "--no-git-ver").returncode == 0


def test_a_bad_target_is_loud_under_auto_and_the_others_still_sync(tmp_path):
    """CONSEQUENCE: 7 (safety) -- a broken target is reported on stderr with
    exit 1 even in quiet hook mode, and the good targets are still updated."""
    root = _project(tmp_path, BOTH_TARGETS.replace('match = "all"\n', ""))
    (root / "mypkg" / "_version.py").write_text(
        VERSION_PY.replace("PATCH = 1", "PATCH = 2"), encoding="utf-8")
    r = _run(root, "--auto", "--no-git-ver")
    assert r.returncode == 1
    assert "marketplace.json" in r.stderr and "2 'version' fields" in r.stderr
    assert '"0.3.2"' in (root / "plugin.json").read_text(encoding="utf-8")


def test_without_extra_targets_nothing_about_them_is_said(tmp_path):
    """CONSEQUENCE: 7 (safety) -- opt-in: a project that declares no
    targets sees no target output and its JSON files are not touched."""
    root = _project(tmp_path, "")
    before = (root / "plugin.json").read_bytes()
    r = _run(root, "--bump", "patch", "--no-git-ver")
    assert r.returncode == 0
    assert "plugin.json" not in r.stdout + r.stderr
    assert (root / "plugin.json").read_bytes() == before


def test_bump_carries_the_new_version_into_the_targets(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- --bump patch moves version.py and every
    declared target to the same new version in one run."""
    root = _project(tmp_path, BOTH_TARGETS)
    r = _run(root, "--bump", "patch", "--no-git-ver")
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"version": "0.3.2"' in (root / "plugin.json").read_text(encoding="utf-8")
    assert (root / "marketplace.json").read_text(encoding="utf-8").count('"0.3.2"') == 2


def test_auto_mode_stages_the_updated_target(tmp_path):
    """CONSEQUENCE: 6 (behaviour) -- in the pre-commit hook (--auto) an
    updated target is staged with the version file."""
    root = _project(tmp_path, PLUGIN_TARGET)
    (root / "mypkg" / "_version.py").write_text(
        VERSION_PY.replace("PATCH = 1", "PATCH = 2"), encoding="utf-8")
    r = _run(root, "--auto", "--no-git-ver")
    assert r.returncode == 0, r.stdout + r.stderr
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                            cwd=root, capture_output=True, text=True).stdout
    assert "plugin.json" in staged.split()


def test_a_root_version_py_counts_as_a_version_file_for_the_date(tmp_path):
    """CONSEQUENCE: 5 (behaviour) -- a version-only change keeps the last
    commit's date in __version__ whatever the version source is called: a
    root version.py (not *_version.py) is a version file, so editing only it
    does not move the date to today."""
    import os
    root = _project(tmp_path, "")
    (root / "mypkg" / "_version.py").rename(root / "version.py")
    py = root / "pyproject.toml"
    py.write_text(py.read_text(encoding="utf-8").replace(
        "mypkg/_version.py", "version.py"), encoding="utf-8")
    dated = {**os.environ, "GIT_COMMITTER_DATE": "2020-01-02T03:04:05",
             "GIT_AUTHOR_DATE": "2020-01-02T03:04:05"}
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "root version.py"], cwd=root,
                   check=True, capture_output=True, env=dated)
    (root / "version.py").write_text(
        VERSION_PY.replace("PATCH = 1", "PATCH = 2"), encoding="utf-8")
    r = _run(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "-20200102-" in (root / "version.py").read_text(encoding="utf-8")


def test_extra_targets_must_be_an_array_of_tables(tmp_path):
    """CONSEQUENCE: 5 (behaviour) -- a single [tool.repokit-common.extra-targets]
    table (one bracket pair) is named as the mistake it is, not ignored."""
    root = _project(tmp_path, '\n[tool.repokit-common.extra-targets]\npath = "plugin.json"\n')
    r = _run(root, "--no-git-ver")
    assert r.returncode == 1 and "array of tables" in r.stderr
