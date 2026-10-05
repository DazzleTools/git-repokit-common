"""Language census of repokit-common's consumers (read-only).

Input: the consumer roster probe's JSON output, with a "records" list of
checkouts (path as argv[1]). For each live consumer checkout, records the
product-language markers at its root and where its config lives. Written for
the 2026-10-04 design of language profiles (the two-layer model), to count
who each profile would serve.
"""

import json
import sys
from collections import Counter
from pathlib import Path

MARKERS = {
    "python-package": lambda r: (r / "setup.py").exists() or (r / "setup.cfg").exists()
        or ((r / "pyproject.toml").exists()
            and "[project]" in (r / "pyproject.toml").read_text(encoding="utf-8", errors="replace")),
    "node": lambda r: (r / "package.json").exists(),
    "claude-plugin": lambda r: (r / ".claude-plugin" / "plugin.json").exists(),
    "rust": lambda r: (r / "Cargo.toml").exists(),
    "c-cpp": lambda r: (r / "CMakeLists.txt").exists() or any(r.glob("*.vcxproj")) or any(r.glob("*/*.vcxproj")),
    "csharp": lambda r: any(r.glob("*.sln")) or any(r.glob("*.csproj")) or any(r.glob("*/*.csproj")),
    "go": lambda r: (r / "go.mod").exists(),
    "comfyui-node": lambda r: (r / "__init__.py").exists() and (r / "pyproject.toml").exists()
        and "comfy" in (r / "pyproject.toml").read_text(encoding="utf-8", errors="replace").lower(),
}


def main(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    recs = data if isinstance(data, list) else data.get("records", [])
    rows, tally = [], Counter()
    for rec in recs:
        if rec.get("backup"):
            continue
        root = Path(rec["repo"])
        if not root.is_dir():
            continue
        hits = [name for name, test in MARKERS.items() if test(root)]
        langs = hits or ["python-scripts/other"]
        for lang in langs:
            tally[lang] += 1
        rows.append((str(root), ",".join(langs), Path(rec.get("config_file") or "-").name))
    for row in sorted(rows):
        print("  ".join(row))
    print()
    print(f"live consumers: {len(rows)}")
    for lang, n in tally.most_common():
        print(f"  {lang}: {n}")


if __name__ == "__main__":
    main(sys.argv[1])
