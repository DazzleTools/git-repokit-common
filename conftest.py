"""pytest settings for repokit-common's own checkout, and for vendored copies.

When repokit-common is vendored into another project (a subtree at
scripts/repokit-common/, or a submodule), a bare `pytest` at that project's
root would also collect this copy's own suite: 182 tests that belong here,
not there (found by claude-bookmarks, whose bare `pytest` collected 191).
There, they are skipped; here, where repokit-common is the project, they run.
"""

import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", str(_HERE), "rev-parse", *args],
                           capture_output=True, text=True)
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _vendored():
    """True when this copy lives inside another project's repository."""
    top = _git("--show-toplevel")
    if not top:
        return False
    if Path(top).resolve() != _HERE:
        return True  # a subtree or a plain copy
    return bool(_git("--show-superproject-working-tree"))  # a submodule


collect_ignore = ["tests"] if _vendored() else []
