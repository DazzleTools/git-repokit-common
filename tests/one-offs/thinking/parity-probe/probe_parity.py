"""Measure: what sync-versions.py does today with --pre-num and --phase on each
version-source kind (2026-10-09, 0.4.0 staged).

Five fixtures in a temp dir, each a throwaway git project with the tool
vendored at scripts/. For each: exit code, bytes changed, stdout+stderr, and
what read_version_components reports afterwards. Known-answer case: Python
WITH the PRE_RELEASE_NUM line must store --pre-num 2. The decision: which of
P1 (header reads/writes PRE_RELEASE_NUM / PROJECT_PHASE) and P2 (warn when a
flag cannot land) are real gaps, and what the anchor test's red observation is.
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TOOL = REPO / "sync-versions.py"

PY_FULL = 'MAJOR = 0\nMINOR = 1\nPATCH = 0\nPHASE = ""\nPRE_RELEASE_NUM = 1\nPROJECT_PHASE = "alpha"\n__version__ = "0.1.0"\n'
PY_BARE = 'MAJOR = 0\nMINOR = 1\nPATCH = 0\nPHASE = ""\n__version__ = "0.1.0"\n'
HDR_BARE = ('#define T_VERSION_MAJOR 0\n#define T_VERSION_MINOR 1\n#define T_VERSION_PATCH 0\n'
            '#define T_VERSION_PHASE ""\n#define T_VERSION_STRING "0.1.0"\n')
HDR_FULL = HDR_BARE + '#define T_VERSION_PRE_RELEASE_NUM 1\n#define T_PROJECT_PHASE "alpha"\n'

FIXTURES = {
    "python-full": ("pkg/_version.py", PY_FULL),
    "python-bare": ("pkg/_version.py", PY_BARE),
    "plain": ("VERSION", "0.1.0\n"),
    "header-bare": ("include/t/version.h", HDR_BARE),
    "header-full": ("include/t/version.h", HDR_FULL),
}


def project(root, name, rel, text):
    d = root / name
    (d / "scripts").mkdir(parents=True)
    shutil.copy(TOOL, d / "scripts" / "sync-versions.py")
    shutil.copy(REPO / "repokit_config.py", d / "scripts" / "repokit_config.py")
    (d / ".repokit-common.toml").write_text(f'[tool.repokit-common]\nversion-source = "{rel}"\ntag-format = "human"\n', encoding="utf-8")
    f = d / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=d, check=True, capture_output=True)
    return d, f


def run(d, *args):
    r = subprocess.run([sys.executable, "scripts/sync-versions.py", *args, "--no-git-ver"], cwd=d, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr).strip().replace("\n", " | ")


def components(d, rel):
    spec = importlib.util.spec_from_file_location("sv_probe", d / "scripts" / "sync-versions.py")
    mod = importlib.util.module_from_spec(spec)
    cwd = Path.cwd()
    try:
        import os
        os.chdir(d)
        spec.loader.exec_module(mod)
        c = mod.read_version_components(d / rel)
    finally:
        os.chdir(cwd)
    return c["pre_release_num"], c["project_phase"], c["phase"]


def main():
    root = Path(tempfile.mkdtemp(prefix="parity-"))
    print(f"{'fixture':13} {'flag':16} {'rc':>2} {'file changed':12} pre/proj/phase after      output")
    try:
        for name, (rel, text) in FIXTURES.items():
            for flag in (["--pre-num", "2"], ["--phase", "alpha"]):
                d, f = project(root, f"{name}-{flag[0][2:]}", rel, text)
                before = f.read_bytes()
                rc, out = run(d, *flag)
                changed = f.read_bytes() != before
                pre, proj, phase = components(d, rel)
                print(f"{name:13} {' '.join(flag):16} {rc:>2} {str(changed):12} {str((pre, proj, phase)):26} {out[:90]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
