"""Measure the real ck3-tiger before the pre-push hook relies on it (0.4.3).

Question: how must the hook call Tiger, and what does its exit code mean?
The hook's paradox profile was written against a stub that accepted anything;
Tiger's README says ck3-tiger takes the descriptor.mod FILE, not the folder.
Decides: the hook's argument per game, whether to pass --no-color, and how a
non-zero exit is reported.

Read-only on every real path: the mod is copied to a temp folder first and
Tiger runs on the copy; the game install is only read by Tiger.

Usage: python probe.py <ck3-tiger.exe> <mod folder> <game folder>
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

tiger, mod_src, game = (Path(a) for a in sys.argv[1:4])
work = Path(tempfile.mkdtemp(prefix="tiger-probe-"))
mod = work / "mod"
shutil.copytree(mod_src, mod)

clean = work / "clean"
(clean / "localization" / "english").mkdir(parents=True)
(clean / "descriptor.mod").write_text(
    'version="0.1.0"\nname="Probe"\nsupported_version="1.20.*"\n', encoding="utf-8")
(clean / "localization" / "english" / "probe_l_english.yml").write_bytes(
    b'\xef\xbb\xbfl_english:\n probe_key:0 "Probe"\n')

CASES = [
    ("descriptor file", [str(mod / "descriptor.mod")]),
    ("mod folder (the hook's call before the fix)", [str(mod)]),
    ("clean minimal mod, descriptor file", [str(clean / "descriptor.mod")]),
    ("descriptor file, --no-color", ["--no-color", str(mod / "descriptor.mod")]),
]

for name, args in CASES:
    t0 = time.monotonic()
    r = subprocess.run([str(tiger), "--game", str(game), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    dt = time.monotonic() - t0
    out = r.stdout + r.stderr
    lines = out.splitlines()
    print(f"=== {name}: exit {r.returncode}, {len(lines)} lines, {dt:.1f}s, "
          f"escape codes: {'yes' if chr(27) in out else 'no'}")
    for kind in ("error", "warning", "tips", "untidy", "fatal"):
        print(f"    lines starting '{kind}': {sum(1 for l in lines if l.lower().startswith(kind))}")
    print("    first lines:")
    for l in lines[:6]:
        print("      " + l[:160])
    print("    last lines:")
    for l in lines[-3:]:
        print("      " + l[:160])

shutil.rmtree(work, ignore_errors=True)
