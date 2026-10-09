#!/usr/bin/env bash
# What does a fork see today when it adopts repokit-common with no version
# source? (read-only for every real repository)
#
# Usage: fork_adoption_probe.sh <source-clone> <scratch-dir> <repokit-common-dir>
#   source-clone       an existing clone of the fork (only read; copied)
#   scratch-dir        a new folder to work in (created; must not exist)
#   repokit-common-dir this checkout of git-repokit-common (files copied in)
#
# Steps, all inside scratch-dir: copy the fork, vendor repokit-common at
# scripts/repokit-common (plain copy, as a subtree would), commit that,
# install the hooks, make one ordinary commit, push it to a local bare
# remote. Every hook message is printed. Nothing outside scratch-dir is
# written; no remote other than the local bare one is touched.
set -u
SRC="$1"; WORK="$2"; RKC="$3"
[ -e "$WORK" ] && { echo "refusing: $WORK exists"; exit 2; }
mkdir -p "$WORK"
git clone -q --no-hardlinks "$SRC" "$WORK/fork" || exit 2
git init -q --bare "$WORK/remote.git"
cd "$WORK/fork" || exit 2
git remote remove origin 2>/dev/null
git remote add origin "$WORK/remote.git"
git config user.email probe@example.invalid
git config user.name probe
git config commit.gpgsign false
git checkout -q -B main

mkdir -p scripts/repokit-common
# The files a vendored copy carries (tests and private vault excluded).
for f in sync-versions.py repokit_config.py install-hooks.sh update-version.sh paths.sh conftest.py VERSION; do
    [ -f "$RKC/$f" ] && cp "$RKC/$f" scripts/repokit-common/
done
cp -r "$RKC/hooks" scripts/repokit-common/hooks
git add scripts/repokit-common
git commit -q --no-verify -m "vendor repokit-common (probe)"
echo "=== install-hooks.sh"
bash scripts/repokit-common/install-hooks.sh 2>&1 | tail -4
echo "=== first push (main) before any change"
git push -q origin main 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
echo "=== ordinary commit"
echo "// probe" >> README.md
git add README.md
git commit -m "probe: ordinary commit" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
echo "=== status after commit"
git status --short
echo "=== push"
git push origin main 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
echo "=== files changed outside scripts/repokit-common vs the fork's tip"
git diff --stat HEAD~2 HEAD -- . ':!scripts/repokit-common'
