"""Red-green audit of slice G1's new tests (2026-10-09).

For each mutation: back the file up, revert ONE behaviour (never an API),
run only the tests that should notice, restore byte for byte (SHA-256
checked), and record the split. The full pytest output of every arm is
written to run-<stamp>.txt beside this script; the mutation table is the
report. Runs only inside this checkout; every test it runs works in tmp_path.
"""
import datetime
import hashlib
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
assert (ROOT / "sync-versions.py").is_file(), ROOT

M = [  # (name, file, old, new, pytest selector, tests expected RED)
    ("M1 vendored-skip off", "repokit_config.py",
     'return all((d / name).is_file() for name in ("repokit_config.py", "sync-versions.py", "VERSION"))',
     "return False",
     "tests/test_repokit_config.py -k 'vendored or submodule_copys or as_the_project'",
     ["vendored_copys_own", "submodule_copys_own"]),
    ("M2 detection off", "repokit_config.py",
     "    root = Path(root)\n    found = []\n    py = root",
     "    return []\n    root = Path(root)\n    found = []\n    py = root",
     "tests/test_repokit_config.py -k 'detected_from_root or setting_wins'",
     ["detected_from_root", "setting_wins"]),
    ("M3 setting ignored", "repokit_config.py",
     '    value = table.get("languages")\n    if value is None:',
     '    value = None\n    if value is None:',
     "tests/test_repokit_config.py::test_languages_setting_wins_detection_is_next_and_python_is_the_default tests/test_pre_push_hook.py::test_a_typescript_project_gets_its_own_checks_and_loses_the_python_warning",
     ["setting_wins", "typescript_project"]),
    ("M4 every source is python", "sync-versions.py",
     '    if p.suffix.lower() in _HEADER_SUFFIXES:\n        return "c-header"\n    return "plain"',
     '    if p.suffix.lower() in _HEADER_SUFFIXES:\n        return "python"\n    return "python"',
     "tests/test_sync_versions_sources.py",
     ["header_bump", "header_set", "plain_version_file", "plain_file_keeps"]),
    ("M5 header re-encoded as UTF-8", "sync-versions.py",
     "format_human_version(components).encode() + m.group(3), new, flags=re.M)\n    if new == data:\n        return False\n    if not dry_run:\n        file_path.write_bytes(new)",
     "format_human_version(components).encode() + m.group(3), new, flags=re.M)\n    if new == data:\n        return False\n    if not dry_run:\n        file_path.write_bytes(new.decode('latin-1').encode('utf-8'))",
     "tests/test_sync_versions_sources.py -k header_bump",
     ["header_bump"]),
    ("M6 versioning off ignored (tool)", "sync-versions.py",
     '    if str(VERSIONING).lower() == "off":',
     '    if False and str(VERSIONING).lower() == "off":',
     "tests/test_sync_versions_sources.py -k versioning_off",
     ["versioning_off"]),
    ("M7 versioning off ignored (pre-commit)", "hooks/pre-commit",
     'if [ "${REPOKIT_VERSIONING:-on}" = "off" ]; then\n    :\nelif',
     'if false; then\n    :\nelif',
     "tests/test_pre_commit_hook.py -k versioning_off",
     ["versioning_off"]),
    ("M8 A6 link never added", "sync-versions.py",
     "    if not link_match and check_changelog_header(root, human_ver):",
     "    if False and not link_match and check_changelog_header(root, human_ver):",
     "tests/test_sync_versions_sources.py -k 'compare_link or without_a_heading'",
     ["gets_its_compare_link"]),
    ("M9 stamp never recognised", "update-common.sh",
     "                [ -z \"$(git diff -U0 -- \"$1\" | grep '^[-+][^-+]' | grep -v '__version__')\" ]\n            }",
     "                [ -z \"$(git diff -U0 -- \"$1\" | grep '^[-+][^-+]' | grep -v '__version__')\" ]\n                return 1\n            }",
     "tests/test_update_common.py",
     ["only_the_stamp"]),
    ("M10 old prefix computation", "update-common.sh",
     'PREFIX="$(cd "$SCRIPT_DIR" && git rev-parse --show-prefix)"\nPREFIX="${PREFIX%/}"',
     'PREFIX="${SCRIPT_DIR#"$REPO_ROOT"/}"',
     "tests/test_update_common.py -k 'clean_tree or only_the_stamp'",
     ["clean_tree", "only_the_stamp"]),
    ("M12 header ignores PRE_RELEASE_NUM again", "sync-versions.py",
     '    pre_m = re.search(_DEFINE_NUM % b"PRE_RELEASE_NUM", data, re.M)',
     '    pre_m = None',
     "tests/test_sync_versions_sources.py -k round_trips",
     ["round_trips"]),
    ("M13 the --pre-num warning removed", "sync-versions.py",
     "        if args.pre_num is not None and not args.dry_run:",
     "        if False:",
     "tests/test_sync_versions_sources.py -k cannot_land",
     ["cannot_land"]),
    ("M11 python profile skips pdb", "hooks/pre-push",
     '            _rk_debug_check python "import pdb|pdb\\.set_trace\\(\\)" "pdb statements" --include="*.py"',
     '            :',
     "tests/test_pre_push_hook.py -k python_profile_runs_as_before",
     ["python_profile"]),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    stamp = datetime.datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
    log = Path(__file__).with_name(f"run-{stamp}.txt")
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    out = [f"redgreen G1 at {head} (tree dirty: slice uncommitted) -- {stamp}", f"python {sys.version.split()[0]}", ""]
    rows = []
    only = sys.argv[1:]   # optional: mutation name prefixes to run (e.g. M1 M2)
    for name, rel, old, new, selector, expect_red in M:
        if only and not any(name.startswith(o) for o in only):
            continue
        f = ROOT / rel
        orig = f.read_bytes()
        digest = sha(f)
        nl = "\r\n" if b"\r\n" in orig else "\n"   # files are CRLF or LF on disk under autocrlf
        text = orig.decode("utf-8").replace("\r\n", "\n")
        assert text.count(old) == 1, f"{name}: anchor not unique/found in {rel} ({text.count(old)})"
        f.write_bytes(text.replace(old, new).replace("\n", nl).encode("utf-8"))
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *shlex.split(selector)],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        finally:
            f.write_bytes(orig)
        assert sha(f) == digest, f"{name}: restore failed for {rel}"
        failed = [line.split("::")[-1].split(" ")[0] for line in r.stdout.splitlines() if line.startswith("FAILED")]
        summary = next((l for l in r.stdout.splitlines()[::-1] if "passed" in l or "failed" in l), r.stdout[-200:])
        red_ok = all(any(e in fl for fl in failed) for e in expect_red)
        rows.append((name, rel, summary.strip("= "), "RED as expected" if red_ok else "NOT RED -> check", failed))
        out += [f"=== {name} ({rel}) :: {selector}", r.stdout, r.stderr, ""]
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    out += ["=== tree check", "porcelain unchanged" if before == after else "PORCELAIN CHANGED\n" + before + "\n---\n" + after]
    log.write_text("\n".join(out), encoding="utf-8")
    for name, rel, summary, verdict, failed in rows:
        print(f"{name:40} {rel:20} {summary:40} {verdict}")
        for fl in failed:
            print(f"{'':40} red: {fl}")
    print("tree:", "unchanged" if before == after else "CHANGED")
    print("log:", log)


if __name__ == "__main__":
    main()
