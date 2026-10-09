"""Who would hit the bash update-version.sh fallback? (read-only)

Input: the consumer roster probe's JSON (argv[1], with a "records" list).
For each live checkout (backups skipped), it finds the vendored repokit
copy from the record's layout, checks for sync-versions.py and
update-version.sh in it, reads the INSTALLED pre-commit hook, and decides
which version tool a commit would run there today:

  sync        -- the hook calls sync-versions.py (directly or via a stub)
  bash        -- the hook would run update-version.sh (no sync-versions.py
                 to find, or the hook calls update-version.sh itself)
  no-hook     -- no pre-commit hook installed: nothing runs
  other       -- a hook that mentions neither tool
  missing     -- the checkout path does not exist (reported, not dropped)

Known-answer cases are printed first: each must land in the expected class
or the census is not trusted.

Written for the 2026-10-06 measurement feeding the C/C++ template design
(two-layer model, language profiles).
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def git_hooks_dir(repo):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    p = Path(r.stdout.strip())
    return p if p.is_absolute() else (repo / p)


def vendored_dir(repo, layout):
    # layout looks like "subtree:scripts/repokit-common" or "template:scripts"
    rel = layout.split(":", 1)[1] if layout and ":" in layout else "scripts"
    return repo / rel


def classify(repo, layout):
    if not repo.is_dir():
        return "missing", {}
    vdir = vendored_dir(repo, layout)
    has_sync = (vdir / "sync-versions.py").is_file() or any(repo.glob("scripts/**/sync-versions.py"))
    has_bash = (vdir / "update-version.sh").is_file() or any(repo.glob("scripts/**/update-version.sh"))
    hooks = git_hooks_dir(repo)
    pre = hooks / "pre-commit" if hooks else None
    detail = {"sync": has_sync, "bash": has_bash, "vendored": str(vdir.relative_to(repo))}
    if not pre or not pre.is_file():
        return "no-hook", detail
    text = pre.read_text(encoding="utf-8", errors="replace")
    stub = "repokit-common hook stub" in text
    detail["hook"] = "stub" if stub else "full"
    calls_sync = "sync-versions" in text or "SYNC_SCRIPT" in text
    calls_bash = "update-version" in text or "UPDATE_SCRIPT" in text
    if stub:
        # a stub runs the vendored hooks/pre-commit, which prefers sync-versions.py
        return ("sync" if has_sync else ("bash" if has_bash else "other")), detail
    if calls_sync and has_sync:
        return "sync", detail
    if calls_bash or (calls_sync and not has_sync and has_bash):
        return "bash", detail
    return "other", detail


def main(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    recs = [r for r in data["records"] if not r.get("backup")]

    known = {
        r"C:\code\git-repokit-common": "no-hook-or-sync",  # the upstream itself
    }
    rows, tally = [], Counter()
    for r in recs:
        repo = Path(r["repo"])
        cls, det = classify(repo, r.get("layout", ""))
        tally[cls] += 1
        rows.append((cls, str(repo), r.get("layout"), r.get("hook"), det))

    # Known-answer: xormove carries its own update-version.sh hook and no
    # repokit-common subtree; it is not in the roster, so classify it directly.
    xm = Path(r"C:\code\xormove\local")
    if xm.is_dir():
        cls, det = classify(xm, "own:scripts")
        print(f"KNOWN-ANSWER xormove/local -> {cls} {det}  (expected: bash)")

    for row in sorted(rows):
        print(" | ".join(str(x) for x in row))
    print()
    print(f"live records: {len(recs)}")
    for k, v in tally.most_common():
        print(f"  {k}: {v}")
    print(f"  sum: {sum(tally.values())}")


if __name__ == "__main__":
    main(sys.argv[1])
