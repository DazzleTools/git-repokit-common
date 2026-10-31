#!/usr/bin/env python3
"""Find and read a project's repokit-common settings.

Settings live in the consuming project's ``pyproject.toml`` under
``[tool.repokit-common]``. A project without a ``pyproject.toml`` (C/C++,
Rust, TypeScript, ...) puts the same table in a ``.repokit-common.toml`` at
its root; a key there outside any table is an error, never silently ignored.
When both files exist in one directory, ``pyproject.toml`` wins.

Discovery walks up from the calling tool's own directory -- not the current
directory -- to the nearest file that holds the table, skipping a
``pyproject.toml`` without it. The walk never leaves the project: when it
reaches a directory containing ``.git`` it asks git, once, where the project
ends (the superproject's root when repokit-common is a submodule, else the
repository root) and stops there. Outside git there is no bound. This rule was
chosen by a proof of concept over eight layouts
(tests/one-offs/thinking/config-discovery/poc_config_discovery.py).

Command line (for the sh hooks):

    repokit_config.py --get KEY           print the value; a list prints one
                                          item per line; unset prints nothing
    repokit_config.py --shell KEY [KEY..] print REPOKIT_<KEY>=<quoted value>
                                          lines for `eval`; one call per hook
    repokit_config.py --where             print the config file's path
    --start DIR                           walk from DIR instead of this file's
                                          directory

Exit 0 on success (also when nothing is configured), 2 when a config file
exists but cannot be read (malformed TOML), with the reason on stderr, so a
hook can refuse rather than silently fall back to defaults. A Python with no
TOML parser (before 3.11, without tomli) is an environment gap, not a broken
file: it prints a warning on stderr and answers as if nothing were set.

Output for the hooks (stdout) is always UTF-8 with LF line endings, whatever
the console code page, because git gives the hooks paths as UTF-8.
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

TABLE = "repokit-common"
FALLBACK_NAME = ".repokit-common.toml"
_TABLE_HEADER = re.compile(r'^\s*\[\s*tool\s*\.\s*"?repokit-common"?\s*\]', re.MULTILINE)
_PROJECT_HEADER = re.compile(r'^\s*\[\s*project\s*\]', re.MULTILINE)

# The product languages the hooks know product checks for. A project may name
# others (e.g. "rust"); they get no product checks until a profile exists.
# paradox is a Paradox game mod (CK3, Victoria 3, Stellaris, ...): declared,
# never detected, with the game named by the paradox-game setting.
KNOWN_LANGUAGES = ("python", "c-cpp", "csharp", "javascript", "typescript", "paradox")
DEFAULT_LANGUAGES = ["python"]


class ConfigError(Exception):
    """A config file exists but could not be read."""


class NoTomlParser(ConfigError):
    """This Python has no TOML parser (before 3.11, without tomli installed).

    An environment gap, not a broken file: callers warn and carry on without
    the project's settings, as sync-versions.py always has, instead of
    refusing every commit and push on such a machine.
    """


def _has_table(pyproject):
    """True when this pyproject.toml declares [tool.repokit-common].

    Decided from the text, so discovery works on a Python with no TOML parser;
    the chosen file is parsed later.
    """
    try:
        return bool(_TABLE_HEADER.search(pyproject.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


# Repository-location environment variables (the set `git rev-parse
# --local-env-vars` reports). git EXPORTS these to hook subprocesses
# (pre-push, post-checkout, ...), so any of our git calls running under a
# hook would silently address the HOOK'S repository instead of the one we
# name with `-C`: with GIT_DIR set, `rev-parse --show-toplevel` reports the
# cwd as toplevel (defeating own-toplevel guards) and write commands like
# `subtree add` mutate the wrong repo. We always address repos explicitly,
# so these must never be inherited. Author/committer/ssh/askpass vars are
# deliberately NOT stripped.
#
# Copied from dazzlecmd-lib (dazzlecmd_lib/mode.py, dazzlecmd bd01d4d,
# v0.9.30). Here it keeps a pre-commit hook in a git worktree -- where git
# exports GIT_DIR -- from taking the vendored copy for the project and
# reading the copy's own settings instead of the project's (0.4.2).
_GIT_REPO_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_INTERNAL_SUPER_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_GRAFT_FILE",
    "GIT_NAMESPACE",
    "GIT_QUARANTINE_PATH",
)


def sanitized_git_env():
    """A copy of the environment safe for spawning git against an EXPLICIT repo.

    Strips the repo-location variables above so a git subprocess resolves the
    repository from its ``-C``/``cwd`` argument -- never from ambient hook
    state. Pass as ``env=`` to every git ``subprocess`` call.
    """
    env = dict(os.environ)
    for var in _GIT_REPO_LOCATION_VARS:
        env.pop(var, None)
    return env


def _git(start, *args):
    try:
        r = subprocess.run(["git", "-C", str(start), "rev-parse", *args],
                           capture_output=True, text=True, env=sanitized_git_env())
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _project_bound(start):
    """Where the project ends, asked from the tool's own directory.

    When repokit-common is its own repository (a submodule, or a clone of it)
    its directory is that repository's root, and the project is the
    superproject when there is one. When it is a subtree or a copy inside a
    project, the project is the repository that contains it -- even if that
    repository is itself a submodule of something larger, whose settings
    belong to a different project.
    """
    top = _git(start, "--show-toplevel")
    if not top:
        return None
    top = Path(top).resolve()
    if top == Path(start).resolve():
        sup = _git(start, "--show-superproject-working-tree")
        if sup:
            return Path(sup).resolve()
    return top


def _is_repokit_common_copy(d):
    """True when ``d`` holds repokit-common itself (its tools and VERSION)."""
    return all((d / name).is_file() for name in ("repokit_config.py", "sync-versions.py", "VERSION"))


def find_config(start):
    """Return the config file for the project containing ``start``, or None.

    repokit-common configures its own versioning in a ``.repokit-common.toml``
    at its root. That file travels with every vendored copy (a subtree, a
    submodule, a plain copy), where it is NOT the consumer's settings: it is
    honoured only when repokit-common is the project itself, i.e. its
    directory is the repository root. Anywhere else the walk steps over it.
    """
    start = Path(start).resolve()
    bound = ...  # not asked yet: git is only consulted at a .git marker
    for d in (start, *start.parents):
        py = d / "pyproject.toml"
        if py.is_file() and _has_table(py):
            return py
        alt = d / FALLBACK_NAME
        if alt.is_file():
            if not _is_repokit_common_copy(d):
                return alt
            if bound is ...:
                bound = _project_bound(start)
            if bound is None or d == bound:
                return alt
            # a vendored copy's own file: not this project's settings
        if (d / ".git").exists():
            if bound is ...:
                bound = _project_bound(start)
            # A .git marker git will not explain is treated as the boundary.
            if bound is None or d == bound:
                return None
    return None


def _load_toml(path):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            raise NoTomlParser(
                f"{path} needs a TOML parser: use Python 3.11+ or install tomli") from None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from None


def table_of(data, path):
    """The [tool.repokit-common] table in ``data``, parsed from ``path``
    (a dict; empty when absent).

    Both files use the table, so a TOML file always says what its keys are
    for and can hold other tables too. In the fallback file a key outside any
    table cannot be meant for anything else, so it is refused: before 0.3.5 a
    fallback file written without the header was found and then read as
    empty, with no warning.
    """
    tool = data.get("tool", {})
    table = tool.get(TABLE, {}) if isinstance(tool, dict) else {}
    table = table if isinstance(table, dict) else {}
    if Path(path).name == FALLBACK_NAME:
        loose = sorted(k for k, v in data.items() if not isinstance(v, dict))
        if loose:
            raise ConfigError(
                f"{path}: {', '.join(loose)} outside any table; repokit-common "
                f"settings go under a [tool.{TABLE}] header")
    return table


def read_table(path):
    """The settings from ``path``: see table_of."""
    return table_of(_load_toml(path), path)


def load(start):
    """(config path or None, table dict) for the project containing ``start``."""
    path = find_config(start)
    return (path, read_table(path)) if path else (None, {})


def project_root(start, config_path=None):
    """Where the product lives: the config file's directory when there is one,
    else the repository root (asked of git from ``start``), else ``start``."""
    if config_path is not None:
        return Path(config_path).resolve().parent
    return _project_bound(start) or Path(start).resolve()


def detect_languages(root):
    """The product languages a project's root markers show, in a fixed order.

    Root markers only: the vendored Python tooling under scripts/ must not make
    a C project read as Python, and a pyproject.toml that holds only the
    [tool.repokit-common] table is not a Python package.
    """
    root = Path(root)
    found = []
    py = root / "pyproject.toml"
    if ((py.is_file() and _PROJECT_HEADER.search(py.read_text(encoding="utf-8", errors="replace")))
            or (root / "setup.py").is_file() or (root / "setup.cfg").is_file()):
        found.append("python")
    if ((root / "CMakeLists.txt").is_file() or (root / "vcpkg.json").is_file()
            or (root / "meson.build").is_file() or any(root.glob("*.vcxproj"))):
        found.append("c-cpp")
    if any(root.glob("*.csproj")) or any(root.glob("*/*.csproj")):
        found.append("csharp")
    if (root / "tsconfig.json").is_file():
        found.append("typescript")
    elif (root / "package.json").is_file():
        found.append("javascript")
    return found


def languages(table, root):
    """The product languages: the ``languages`` setting, else detection from
    the root markers, else Python -- so a project that sets nothing and shows
    nothing behaves exactly as before the setting existed."""
    value = table.get("languages")
    if value is None:
        return detect_languages(root) or list(DEFAULT_LANGUAGES)
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(
            "languages must be a list of names, e.g. languages = [\"python\"] "
            f"(known: {', '.join(KNOWN_LANGUAGES)})")
    return list(value)


def check_commands(table):
    """The ``check-command`` table: {language: command}, empty when unset.

    A language's command replaces that language's own check step in the
    pre-push (python's default is the syntax check); an empty command turns
    the step off; a language with no default step gets one. Written as

        [tool.repokit-common.check-command]
        python = "ruff check ."
    """
    value = table.get("check-command")
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ConfigError(
            "check-command must be a table of commands per language, e.g. "
            "[tool.repokit-common.check-command] with python = \"ruff check .\"")
    return dict(value)


def _as_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v) for v in value)
    return str(value)


def _var_name(key):
    return "REPOKIT_" + re.sub(r"[^A-Za-z0-9]", "_", key).upper()


def _set_up_streams():
    """stdout is read by the hooks, not by a person: always UTF-8 with LF.

    git hands the hooks staged paths as UTF-8 bytes, so a non-ASCII pattern or
    command must arrive in UTF-8 whatever the console code page is (on
    Windows a pipe defaults to cp1252, which cannot encode e.g. a check mark
    and used to crash the call). stderr is read by a person: it keeps the
    console's encoding but can never crash on a character it cannot show.
    """
    for stream, kwargs in ((sys.stdout, {"encoding": "utf-8", "newline": "\n"}),
                           (sys.stderr, {"errors": "backslashreplace"})):
        try:
            stream.reconfigure(**kwargs)
        except (AttributeError, ValueError):
            pass  # not a text stream we can reconfigure (e.g. replaced by a test)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read repokit-common settings for the project.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--get", metavar="KEY")
    g.add_argument("--shell", metavar="KEY", nargs="+")
    g.add_argument("--where", action="store_true")
    ap.add_argument("--start", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args(argv)
    _set_up_streams()

    if args.where:
        path = find_config(args.start)
        if path:
            print(path)
        return 0
    try:
        path, table = load(args.start)
    except NoTomlParser as e:
        print(f"repokit-common: warning: {e}; the project's settings are skipped", file=sys.stderr)
        path, table = None, {}
    except ConfigError as e:
        print(f"repokit-common: {e}", file=sys.stderr)
        return 2

    def value_of(key):
        # `languages` always has a value: the setting, detection, or Python.
        if key == "languages":
            return _as_text(languages(table, project_root(args.start, path)))
        if key == "check-command":
            # One "language<TAB>command" line each; the hooks use --shell.
            commands = check_commands(table)
            return "\n".join(f"{k}\t{v}" for k, v in commands.items()) if commands else None
        return _as_text(table[key]) if key in table else None

    try:
        if args.get:
            value = value_of(args.get)
            if value is not None:
                print(value)
            return 0
        for key in args.shell:
            if key == "check-command":
                # REPOKIT_CHECK_COMMAND names the languages that have one, and
                # REPOKIT_CHECK_COMMAND_<LANGUAGE> holds each command (set,
                # possibly empty, only for a language the table names).
                commands = check_commands(table)
                print(f"{_var_name(key)}={shlex.quote(' '.join(commands))}")
                for lang, command in commands.items():
                    print(f"{_var_name(key + '-' + lang)}={shlex.quote(command)}")
                continue
            value = value_of(key)
            print(f"{_var_name(key)}={shlex.quote(value if value is not None else '')}")
    except ConfigError as e:
        print(f"repokit-common: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
