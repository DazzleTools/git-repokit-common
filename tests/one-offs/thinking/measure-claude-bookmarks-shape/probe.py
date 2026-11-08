"""Measure what claude-bookmarks' pre-push prints at 0.3.4 and with 0.4.3 (2026-10-31).

Question: does the 0.4.3 pull alone remove "No Python package directory found",
and what does declaring languages = ["typescript", "python"] change? Decides
what claude-bookmarks should do, and whether git-repokit should write
`languages` for mixed projects.

Read-only on the real repository: its tracked files are copied (git archive)
into a temp folder; the hook runs there with its stdin built by hand. The
project's test-command is replaced for the run (REPOKIT_TEST_COMMAND, which
wins over the setting) so only the hook's own steps differ between runs.

Usage: python probe.py <claude-bookmarks checkout> <git-repokit-common checkout>
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

cb, rkc = Path(sys.argv[1]), Path(sys.argv[2])

# The shell git runs hooks with. A bare "bash" from Python on Windows can be
# System32's WSL bash, which has no Python: the first run of this probe got
# "python: command not found" and failed its known-answer check (case A must
# reproduce the push output claude-bookmarks prints today).
_exec = Path(subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip())
BASH = next((str(p) for p in (_exec.parents[2] / "bin" / "bash.exe", _exec.parents[2] / "usr" / "bin" / "bash.exe",
                              Path("/bin/bash")) if p.exists()), "bash")
work = Path(tempfile.mkdtemp(prefix="cb-shape-"))
GIT = ["git", "-c", "user.email=p@example.invalid", "-c", "user.name=p",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def make(name, rkc_copy, languages=None):
    root = work / name
    root.mkdir()
    tar = subprocess.run(["git", "-C", str(cb), "archive", "HEAD"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(root)], input=tar, check=True)
    if rkc_copy:
        shutil.rmtree(root / "scripts" / "repokit-common")
        shutil.copytree(rkc_copy, root / "scripts" / "repokit-common", ignore=shutil.ignore_patterns(
            ".git", "private", "tests", "__pycache__", ".vscode", "demo", "docs"))
    if languages:
        cfg = root / ".repokit-common.toml"
        text = cfg.read_text(encoding="utf-8")
        cfg.write_text(text.replace("[tool.repokit-common]\n", f"[tool.repokit-common]\nlanguages = {languages}\n", 1),
                       encoding="utf-8")
    subprocess.run([*GIT, "init", "-q", "-b", "dev"], cwd=root, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=root, check=True)
    subprocess.run([*GIT, "commit", "-q", "--no-verify", "-m", "probe"], cwd=root, check=True)
    return root


def prepush(root):
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "REPOKIT_TEST_COMMAND": "echo test-command-stubbed-for-the-probe", "REPOKIT_OUTPUT": "plain"}
    r = subprocess.run([BASH, "scripts/repokit-common/hooks/pre-push", "origin", "unused"], cwd=root, env=env,
                       input=f"refs/heads/dev {sha} refs/heads/dev {'0' * 40}\n",
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


cases = [
    ("A. as it is today (vendored 0.3.4)", make("a", None)),
    ("B. 0.4.3 pulled, nothing else", make("b", rkc)),
    ("C. 0.4.3 + languages = [\"typescript\", \"python\"]", make("c", rkc, '["typescript", "python"]')),
]
for title, root in cases:
    rc, out = prepush(root)
    print(f"===== {title}: exit {rc}")
    for line in out.splitlines():
        if line.strip():
            print("   " + line)


def _writable_then_retry(func, path, _exc):
    os.chmod(path, 0o700)
    func(path)


shutil.rmtree(work, onexc=_writable_then_retry)
print(f"\n(bash used: {BASH}; temp folder removed: {not work.exists()})")
