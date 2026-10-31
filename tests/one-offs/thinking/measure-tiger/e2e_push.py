"""End to end: real pushes through this checkout's hooks, before the 0.4.3 last-mile.

Three throwaway repositories under a temp folder, each with a bare remote
beside it and repokit-common vendored at scripts/repokit-common/, hooks
installed by install-hooks.sh and core.hooksPath pinned on every git call:

1. a CK3 mod (DaddyPika's Cheat Menu, copied) with languages = ["paradox"],
   the REAL ck3-tiger on PATH, and the pattern target on mod/descriptor.mod;
2. a project that sets nothing (python by default) with a broken tooling
   script: the syntax check must still stop it;
3. a claude-bookmarks-shaped project: languages = ["typescript", "python"],
   the plugin in plugin/, Python tests in tests/.

Nothing outside the temp folder is written; the mod and the game are only read.
Usage: python e2e_push.py <folder holding ck3-tiger.exe> <mod folder>
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RK = Path(__file__).resolve().parents[4]          # this checkout of git-repokit-common
tiger_dir, mod_src = Path(sys.argv[1]), Path(sys.argv[2])
work = Path(tempfile.mkdtemp(prefix="rk-e2e-"))
GIT = ["git", "-c", "user.email=e2e@example.invalid", "-c", "user.name=e2e",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def git(cwd, *args, env=None, check=True):
    hooks = cwd / ".git" / "hooks"
    return subprocess.run([*GIT, "-c", f"core.hooksPath={hooks}", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def project(name, files, raw=None):
    remote = work / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    root = work / name
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", str(remote))
    vend = root / "scripts" / "repokit-common"
    shutil.copytree(RK, vend, ignore=shutil.ignore_patterns(
        ".git", "private", "tests", "__pycache__", ".vscode", "demo", "docs"))
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    for rel, src in (raw or {}).items():
        shutil.copytree(src, root / rel)
    r = subprocess.run(["bash", "scripts/repokit-common/install-hooks.sh"], cwd=root, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr
    return root


def commit_and_push(root, env=None):
    git(root, "add", "-A")
    c = git(root, "commit", "-q", "-m", "e2e", env=env, check=False)
    p = git(root, "push", "-q", "origin", "main", env=env, check=False)
    landed = subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/main"],
                            cwd=work / f"{root.name}.git", capture_output=True).returncode == 0
    return c, p, landed


def show(title, c, p, landed):
    print(f"\n===== {title}: commit exit {c.returncode}, push exit {p.returncode}, landed {landed}")
    for line in (c.stdout + c.stderr + p.stdout + p.stderr).splitlines():
        if line.strip():
            print("   " + line[:200])


env_tiger = {**os.environ, "PATH": str(tiger_dir) + os.pathsep + os.environ["PATH"]}

# 1. the mod
mod = project("ck3-mod", {
    ".repokit-common.toml": ('[tool.repokit-common]\nlanguages = ["paradox"]\nparadox-game = "ck3"\n'
                             'version-source = "VERSION"\n\n[[tool.repokit-common.extra-targets]]\n'
                             'path = "mod/descriptor.mod"\npattern = \'^version="([^"]*)"\\r?$\'\nformat = "base"\n'),
    "VERSION": "0.2.0\n",
    "tools/link_mod.py": "def broken(:\n",                # tooling Python: not checked for a mod
}, raw={"mod": mod_src})
before = (mod / "mod" / "descriptor.mod").read_bytes()
show("1. CK3 mod, real ck3-tiger", *commit_and_push(mod, env=env_tiger))
after = (mod / "mod" / "descriptor.mod").read_bytes()
changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
print(f"   descriptor.mod lines changed by the commit: {changed}")
print(f"   descriptor.mod BOM before/after: {before[:3] == b'\\xef\\xbb\\xbf'}/{after[:3] == b'\\xef\\xbb\\xbf'}, "
      f"CRLF before/after: {b'\\r\\n' in before}/{b'\\r\\n' in after}")
report = mod / ".git" / "repokit-ck3-tiger.txt"
print(f"   report: {report.exists()} ({len(report.read_text(encoding='utf-8').splitlines()) if report.exists() else 0} lines)")

# 1b. the BOM check, for real: a localization file saved without its BOM
loc = next((mod / "mod" / "localization").rglob("*.yml"))
loc.write_bytes(loc.read_bytes().removeprefix(b"\xef\xbb\xbf"))
git(mod, "add", "-A")
c = git(mod, "commit", "-q", "-m", "no bom", check=False)
print(f"\n===== 1b. localization without a BOM: commit exit {c.returncode}")
print("   " + "\n   ".join(l for l in (c.stdout + c.stderr).splitlines() if l.strip())[:600])
git(mod, "reset", "-q", "HEAD", "--", ".")               # unstage in the throwaway repo only

# 2. python by default
py = project("py-default", {"tools/gen.py": "def broken(:\n", "tests/test_a.py": "def test_ok():\n    pass\n"})
show("2. Python by default, broken tooling script", *commit_and_push(py))

# 3. claude-bookmarks-shaped
cb = project("cb-shaped", {
    ".repokit-common.toml": ('[tool.repokit-common]\nlanguages = ["typescript", "python"]\nversioning = "off"\n'
                             'check-command.typescript = "echo tsc-would-run-on-plugin"\n'),
    "plugin/tsconfig.json": "{}\n", "plugin/src/index.ts": "export const x = 1;\n",
    "tests/test_version.py": "def test_ok():\n    pass\n",
})
show("3. typescript + python (claude-bookmarks shape)", *commit_and_push(cb))

def _writable_then_retry(func, path, _exc):
    # git's object files are read-only; on Windows rmtree cannot remove them as they are
    os.chmod(path, 0o700)
    func(path)


shutil.rmtree(work, onerror=_writable_then_retry)
print(f"\n(temp folder removed: {not work.exists()})")
