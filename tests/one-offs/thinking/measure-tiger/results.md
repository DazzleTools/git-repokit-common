# Measure: the real ck3-tiger, and the 0.4.3 hooks end to end (2026-10-30)

## Question

How must the pre-push hook call Tiger, and what does its exit code mean? The paradox profile had been written against a stub that accepted any argument.

The decisions that depend on it: the hook's argument for each game, `--no-color`, and how a non-zero exit is reported.

## Method

- **The tool:** `ck3-tiger` v1.19.0, the official Windows release from github.com/amtep/tiger.
  - The zip's sha256 (`ddafd73a...0505`) matches GitHub's asset digest.
  - It is unpacked at `C:\code-ext\tiger\ck3-tiger-v1.19.0\`.
- **The mod:** DaddyPika's Cheat Menu (`C:\code\ck3\daddy-pikas-cheat-menu__original`), copied to a temp folder first. Tiger reads only the copy.
- **The game:** the CK3 1.20.1.2 install, read by Tiger.
- **`probe.py`:** four calls: the descriptor file; the folder; a clean minimal mod, as the known answer ("No problems found"); and `--no-color`.
- **`e2e_push.py`:** real pushes through this checkout's hooks, installed by `install-hooks.sh`, into three throwaway repositories under a temp folder.

## Results (`results-raw.txt`, `results-e2e.txt`)

| Question | Measured |
|---|---|
| What does `ck3-tiger` take? | `--help`: "Path to .mod file of mod to check". v1.19 also accepts the folder; the hook passes the file, as documented. vic3-tiger takes the folder (README). |
| Exit code with findings | **0**, with 55 fatal, 346 errors and 501 warnings. |
| Exit code when it cannot run | **1** (a path that does not exist). |
| Exit code, clean mod | 0, "No problems found." |
| Colour into a pipe | **yes**, escape codes, unless `--no-color` is passed. |
| Output size, real mod | 4,728 lines (`--consolidate`: 4,613). |
| Where the summary is | the last line: `fatal: 55, error: 346, warning: 501, untidy: 0, tips: 2`. |
| Finding the game | by itself, through Steam. No `--game` is needed. |
| Version banner | "PLEASE UPDATE!": Tiger 1.19 was built for CK3 1.19.0, and the game is 1.20.1.2. |

## Verdict: what changed in the hook

- **The argument:** the descriptor file for ck3 and imperator, the folder for vic3.
- **Colour:** `--no-color` when the hook's output is plain.
- **The report:** written to `.git/repokit-<linter>.txt` (never committed). The push shows the summary line, the version note, and the report's path.
- **A non-zero exit** means "Tiger could not run, the mod was not linted". It never means findings. Both are advisory.
- **The test stub** now behaves as measured: it refuses a folder where ck3 takes the file, ends with a summary line, exits 0 whatever it found, and exits 1 only when it cannot run.

## End to end (`results-e2e.txt`)

1. **The CK3 mod, with the real Tiger:**
   - push accepted; Tiger's summary and the version note shown;
   - the broken tooling `.py` not checked;
   - the commit hook's pattern target rewrote exactly one descriptor line (`version="1.3.0"` -> `version="0.2.0"`), with no BOM and LF before and after.
2. **A localization `.yml` re-saved without its BOM:** the commit was blocked, naming the file.
3. **A project that sets nothing:** the Python syntax check still blocked a broken script.
4. **`languages = ["typescript", "python"]`** (the claude-bookmarks shape): the TypeScript check-command, then the Python syntax check, then pytest.

## A finding for the CK3 port

DaddyPika's mod has 55 crash-level problems against current CK3, for example: "`event_background` now causes a crash. It has been replaced by `reference` since 1.9". That is the start of a worklist for the 1.20 port. Tiger's own version is one behind the game, so some reports may be wrong.
