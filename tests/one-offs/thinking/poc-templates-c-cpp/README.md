# POC: one templates repo + a local assembler, proven on C/C++

Question ("How many repokit templates?"): can ONE templates repo -- `base/` plus
`languages/<lang>/` plus `archetypes/<lang>/<name>/` -- and a local assembler
produce working projects, instead of one GitHub template repo per language?

Designs: `2026-10-05__23-24-14__dev-workflow-process__template-family-home-and-composition.md`
and `2026-10-05__23-41-54__dev-workflow-process__c-cpp-template-first.md` (project vault).

Layout here:

- `templates/` -- stands in for the one templates repo
- `assemble.py` -- the local assembler (`/create-project` would call it)
- `version_c.py` -- prototype version reader/writer for `VERSION`, C headers and `.rc` files
- `run_poc.sh` -- runs every arm into a scratch folder given as its argument

Nothing here is production code; the arms decide whether the design is built properly.

## Arms (written before running)

| Arm | Prediction | Pass criterion | Control (predicted to FAIL) | Fallback if refuted |
|---|---|---|---|---|
| A1 placeholders (C5/T7) | `my-tool` assembles to target `my-tool`, macro prefix `MY_TOOL_`, header `include/my_tool/version.h`, `.repokit-common.toml` naming that header; no `__RK_` token left anywhere; every `.github/workflows/*` byte-identical to its source | grep finds 0 tokens; paths exist; SHA-256 of workflows equal | copy the layers with no substitution: tokens remain (>0 found) | per-language templates repos (option 1) or Copier |
| A2 cmake-app builds (C1) | VS 2022 CMake configures with the vcpkg toolchain (manifest, no deps), builds Release, `ctest` passes | exit 0 for configure, build, ctest | inject a failing assert into the test: `ctest` exits non-zero | document a vcpkg-free preset |
| A3 msbuild + minimal build (C6) | MSBuild builds the generated `.sln` (x64 Release); `cl` builds the minimal `.c` | exit 0, executables exist | a syntax error in the minimal source: `cl` exits non-zero | drop that archetype to a stub |
| A4 one version source (C2/C10) | after `version_c.py bump patch` on `version.h`, the header's component lines change and nothing else; CMake's configured version, the exe's `--version`, and the exe's VERSIONINFO (`(Get-Item).VersionInfo.FileVersion`) all report the bumped version | three readings equal the new version; diff touches only `#define` component/string lines | bump the header but run the OLD exe: readings disagree (detected) | generate a `version.rc2` instead of including the header |
| A5 encodings (C4) | editing a UTF-8-BOM + CRLF header and a Windows-1252 `.rc` containing 0xA9 changes only the version bytes: BOM kept, CRLF kept, 0xA9 count unchanged | byte compare outside the edited lines equal; 0xA9 count equal | the same edit through `read_text()`/`write_text()` with UTF-8: 0xA9 count drops (corruption detected) | bytes-level edit only, per target encoding |
| A6 build-time stamp (C3) | in a git repo, after commit + build, `git status` is clean and `--version` prints `<ver>_<branch>_<count>-<date>-<shorthash>` with HEAD's hash | regex match and hash equal HEAD; status empty | build from a copy without `.git`: stamp says `unknown` (and does not fail the build) | stamp committed by hooks (S1) |
| A7 stubs (C9) | assembling `cmake-lib`, `qt` or `python/qt` writes nothing and says it is a stub | exit code 3, message contains "stub", target folder absent | -- | -- |
| A8 fork adoption (C11) | with `versioning = "off"` honoured (prototype patch in the scratch copy's vendored hooks only), a commit prints no version warning | 0 lines matching "Version update failed" / "version hash not updated" | the same commit without the setting: both warnings appear | an adoption-only hook variant |

Verdict words: survived / refuted / inconclusive / method-broken (a control that passes voids its arm).

## Results (2026-10-07, final runs)

Run: `bash run_poc.sh <scratch> a1 a2 a3 a4 a6 a7 a8` and `python a5_check.py <scratch>/a5` (Windows 11, VS 2022 Community: CMake 3.30.5-msvc23, MSBuild 17.13, MSVC 14.43, VS-bundled vcpkg).

| Arm | Verdict | Observed |
|---|---|---|
| A1 | survived | 0 `__RK_` tokens left in files or paths; `my-tool` / `MY_TOOL_` / `include/my_tool/version.h`; `.gitignore` and `.repokit-common.toml` appends applied; `ci.yml` byte-identical. Control (no substitution): tokens in 9 files |
| A2 | survived | `cmake --preset windows-release` (vcpkg manifest mode ran), build, `ctest` all exit 0; CMake printed `my-tool version 0.1.0` read from the header. Control (failing test): `ctest` exit 8 |
| A3 | survived | MSBuild built the generated `.sln` (`my-tool 0.1.0`); `build.bat` built the minimal C file with `rc` + `cl` (`my-tool 0.1.0`). Control (syntax error): exit 1 |
| A4 | survived | `version_c.py bump patch` changed 2 header lines; CMake, `--version` and `VersionInfo.FileVersion` all `0.1.1`. Control: the pre-bump exe still `0.1.0` |
| A5 | survived | header: BOM kept, 9/9 CRLF kept, only lines 5 and 7 changed; cp1252 `.rc`: 0xA9 count 1 -> 1, other lines identical. Control (naive UTF-8 round trip): raw 0xA9 gone, U+FFFD present |
| A6 | survived | `--version` -> `0.1.0_main_2-20261007-f169d79` = HEAD, tree clean. Control (no `.git`): build passes, stamp `unknown` |
| A7 | survived | `c-cpp/cmake-lib`, `c-cpp/qt`, `python/qt`: exit 3, "is a stub", nothing written |
| A8 | survived | `versioning = "off"` (prototype: 2 hook lines patched in the scratch copy only): 0 version warnings on commit; control without it: 2. Adoption touched no file outside `scripts/repokit-common/` and `.repokit-common.toml` |

`verdicts.txt` in the scratch folder keeps every run in order, including the method failures below; the table above is the final run of each arm.

### Method failures caught and fixed (not findings about the design)

- A5's first report printed `bom=False`, `0xA9 0->0`: the detail strings used `b'\\xa9'` (literal text) while the pass conditions used real bytes. Fixed to shared byte constants; re-run, and checked independently with `od` and `grep`.
- A3: `build.bat` "is not recognized" because this shell sets `NoDefaultCurrentDirectoryInExePath=1`; the wrapper now calls `.\build.bat` (and escapes `\\` because `printf` reads `\b` as backspace). `vcvars64.bat` also prints "'vswhere.exe' is not recognized" on this machine (no VS Installer `vswhere`); harmless.
- A4/A6: copies carried A2's `build/` (a CMake cache is bound to its folder) and A6 wrote its log inside the repo (a false "dirty"). Copies now drop `build/`; logs live outside.
- A8: the first count read `grep -c` over two files, which prints `path:count`; Windows paths contain `:`, so the sum was 0. Counted through `cat` instead.

### A finding about the design, fixed in the template

- **The build stamp used an outer repository.** With `.git` removed, the build still found a git repository by walking up to the repository that tracks the user's home directory and stamped `main_2164-...-59dd4d208` (that repo's identity) instead of `unknown`. `GenerateStamp.cmake` now compares `git rev-parse --show-toplevel` with the source directory and uses `unknown` unless they match. Any source tree unpacked inside another checkout would otherwise be mis-stamped.

### Not tested here (still open)

- GitHub side: CI on the 3-OS matrix, Dependabot on first push, GitHub's language detection with `linguist-vendored` (needs the throwaway repository).
- Linux/macOS builds and the Makefile (no gcc on this machine).
- Copier, and its update path for existing projects (not installed; the POC used its own ~150-line assembler).
- Mixed-language assembly (two language layers on one base).
- The real `sync-versions.py` (the POC used `version_c.py`; the readers and the header target still have to be built there).
- `git-repokit` as the assembler (djdarcy, 2026-10-07: "If we do assemble a repo we should probaly use "git-repokit in some shape or form").
