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
    """CONSEQUENCE: 4 (behaviour) -- match="first" updates the first field (the
    marketplace's own version) and leaves the later one (the plugin entry's)
    alone. Compared as whole text: a count of each version cannot tell the
    first field from the last (the 0.4.3 sweep's M9 survived it)."""
    f = _target(tmp_path, MARKET, "marketplace.json")
    _sync(tmp_path, {"path": "marketplace.json", "match": "first"})
    assert f.read_text(encoding="utf-8") == MARKET.replace('"0.3.1"', '"0.3.2"', 1)


def test_an_in_sync_target_is_not_rewritten(tmp_path):
    """CONSEQUENCE: 4 (behaviour) -- idempotence: a target already at the
    version reports ok and is not written (its mtime does not move)."""
    f = _target(tmp_path, PLUGIN.replace("0.3.1", "0.3.2"))
    mtime = f.stat().st_mtime_ns
    assert _sync(tmp_path, {"path": "plugin.json"}) == "ok"
    assert f.stat().st_mtime_ns == mtime


# --- pattern targets -----------------------------------------------------

# Shaped like the real CK3 descriptors M3 rewrote (2026-10-30, 62 of 62
# byte-exact): version="x" with no spaces, and a supported_version line that
# must never be taken for it.
DESCRIPTOR = ('version="0.3.1"\ntags={\n\t"Utilities"\n}\nname="Demo"\n'
              'supported_version="1.20.*"\nremote_file_id="2216746850"\n')
DESC_PATTERN = '^version="([^"]*)"\\r?$'
DESC_SPEC = {"path": "descriptor.mod", "pattern": DESC_PATTERN, "format": "base"}


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"], ids=["no-bom", "bom"])
@pytest.mark.parametrize("eol", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_pattern_rewrites_only_the_version_group_byte_for_byte(tmp_path, bom, eol):
    """CONSEQUENCE: 9 (safety) -- the anchor: a descriptor.mod's version line
    gets the new version and not one other byte changes -- BOM, line endings
    and supported_version included."""
    text = DESCRIPTOR.replace("\n", eol)
    f = _target(tmp_path, None, "descriptor.mod", raw=bom + text.encode("utf-8"))
    assert _sync(tmp_path, DESC_SPEC) == "updated"
    expected = text.replace('version="0.3.1"', 'version="0.3.2"', 1)
    assert f.read_bytes() == bom + expected.encode("utf-8")
    assert 'supported_version="1.20.*"' in f.read_text(encoding="utf-8-sig")


def test_pattern_with_no_matching_line_is_absent_not_an_error(tmp_path):
    """CONSEQUENCE: 7 (behaviour) -- a descriptor with no version line (3 of
    65 real ones) is reported absent and left byte-identical, in check mode too."""
    text = DESCRIPTOR.replace('version="0.3.1"\n', "")
    f = _target(tmp_path, text, "descriptor.mod")
    assert _sync(tmp_path, DESC_SPEC) == "absent"
    assert _sync(tmp_path, DESC_SPEC, check=True) == "absent"
    assert f.read_text(encoding="utf-8") == text


def test_pattern_matching_two_lines_is_refused_unless_match_all(tmp_path):
    """CONSEQUENCE: 8 (safety) -- a pattern that matches more than one line is
    refused untouched; match = "all" updates every one, "first" the first."""
    text = DESCRIPTOR + 'version="0.3.1"\n'
    f = _target(tmp_path, text, "descriptor.mod")
    with pytest.raises(SV.TargetError, match='2 lines match the pattern; set match = "all"'):
        _sync(tmp_path, DESC_SPEC)
    assert f.read_text(encoding="utf-8") == text
    assert _sync(tmp_path, dict(DESC_SPEC, match="first")) == "updated"
    after_first = f.read_text(encoding="utf-8")
    assert after_first.startswith('version="0.3.2"\n')            # the first line ...
    assert after_first.endswith('version="0.3.1"\n')              # ... and not the last
    assert _sync(tmp_path, dict(DESC_SPEC, match="all")) == "updated"
    assert f.read_text(encoding="utf-8").count('version="0.3.2"') == 2


def test_pattern_match_all_with_a_longer_version_rewrites_every_line_exactly(tmp_path):
    """CONSEQUENCE: 8 (safety) -- when the new version is longer than the old
    (0.3.1 -> 0.3.2-alpha), every matched line still gets exactly the new text:
    an edit at one line must not shift where the next one lands."""
    text = DESCRIPTOR + 'version="0.3.1"\n'
    f = _target(tmp_path, text, "descriptor.mod")
    spec = {"path": "descriptor.mod", "pattern": DESC_PATTERN, "match": "all"}
    assert _sync(tmp_path, spec, components=ALPHA) == "updated"
    human = SV.format_human_version(ALPHA)
    assert f.read_text(encoding="utf-8") == text.replace('version="0.3.1"', f'version="{human}"')


def test_pattern_check_mode_and_format(tmp_path):
    """CONSEQUENCE: 7 (behaviour) -- --check reports stale and writes nothing;
    format = "human" (the default) carries the phase, as for JSON targets; an
    in-sync file reports ok."""
    f = _target(tmp_path, DESCRIPTOR, "descriptor.mod")
    spec = {"path": "descriptor.mod", "pattern": DESC_PATTERN}
    assert _sync(tmp_path, spec, components=ALPHA, check=True) == "stale"
    assert f.read_text(encoding="utf-8") == DESCRIPTOR
    assert _sync(tmp_path, spec, components=ALPHA) == "updated"
    human = SV.format_human_version(ALPHA)
    assert human != "0.3.2" and f'version="{human}"' in f.read_text(encoding="utf-8")
    assert _sync(tmp_path, spec, components=ALPHA) == "ok"


@pytest.mark.parametrize("spec, message", [
    ({"path": "descriptor.mod", "pattern": '^version="[^"]*"$'}, "exactly one group"),
    ({"path": "descriptor.mod", "pattern": '^(version)="([^"]*)"$'}, "exactly one group"),
    ({"path": "descriptor.mod", "pattern": '^version="(['}, "not a valid regular expression"),
    ({"path": "descriptor.mod", "pattern": ""}, "non-empty 'pattern'"),
    ({"path": "descriptor.mod", "pattern": '^v="(.*)"$', "field": "version"}, "'field' is for json"),
    ({"path": "descriptor.mod", "pattern": '^v="(.*)"$', "type": "json"}, "'pattern' is for pattern"),
    ({"path": "descriptor.mod", "type": "pattern"}, "non-empty 'pattern'"),
])
def test_bad_pattern_entries_are_named_not_guessed(tmp_path, spec, message):
    """CONSEQUENCE: 6 (behaviour) -- a pattern with no group or two, an invalid
    one, a missing one, or one mixed with a JSON field is an error naming the
    problem, and the file is untouched."""
    f = _target(tmp_path, DESCRIPTOR, "descriptor.mod")
    with pytest.raises(SV.TargetError, match=message):
        _sync(tmp_path, spec)
    assert f.read_text(encoding="utf-8") == DESCRIPTOR


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


def test_bump_carries_the_version_into_a_descriptor_and_notes_one_without_a_line(tmp_path):
    """CONSEQUENCE: 8 (behaviour) -- end to end: --bump moves a pattern
    target with the version source; a second descriptor with no version line
    is noted as skipped and the run still exits 0; --check then passes."""
    targets = ("\n[[tool.repokit-common.extra-targets]]\npath = \"mod/descriptor.mod\"\n"
               "pattern = '^version=\"([^\"]*)\"\\r?$'\nformat = \"base\"\n"
               "\n[[tool.repokit-common.extra-targets]]\npath = \"other/descriptor.mod\"\n"
               "pattern = '^version=\"([^\"]*)\"\\r?$'\n")
    root = _project(tmp_path, targets)
    (root / "mod").mkdir()
    (root / "other").mkdir()
    (root / "mod" / "descriptor.mod").write_bytes(b"\xef\xbb\xbf" + DESCRIPTOR.encode("utf-8"))
    no_line = DESCRIPTOR.replace('version="0.3.1"\n', "")
    (root / "other" / "descriptor.mod").write_text(no_line, encoding="utf-8")
    r = _run(root, "--bump", "patch", "--no-git-ver")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "mod" / "descriptor.mod").read_bytes() == (
        b"\xef\xbb\xbf" + DESCRIPTOR.replace('version="0.3.1"', 'version="0.3.2"').encode("utf-8"))
    assert "other/descriptor.mod: no line matches the pattern (skipped)" in r.stdout
    assert (root / "other" / "descriptor.mod").read_text(encoding="utf-8") == no_line
    assert _run(root, "--check", "--no-git-ver").returncode == 0


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
