"""Prototype version reader/writer for C/C++ sources (POC, not production).

  version_c.py read  <source>                    print the version (VERSION file or C header)
  version_c.py bump  <header> <PREFIX> <part>     bump major|minor|patch in a C header, in place
  version_c.py rc    <rc-file> <old> <new> <enc>  replace a version string in an .rc file, in place,
                                                  decoding and encoding with <enc> (e.g. cp1252)

Edits are made on bytes: only the version text changes; BOM, line endings and
every other byte are kept. This is the property the real sync-versions.py
targets must have (Locate64's 0xA9 lesson).
"""

import re
import sys
from pathlib import Path

DEF = rb"^(#define\s+%s_VERSION_(MAJOR|MINOR|PATCH)\s+)(\d+)"


def read_version(path):
    p = Path(path)
    data = p.read_bytes().lstrip(b"\xef\xbb\xbf")
    if p.name == "VERSION":
        return data.decode("utf-8").strip()
    comps = dict(re.findall(rb"#define\s+\w+_VERSION_(MAJOR|MINOR|PATCH)\s+(\d+)", data))
    phase = re.search(rb'#define\s+\w+_VERSION_PHASE\s+"([^"]*)"', data)
    v = ".".join(comps[k].decode() for k in (b"MAJOR", b"MINOR", b"PATCH"))
    return v + (f"-{phase.group(1).decode()}" if phase and phase.group(1) else "")


def bump_header(path, prefix, part):
    p = Path(path)
    data = p.read_bytes()
    comps = {k.decode(): int(v) for _, k, v in re.findall(DEF % prefix.encode(), data, re.M)}
    if part == "major":
        comps.update(MAJOR=comps["MAJOR"] + 1, MINOR=0, PATCH=0)
    elif part == "minor":
        comps.update(MINOR=comps["MINOR"] + 1, PATCH=0)
    else:
        comps.update(PATCH=comps["PATCH"] + 1)
    data = re.sub(DEF % prefix.encode(),
                  lambda m: m.group(1) + str(comps[m.group(2).decode()]).encode(), data, flags=re.M)
    new = f"{comps['MAJOR']}.{comps['MINOR']}.{comps['PATCH']}"
    data = re.sub(rb'(#define\s+%s_VERSION_STRING\s+")[^"]*(")' % prefix.encode(),
                  lambda m: m.group(1) + new.encode() + m.group(2), data)
    p.write_bytes(data)
    return new


def rc_replace(path, old, new, enc):
    p = Path(path)
    text = p.read_bytes().decode(enc)
    if old not in text:
        raise SystemExit(f"{old!r} not found in {path}")
    p.write_bytes(text.replace(old, new).encode(enc))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "read":
        print(read_version(sys.argv[2]))
    elif cmd == "bump":
        print(bump_header(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif cmd == "rc":
        rc_replace(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        raise SystemExit(__doc__)
