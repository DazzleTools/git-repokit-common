"""Count distinct projects and layouts among the fallback census's "bash" rows.

Usage: count_bash_projects.py <fallback_census output file>
A project with local/ and github/ checkouts counts once.
"""

import sys
from pathlib import PureWindowsPath

rows = [line.split(" | ") for line in open(sys.argv[1], encoding="utf-8")
        if line.startswith("bash |")]
projects = set()
for r in rows:
    p = PureWindowsPath(r[1].strip())
    projects.add(str(p.parent) if p.name in ("local", "github") else str(p))
layouts = sorted({r[2].strip() for r in rows})
print(f"{len(rows)} checkouts, {len(projects)} projects, layouts: {layouts}")
