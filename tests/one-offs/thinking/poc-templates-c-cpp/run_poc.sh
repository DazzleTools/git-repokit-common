#!/usr/bin/env bash
# Run the POC arms. Usage: run_poc.sh <scratch-dir> [arm ...]   (arms: a1 a2 a3 a4 a5 a6 a7 a8; default all)
# Everything is written under <scratch-dir>; nothing else is touched.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$1"; shift
ARMS="${*:-a1 a2 a3 a4 a5 a6 a7 a8}"
T="$HERE/templates"
VS="/c/Program Files/Microsoft Visual Studio/2022/Community"
CMAKE="$VS/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
CTEST="$VS/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/ctest.exe"
MSBUILD="$VS/MSBuild/Current/Bin/MSBuild.exe"
export VCPKG_ROOT="$(cygpath -w "$VS/VC/vcpkg")"
mkdir -p "$S"
verdict() { printf '%-4s %-9s %s\n' "$1" "$2" "$3" | tee -a "$S/verdicts.txt"; }

for arm in $ARMS; do case "$arm" in

a1)
    D="$S/a1"; rm -rf "$D"
    python "$HERE/assemble.py" "$T" c-cpp/cmake-app my-tool "$D/proj" >/dev/null
    python "$HERE/assemble.py" "$T" c-cpp/cmake-app my-tool "$D/control" --no-substitute >/dev/null
    left=$(grep -rIl "__RK_[A-Z_]*__" "$D/proj" | wc -l)
    left_paths=$(find "$D/proj" -name "*__RK_*" | wc -l)
    ctl=$(grep -rIl "__RK_[A-Z_]*__" "$D/control" | wc -l)
    paths_ok=0
    for p in include/my_tool/version.h CMakeLists.txt src/app.rc .repokit-common.toml vcpkg.json; do [ -f "$D/proj/$p" ] || paths_ok=1; done
    grep -q 'project(my-tool' "$D/proj/CMakeLists.txt" || paths_ok=1
    grep -q '#define MY_TOOL_VERSION_MAJOR 0' "$D/proj/include/my_tool/version.h" || paths_ok=1
    grep -q 'version-source = "include/my_tool/version.h"' "$D/proj/.repokit-common.toml" || paths_ok=1
    grep -q 'vcpkg.json' "$D/proj/.repokit-common.toml" || paths_ok=1
    grep -q 'vcpkg_installed/' "$D/proj/.gitignore" || paths_ok=1
    wf_same=$(cmp -s "$T/archetypes/c-cpp/cmake-app/.github/workflows/ci.yml" "$D/proj/.github/workflows/ci.yml" && echo yes || echo no)
    echo "a1: tokens-left files=$left paths=$left_paths; names/layers ok=$([ $paths_ok = 0 ] && echo yes || echo no); workflow identical=$wf_same; control tokens files=$ctl"
    if [ "$ctl" -eq 0 ]; then verdict A1 method-broken "control had no tokens"
    elif [ "$left" -eq 0 ] && [ "$left_paths" -eq 0 ] && [ $paths_ok = 0 ] && [ "$wf_same" = yes ]; then verdict A1 survived "0 tokens left, names right, layers appended, workflow byte-identical; control kept tokens in $ctl files"
    else verdict A1 refuted "tokens=$left/$left_paths names-ok=$paths_ok workflow=$wf_same"; fi
    ;;

a2)
    D="$S/a2"; rm -rf "$D"
    python "$HERE/assemble.py" "$T" c-cpp/cmake-app my-tool "$D/proj" >/dev/null
    ( cd "$D/proj" && git init -q && git -c user.email=p@e.invalid -c user.name=p -c commit.gpgsign=false add -A && \
      git -c user.email=p@e.invalid -c user.name=p -c commit.gpgsign=false commit -q -m init )
    ( cd "$D/proj" && "$CMAKE" --preset windows-release ) > "$D/configure.txt" 2>&1; c=$?
    ( cd "$D/proj" && "$CMAKE" --build --preset windows-release ) > "$D/build.txt" 2>&1; b=$?
    ( cd "$D/proj" && "$CTEST" --preset windows-release ) > "$D/ctest.txt" 2>&1; t=$?
    # Control: a test that must fail.
    cp -r "$D/proj" "$D/control"; rm -rf "$D/control/build"
    sed -i 's/return 0;$/return 7;/' "$D/control/tests/test_version.cpp"
    ( cd "$D/control" && "$CMAKE" --preset windows-release && "$CMAKE" --build --preset windows-release ) > "$D/control-build.txt" 2>&1
    ( cd "$D/control" && "$CTEST" --preset windows-release ) > "$D/control-ctest.txt" 2>&1; ct=$?
    echo "a2: configure=$c build=$b ctest=$t; control ctest=$ct; $(grep -m1 'my-tool version' "$D/configure.txt")"
    if [ $ct -eq 0 ]; then verdict A2 method-broken "control test passed"
    elif [ $c -eq 0 ] && [ $b -eq 0 ] && [ $t -eq 0 ]; then verdict A2 survived "configure+build+ctest pass with VS 2022 CMake and the vcpkg toolchain; control ctest exit $ct"
    else verdict A2 refuted "configure=$c build=$b ctest=$t (see $D/*.txt)"; fi
    ;;

a3)
    D="$S/a3"; rm -rf "$D"; mkdir -p "$D"
    python "$HERE/assemble.py" "$T" c-cpp/msbuild my-tool "$D/msb" >/dev/null
    "$MSBUILD" "$(cygpath -w "$D/msb/my-tool.sln")" -nologo -v:minimal -p:Configuration=Release -p:Platform=x64 > "$D/msbuild.txt" 2>&1; m=$?
    msb_ver=$("$D/msb/x64/Release/my-tool.exe" --version 2>&1)
    python "$HERE/assemble.py" "$T" c-cpp/minimal my-tool "$D/min" >/dev/null
    # .\ because this shell sets NoDefaultCurrentDirectoryInExePath=1; \\ because printf reads \b as backspace.
    printf '@call "%s" >nul\r\n@cd /d "%s"\r\n@call .\\build.bat\r\n' "$(cygpath -w "$VS/VC/Auxiliary/Build/vcvars64.bat")" "$(cygpath -w "$D/min")" > "$D/run_min.cmd"
    cmd.exe //c "$(cygpath -w "$D/run_min.cmd")" > "$D/minimal.txt" 2>&1; n=$?
    min_ver=$("$D/min/build/my-tool.exe" --version 2>&1)
    # Control: a syntax error must fail the minimal build.
    cp -r "$D/min" "$D/min-control"; rm -rf "$D/min-control/build"
    printf 'int broken(\n' >> "$D/min-control/src/my_tool.c"
    printf '@call "%s" >nul\r\n@cd /d "%s"\r\n@call .\\build.bat\r\n' "$(cygpath -w "$VS/VC/Auxiliary/Build/vcvars64.bat")" "$(cygpath -w "$D/min-control")" > "$D/run_ctl.cmd"
    cmd.exe //c "$(cygpath -w "$D/run_ctl.cmd")" > "$D/min-control.txt" 2>&1; nc=$?
    echo "a3: msbuild=$m ($msb_ver); minimal=$n ($min_ver); control=$nc"
    if [ $nc -eq 0 ]; then verdict A3 method-broken "control built"
    elif [ $m -eq 0 ] && [ $n -eq 0 ] && [ -n "$msb_ver" ] && [ -n "$min_ver" ]; then verdict A3 survived "MSBuild and cl builds run; control exit $nc"
    else verdict A3 refuted "msbuild=$m minimal=$n (see $D/*.txt)"; fi
    ;;

a4)
    # Copies drop build/ (a CMake cache only works in the folder that made it); logs stay outside the repo.
    D="$S/a4"; rm -rf "$D"; cp -r "$S/a2/proj" "$D"; rm -rf "$D/build"
    old_exe="$S/a4-old.exe"; cp "$S/a2/proj/build/Release/my-tool.exe" "$old_exe"
    before=$(cat "$D/include/my_tool/version.h")
    new=$(python "$HERE/version_c.py" bump "$D/include/my_tool/version.h" MY_TOOL patch)
    changed=$(diff <(echo "$before") "$D/include/my_tool/version.h" | grep -c '^[<>]')
    ( cd "$D" && "$CMAKE" --preset windows-release && "$CMAKE" --build --preset windows-release ) > "$S/a4-rebuild.txt" 2>&1; rb=$?
    cmake_v=$(grep -o 'my-tool version [0-9.]*' "$S/a4-rebuild.txt" | head -1 | awk '{print $3}')
    exe_v=$("$D/build/Release/my-tool.exe" --version | awk '{print $2}')
    vi_v=$(powershell.exe -NoProfile -Command "(Get-Item '$(cygpath -w "$D/build/Release/my-tool.exe")').VersionInfo.FileVersion" | tr -d '\r')
    old_v=$("$old_exe" --version | awk '{print $2}')
    echo "a4: new=$new header-lines-changed=$changed rebuild=$rb cmake=$cmake_v exe=$exe_v versioninfo=$vi_v; control old exe=$old_v"
    if [ "$old_v" = "$new" ]; then verdict A4 method-broken "old exe already reports the new version"
    elif [ $rb -eq 0 ] && [ "$cmake_v" = "$new" ] && [ "$exe_v" = "$new" ] && [ "$vi_v" = "$new" ] && [ "$changed" -eq 4 ]; then verdict A4 survived "one header edit (2 lines) -> CMake, --version and VERSIONINFO all $new; old exe still $old_v"
    else verdict A4 refuted "cmake=$cmake_v exe=$exe_v vi=$vi_v changed=$changed"; fi
    ;;

a6)
    D="$S/a6"; rm -rf "$D"; cp -r "$S/a2/proj" "$D"; rm -rf "$D/build"
    ( cd "$D" && echo "change" >> README.md && git -c user.email=p@e.invalid -c user.name=p -c commit.gpgsign=false commit -qam "second" )
    ( cd "$D" && "$CMAKE" --preset windows-release && "$CMAKE" --build --preset windows-release ) > "$S/a6-build.txt" 2>&1; b=$?
    out=$("$D/build/Release/my-tool.exe" --version); head=$(git -C "$D" rev-parse --short HEAD); dirty=$(git -C "$D" status --porcelain | wc -l)
    # Control: no .git -> stamp says unknown, build still succeeds.
    cp -r "$D" "$D-nogit"; rm -rf "$D-nogit/.git" "$D-nogit/build"
    ( cd "$D-nogit" && "$CMAKE" --preset windows-release && "$CMAKE" --build --preset windows-release ) > "$D-nogit.txt" 2>&1; cb=$?
    cout=$("$D-nogit/build/Release/my-tool.exe" --version 2>&1)
    echo "a6: build=$b out='$out' head=$head dirty=$dirty; control build=$cb out='$cout'"
    if echo "$out" | grep -Eq "\(0\.1\.0_main_2-[0-9]{8}-$head\)" && [ $b -eq 0 ] && [ "$dirty" -eq 0 ] && [ $cb -eq 0 ] && echo "$cout" | grep -q unknown; then
        verdict A6 survived "stamp carries HEAD $head and build count 2, tree clean; without .git the build passes with 'unknown'"
    else verdict A6 refuted "out=$out dirty=$dirty control=$cb/$cout"; fi
    ;;

a8)
    # Fork adoption with versioning off. The setting is prototyped by patching
    # ONLY the scratch copy's vendored hooks; repokit-common itself is not touched.
    SRC_FORK="$(dirname "$S")/cpp-survey/ttyd-msvc"
    RKC="$(cd "$HERE/../../../.." && pwd)"
    for mode in off control; do
        D="$S/a8-$mode"; rm -rf "$D"
        git clone -q --no-hardlinks "$SRC_FORK" "$D" 2>/dev/null
        ( cd "$D" && git checkout -q -B main && git config user.email p@e.invalid && git config user.name p && git config commit.gpgsign false
          mkdir -p scripts/repokit-common
          for f in sync-versions.py repokit_config.py install-hooks.sh update-version.sh paths.sh conftest.py VERSION .gitignore; do cp "$RKC/$f" scripts/repokit-common/ 2>/dev/null; done
          cp -r "$RKC/hooks" scripts/repokit-common/hooks
          if [ "$mode" = off ]; then
              sed -i 's/^rk_read_settings private-patterns output version-source /rk_read_settings private-patterns output version-source versioning /' scripts/repokit-common/hooks/pre-commit
              sed -i 's/^if \[ -n "\$SYNC_SCRIPT" \] \&\& command -v python/if [ "${REPOKIT_VERSIONING:-on}" = off ]; then :\nelif [ -n "$SYNC_SCRIPT" ] \&\& command -v python/' scripts/repokit-common/hooks/pre-commit
              sed -i 's/^rk_read_settings output || true/rk_read_settings output versioning || true/' scripts/repokit-common/hooks/post-commit
              sed -i 's/^if \[ -n "\$SYNC_SCRIPT" \] \&\& command -v python/if [ "${REPOKIT_VERSIONING:-on}" = off ]; then exit 0\nelif [ -n "$SYNC_SCRIPT" ] \&\& command -v python/' scripts/repokit-common/hooks/post-commit
              printf '[tool.repokit-common]\nversioning = "off"\nlanguages = ["c-cpp"]\n' > .repokit-common.toml
          fi
          git add -A && git commit -q --no-verify -m "adopt repokit-common (probe)"
          bash scripts/repokit-common/install-hooks.sh >/dev/null 2>&1
          echo "// probe" >> README.md && git add README.md
          git commit -m "probe: ordinary commit" ) > "$S/a8-$mode.txt" 2>&1
    done
    # cat, not grep over two files: grep would print "path:count" and Windows paths hold a colon.
    patched=$(cat "$S/a8-off/scripts/repokit-common/hooks/pre-commit" "$S/a8-off/scripts/repokit-common/hooks/post-commit" | grep -c 'REPOKIT_VERSIONING')
    w_off=$(grep -cE "Version update failed|version hash not updated" "$S/a8-off.txt")
    w_ctl=$(grep -cE "Version update failed|version hash not updated" "$S/a8-control.txt")
    touched=$(git -C "$S/a8-off" diff --name-only HEAD~2 HEAD~1 | grep -vE '^scripts/repokit-common/|^\.repokit-common\.toml$' | wc -l)
    echo "a8: patch lines=$patched warnings with off=$w_off, control=$w_ctl; adoption touched $touched file(s) outside scripts/repokit-common and the settings file"
    if [ "$w_ctl" -lt 2 ]; then verdict A8 method-broken "control showed $w_ctl warnings"
    elif [ "$patched" -ge 2 ] && [ "$w_off" -eq 0 ] && [ "$touched" -eq 0 ]; then verdict A8 survived "versioning off: 0 version warnings (control $w_ctl); adoption adds only the vendored copy and .repokit-common.toml"
    else verdict A8 refuted "patched=$patched off=$w_off touched=$touched"; fi
    ;;

a7)
    out=""; rc_all=""
    for st in c-cpp/cmake-lib c-cpp/qt python/qt; do
        D="$S/a7-$(echo $st | tr / -)"; rm -rf "$D"
        msg=$(python "$HERE/assemble.py" "$T" "$st" my-tool "$D" 2>&1); rc=$?
        rc_all="$rc_all $rc"; out="$out | $st: $msg"
        [ -e "$D" ] && rc_all="$rc_all(wrote!)"
    done
    echo "a7:$out"
    if [ "$rc_all" = " 3 3 3" ]; then verdict A7 survived "all three stubs exit 3, say 'stub', write nothing"
    else verdict A7 refuted "exit codes:$rc_all"; fi
    ;;

*) echo "arm $arm not in this run" ;;
esac; done
