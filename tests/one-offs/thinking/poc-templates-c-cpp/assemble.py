"""Assemble a project from the one templates repo (POC).

Usage:
  assemble.py <templates-dir> <archetype> <name> <dest> [--org ORG] [--description TEXT]
  assemble.py <templates-dir> <archetype> <name> <dest> --no-substitute   (control arm)

Layers named by the archetype in manifest.toml are copied in order; a later
file replaces an earlier one, and <file>.rkappend is appended to <file>.
Then __RK_*__ tokens are replaced inside every text file and in every path.
Workflow files (.github/workflows/) are copied byte for byte and must hold no
token: a token there is an error, because GitHub Actions' own ${{ }} syntax
lives in those files and they must never pass through substitution.

Exit codes: 0 assembled, 2 usage/error, 3 the archetype is a stub.
"""

import argparse
import datetime
import re
import shutil
import sys
import tomllib
import uuid
from pathlib import Path

TOKEN = re.compile(rb"__RK_[A-Z_]+?__")
APPEND = ".rkappend"


def names(name, org, description, archetype):
    words = re.split(r"[-_\s]+", name)
    return {
        "__RK_PROJECT__": name,                                  # my-tool
        "__RK_SNAKE__": "_".join(words).lower(),                 # my_tool
        "__RK_MACRO__": "_".join(words).upper(),                 # MY_TOOL
        "__RK_PASCAL__": "".join(w.capitalize() for w in words), # MyTool
        "__RK_ORG__": org,
        "__RK_DESCRIPTION__": description,
        "__RK_ARCHETYPE__": archetype,
        "__RK_YEAR__": str(datetime.date.today().year),
        "__RK_DATE__": datetime.date.today().isoformat(),
        "__RK_GUID_PROJECT__": str(uuid.uuid4()).upper(),
        "__RK_GUID_SOLUTION__": str(uuid.uuid4()).upper(),
    }


def is_text(data):
    return b"\0" not in data[:8192]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("templates")
    ap.add_argument("archetype")
    ap.add_argument("name")
    ap.add_argument("dest")
    ap.add_argument("--org", default="DazzleTools")
    ap.add_argument("--description", default="A project made from the repokit templates")
    ap.add_argument("--no-substitute", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.templates)
    manifest = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
    entry = manifest["archetypes"].get(a.archetype)
    if entry is None:
        print(f"unknown archetype {a.archetype!r}; known: {', '.join(manifest['archetypes'])}")
        return 2
    if entry.get("stub"):
        print(f"{a.archetype} is a stub, not built yet: {entry.get('description', '')}")
        return 3

    dest = Path(a.dest)
    if dest.exists():
        print(f"refusing: {dest} exists")
        return 2

    # 1. Layers, in order. Keys are template-relative paths with tokens unresolved.
    files = {}
    for layer in entry["layers"]:
        base = root / layer
        for src in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = src.relative_to(base).as_posix()
            data = src.read_bytes()
            if rel.endswith(APPEND):
                target = rel[: -len(APPEND)]
                files[target] = files.get(target, b"") + data
            else:
                files[rel] = data

    subs = {k.encode(): v.encode() for k, v in names(a.name, a.org, a.description, a.archetype).items()}

    def resolve(blob):
        for k, v in subs.items():
            blob = blob.replace(k, v)
        return blob

    # 2. Write, substituting inside text files and in paths.
    for rel, data in files.items():
        is_workflow = rel.startswith(".github/workflows/")
        if is_workflow and TOKEN.search(data):
            print(f"error: token in workflow file {rel}; workflow files must stay placeholder-free")
            return 2
        out_rel = rel if a.no_substitute else resolve(rel.encode()).decode()
        if not a.no_substitute and not is_workflow and is_text(data):
            data = resolve(data)
        out = dest / out_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)

    print(f"assembled {a.archetype} as {a.name} into {dest} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
