"""Arm A5: encoding preservation (POC).

Builds two fixtures in <dir>:
  version_bom_crlf.h  UTF-8 with BOM and CRLF line endings, a 0xC2 0xA9 (©) in a comment
  commonres.rc        Windows-1252 with a raw 0xA9 (©) and Locate64-style version text
Then:
  1. bumps the header's patch with version_c.bump_header and checks that every byte
     outside the PATCH and STRING lines is identical (BOM and CRLF kept);
  2. rewrites the .rc version text with version_c.rc_replace(..., "cp1252") and
     checks the 0xA9 count and every other line are unchanged;
  3. control: the same .rc edit done naively (read as UTF-8 with replacement,
     written as UTF-8) -- predicted to corrupt the 0xA9.
Prints one PASS/FAIL line per step and exits non-zero on any unexpected result.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import version_c  # noqa: E402

d = Path(sys.argv[1])
d.mkdir(parents=True, exist_ok=True)

hdr = d / "version_bom_crlf.h"
hdr_lines = [
    "#ifndef MY_TOOL_VERSION_H",
    "#define MY_TOOL_VERSION_H",
    "/* (c) © 2026 example */",
    "#define MY_TOOL_VERSION_MAJOR 1",
    "#define MY_TOOL_VERSION_MINOR 4",
    "#define MY_TOOL_VERSION_PATCH 9",
    '#define MY_TOOL_VERSION_PHASE ""',
    '#define MY_TOOL_VERSION_STRING "1.4.9"',
    "#endif",
]
hdr.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(hdr_lines).encode("utf-8") + b"\r\n")
before = hdr.read_bytes()

rc = d / "commonres.rc"
rc_text = (
    'FILEVERSION 3,2,11,8221\r\n'
    'VALUE "LegalCopyright", "Copyright \xa9 1997-2011 Janne Huttunen"\r\n'
    'VALUE "ProductVersion", "3.2 RC4 build 11.8221"\r\n'
)
rc.write_bytes(rc_text.encode("cp1252"))
rc_before = rc.read_bytes()

ok = True
BOM, CRLF, A9, REPL = b"\xef\xbb\xbf", b"\r\n", b"\xa9", b"\xef\xbf\xbd"


def report(name, cond, detail):
    global ok
    print(f"{'PASS' if cond else 'FAIL'} {name}: {detail}")
    ok &= cond


# 1. header bump
new = version_c.bump_header(hdr, "MY_TOOL", "patch")
after = hdr.read_bytes()
b_lines, a_lines = before.split(b"\r\n"), after.split(b"\r\n")
changed = [i for i, (x, y) in enumerate(zip(b_lines, a_lines)) if x != y]
bom_kept = after[:3] == BOM
report("header", new == "1.4.10" and bom_kept and after.count(CRLF) == before.count(CRLF)
       and changed == [5, 7] and len(b_lines) == len(a_lines),
       f"new={new} bom={bom_kept} crlf={after.count(CRLF)}/{before.count(CRLF)} changed-lines={changed}")
report("header read", version_c.read_version(hdr) == "1.4.10", f"read={version_c.read_version(hdr)}")

# 2. cp1252 .rc edit
version_c.rc_replace(rc, "3.2 RC4 build 11.8221", "3.2 RC5 build 11.8222", "cp1252")
rc_after = rc.read_bytes()
same_other = rc_after.split(b"\r\n")[:2] == rc_before.split(b"\r\n")[:2]
report("rc cp1252", rc_after.count(A9) == rc_before.count(A9) == 1 and same_other and b"RC5 build 11.8222" in rc_after,
       f"0xA9 {rc_before.count(A9)}->{rc_after.count(A9)}, other lines identical={same_other}")

# 3. control: naive UTF-8 round trip of the original .rc
naive = d / "commonres_naive.rc"
naive.write_bytes(rc_before)
t = naive.read_text(encoding="utf-8", errors="replace").replace("RC4 build 11.8221", "RC5 build 11.8222")
naive.write_text(t, encoding="utf-8", newline="")
nb = naive.read_bytes()
corrupted = nb.count(A9) != 1 or REPL in nb
report("control (naive UTF-8, predicted corrupt)", corrupted,
       f"0xA9 raw count={nb.count(A9)}, replacement char present={REPL in nb}")

sys.exit(0 if ok else 1)
