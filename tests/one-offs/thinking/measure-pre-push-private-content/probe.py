"""Measure, for the 0.4.4 pre-push private-content refusal (2026-11-06):

Q1  On how many git-repokit-common consumers does the main branch (main, else
    master) already TRACK a path that matches the private patterns (the
    built-in regex from hooks/pre-commit plus the project's private-patterns),
    minus .repokit-allowlist? A refusal that checks the pushed branch's whole
    tree would newly refuse every push of those projects.
Q2  How many consumers have remote branches whose names match the default
    private-branches list (local private feature/* feat/* prototype/*
    experiment/* spike/*)? A refusal by branch name would newly refuse those
    pushes.

Prediction (written first): Q1 a few (<= 5 of ~50), mostly *.log / .bak;
Q2 a handful with feature/* branches on a remote.

Read-only: `git rev-parse`, `git ls-tree`, `git branch -r`. Known-answer
control: a throwaway repo under this script's folder with logs/x.log
committed on main must be counted in Q1, and one with origin/feature/x in Q2.

    python probe.py > results-raw.txt
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path("C:/code")
SKIP_DIRS = {"node_modules", ".git", "site-packages", ".venv", "venv", "__pycache__", "dist", "build"}
spec = importlib.util.spec_from_file_location("rkc", "C:/code/git-repokit-common/repokit_config.py")
rkc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rkc)

# hooks/pre-commit:162, verbatim
BUILTIN = re.compile(r"^.*/__private__.*|^.*/private_.*|^.*~$|\.backup$|\.bak$|\.log$|\.tmp$|^\.env.*|^\.env\.local$|^\.env\.private$|^convos/|^credentials/|^logs/|^nul$|^private/|^revisions/|^secrets/|^test-runs/|^test_runs/")
DEFAULT_PRIVATE = "local private feature/* feat/* prototype/* experiment/* spike/*".split()


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=rkc.sanitized_git_env())
    return r.stdout if r.returncode == 0 else ""


def walk_consumers():
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        depth = Path(dirpath).relative_to(ROOT).parts
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and len(depth) < 6]
        if "repokit_config.py" in filenames or "sync-versions.py" in filenames:
            hits.append(Path(dirpath))
    return hits


def project_patterns(top):
    try:
        cfg = rkc.find_config(top)
        if not cfg:
            return []
        table = rkc.read_table(cfg) or {}
        v = table.get("private-patterns", [])
        return [v] if isinstance(v, str) else list(v)
    except Exception as e:  # noqa: BLE001 -- a probe reports, never stops
        return [f"<unreadable: {e}>"]


def allowlist(top):
    f = Path(top) / ".repokit-allowlist"
    if not f.is_file():
        return set()
    return {l.strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines()
            if l.strip() and not l.lstrip().startswith("#")}


def survey(top):
    branch = "main" if git(top, "rev-parse", "--verify", "-q", "refs/heads/main").strip() else (
        "master" if git(top, "rev-parse", "--verify", "-q", "refs/heads/master").strip() else None)
    q1 = []
    if branch:
        pats = [p.lstrip("./").lstrip("/") for p in project_patterns(top) if p and not p.startswith("<")]
        allow = allowlist(top)
        for path in git(top, "ls-tree", "-r", "--name-only", branch).splitlines():
            if path in allow:
                continue
            if BUILTIN.search(path) or any(path.startswith(p) for p in pats):
                q1.append(path)
    q2 = []
    for rb in git(top, "branch", "-r", "--format=%(refname:short)").splitlines():
        name = rb.split("/", 1)[1] if "/" in rb else rb
        if name == "HEAD":
            continue
        if any(fnmatchcase(name, p) for p in DEFAULT_PRIVATE):
            q2.append(rb)
    return branch, q1, q2


def _rm(d):
    # git's object files are read-only on Windows
    def onerr(func, path, _exc):
        os.chmod(path, 0o700)
        func(path)
    shutil.rmtree(d, onexc=onerr)


def control():
    d = HERE / "control"
    if d.exists():
        _rm(d)
    remote = d / "remote.git"
    repo = d / "repo"
    env = dict(rkc.sanitized_git_env(), GIT_CEILING_DIRECTORIES=str(HERE))
    run = lambda cwd, *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e",
                                          "-c", "commit.gpgsign=false", *a], cwd=cwd, env=env,
                                         capture_output=True, check=True)
    d.mkdir()
    run(d, "init", "-q", "--bare", "-b", "main", str(remote))
    run(d, "init", "-q", "-b", "main", str(repo))
    (repo / "logs").mkdir()
    (repo / "logs" / "x.log").write_text("x\n")
    run(repo, "add", "-f", ".")
    run(repo, "commit", "-q", "--no-verify", "-m", "c")
    run(repo, "remote", "add", "origin", str(remote))
    run(repo, "push", "-q", "--no-verify", "origin", "main", "main:feature/x")
    run(repo, "fetch", "-q", "origin")
    b, q1, q2 = survey(repo)
    ok = q1 == ["logs/x.log"] and "origin/feature/x" in q2
    _rm(d)
    return ok, q1, q2


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ok, q1, q2 = control()
    print(f"control: {'PASS' if ok else 'FAIL'} q1={q1} q2={q2}")
    if not ok:
        sys.exit(1)
    seen = {}
    for copy in walk_consumers():
        top = git(copy, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        if not top:
            continue
        top = str(Path(top).parent) if top.endswith(".git") else top
        seen.setdefault(top, copy)
    rows = []
    for top in sorted(seen):
        b, q1, q2 = survey(top)
        rows.append((top, b, q1, q2))
        print(f"{top}\tbranch={b}\tq1={len(q1)}\tq2={len(q2)}")
        for p in q1[:8]:
            print(f"    tracked: {p}")
        if len(q1) > 8:
            print(f"    ... {len(q1) - 8} more")
        for r in q2:
            print(f"    remote: {r}")
    n = len(rows)
    print(f"\nconsumers: {n}")
    print(f"Q1 main tracks private-pattern paths: {sum(1 for r in rows if r[2])}/{n}")
    print(f"Q2 remote branches named private by default: {sum(1 for r in rows if r[3])}/{n}"
          f" ({sum(len(r[3]) for r in rows)} branches)")


if __name__ == "__main__":
    main()
