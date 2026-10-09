#!/usr/bin/env bash
# Update git-repokit-common scripts to the latest version.
#
# Usage:
#   bash scripts/update-common.sh          # pull latest from upstream
#   bash scripts/update-common.sh --check  # show current vs latest version
#   bash scripts/update-common.sh --push   # push local changes back upstream

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repository root via git (works for any subtree prefix depth)
REPO_ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel)"
# Subtree prefix: this script's folder relative to the repo root, asked of git
# itself. Stripping $REPO_ROOT from $SCRIPT_DIR fails on Windows, where git
# answers C:/... and the shell's pwd /c/... (or /tmp/...), leaving an absolute
# "prefix" that `git subtree pull` reports as never added.
PREFIX="$(cd "$SCRIPT_DIR" && git rev-parse --show-prefix)"
PREFIX="${PREFIX%/}"
REMOTE_NAME="repokit-common"
REMOTE_URL="https://github.com/DazzleTools/git-repokit-common.git"

cd "$REPO_ROOT"

# Ensure remote exists
if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
    echo "Adding remote: $REMOTE_NAME -> $REMOTE_URL"
    git remote add "$REMOTE_NAME" "$REMOTE_URL"
fi

case "${1:-pull}" in
    --check|check|--version|version|-v)
        echo "=== git-repokit-common status ==="
        echo ""
        # Show version from VERSION file if it exists
        LOCAL_VER="unknown"
        if [ -f "$SCRIPT_DIR/VERSION" ]; then
            LOCAL_VER=$(cat "$SCRIPT_DIR/VERSION" | tr -d '[:space:]')
        fi
        echo "  Local version:  $LOCAL_VER"
        # Fetch and show upstream version
        git fetch "$REMOTE_NAME" main --quiet 2>/dev/null
        UPSTREAM_VER=$(git show "$REMOTE_NAME/main:VERSION" 2>/dev/null | tr -d '[:space:]' || echo "unknown")
        echo "  Upstream version: $UPSTREAM_VER"
        # Compare commits
        LOCAL_SHA=$(git log --format="%H" --grep="Squashed '$PREFIX/'" -1 2>/dev/null)
        if [ -n "$LOCAL_SHA" ]; then
            BEHIND=$(git rev-list --count "$LOCAL_SHA".."$REMOTE_NAME/main" 2>/dev/null || echo "?")
            if [ "$BEHIND" = "0" ]; then
                echo ""
                echo "  Up to date."
            else
                echo ""
                echo "  $BEHIND commit(s) behind upstream."
                echo "  Run: bash $PREFIX/update-common.sh"
            fi
        fi
        ;;
    --push|push)
        echo "Pushing local $PREFIX/ changes to $REMOTE_NAME..."
        git subtree push --prefix="$PREFIX" "$REMOTE_NAME" main
        echo "Done."
        ;;
    pull|"")
        # `git subtree pull` refuses a dirty tree, and the pre-commit hook makes
        # most trees dirty by exactly one line: the version source's __version__
        # stamp. When that line is the only change, keep the work safe and pull:
        # save a snapshot, restore the file from HEAD, pull, then re-stamp with
        # sync-versions.py. Any other change is refused and named, and nothing
        # is touched -- a pull must never cost a user their uncommitted work.
        DIRTY="$(git status --porcelain --untracked-files=no)"
        RESTAMP=""
        if [ -n "$DIRTY" ]; then
            VSRC="$(python "$SCRIPT_DIR/repokit_config.py" --get version-source 2>/dev/null || true)"
            DIRTY_PATHS="$(printf '%s\n' "$DIRTY" | sed 's/^.. //; s/^"\(.*\)"$/\1/; s/.* -> //')"
            stamp_only() {
                # one file, one line changed, and that line is the __version__ stamp
                [ "$(git diff --numstat -- "$1" | awk '{print $1, $2}')" = "1 1" ] || return 1
                [ -z "$(git diff -U0 -- "$1" | grep '^[-+][^-+]' | grep -v '__version__')" ]
            }
            if [ -n "$VSRC" ] && [ "$DIRTY_PATHS" = "$VSRC" ] && stamp_only "$VSRC"; then
                if command -v dz >/dev/null 2>&1 && dz git-snapshot --help >/dev/null 2>&1; then
                    dz git-snapshot save "update-common: before pulling $REMOTE_NAME" >/dev/null \
                        && echo "Saved a dz git-snapshot of the tree."
                else
                    BAK="$(git rev-parse --git-dir)/repokit-common-stamp.bak"
                    cp "$VSRC" "$BAK"
                    echo "Saved a copy of $VSRC at $BAK."
                fi
                git checkout -- "$VSRC"
                RESTAMP="$VSRC"
                echo "Set aside the version stamp in $VSRC (the only change); it is restored after the pull."
            else
                echo "Refusing to pull: the working tree has changes other than the version stamp:"
                printf '%s\n' "$DIRTY" | sed 's/^/    /'
                echo "Commit or stash them, then run again. Nothing was touched."
                exit 1
            fi
        fi
        echo "Pulling latest $REMOTE_NAME into $PREFIX/..."
        git subtree pull --prefix="$PREFIX" "$REMOTE_NAME" main --squash
        if [ -n "$RESTAMP" ]; then
            python "$SCRIPT_DIR/sync-versions.py" >/dev/null && echo "Re-stamped $RESTAMP."
        fi
        echo "Done."
        ;;
    --help|-h|help)
        echo "Usage: bash $PREFIX/update-common.sh [command]"
        echo ""
        echo "Commands:"
        echo "  (none), pull    Pull latest from upstream"
        echo "  --check, -v     Show current vs upstream version"
        echo "  --push          Push local changes back upstream"
        echo "  --help          Show this help"
        ;;
    *)
        echo "Unknown option: $1"
        echo "Run: bash $PREFIX/update-common.sh --help"
        exit 1
        ;;
esac
