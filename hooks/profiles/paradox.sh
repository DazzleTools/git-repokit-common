# shellcheck shell=sh
#
# repokit-common language profile: paradox, a Paradox game mod (CK3, Victoria
# 3, Imperator, ...). Declared, never detected; the game is the paradox-game
# setting. The profile contract is described in python.sh. POSIX sh.

# check: the game's Tiger linter on the mod, advisory. A mod should be linted,
# but never held back by a tool that is not installed, or by findings in files
# it overrides from the game; a project that wants Tiger to gate sets
# check-command.paradox.
# Measured on ck3-tiger 1.19.0 (tests/one-offs/thinking/measure-tiger): it
# exits 0 whatever it finds (55 fatal and 346 errors on a real mod) and 1 when
# it cannot run (a bad path); it finds the game through Steam by itself; it
# prints colour even into a pipe; a real mod's report runs to ~4,700 lines,
# its last line the summary ("fatal: 55, error: 346, warning: 501, ..."). So
# the report goes to a file in git's directory and the push shows its summary.
rk_profile_paradox_check() {
    _rk_mod=""
    if [ -f mod/descriptor.mod ]; then _rk_mod=mod
    elif [ -f descriptor.mod ]; then _rk_mod=.
    fi
    if [ -z "$_rk_mod" ]; then
        echo "  paradox: no descriptor.mod in mod/ or at the root -- linter skipped"
        return 0
    fi
    case "${REPOKIT_PARADOX_GAME:-}" in
        # ck3-tiger and imperator-tiger take the descriptor file, vic3-tiger
        # the mod folder (Tiger's README and --help).
        ck3|imperator) _rk_tiger="${REPOKIT_PARADOX_GAME}-tiger"; _rk_target="$_rk_mod/descriptor.mod" ;;
        vic3) _rk_tiger=vic3-tiger; _rk_target="$_rk_mod" ;;
        "")
            echo "  paradox: set paradox-game (e.g. \"ck3\") to choose a linter -- linter skipped"
            return 0
            ;;
        *)
            echo "  paradox: no default linter for $REPOKIT_PARADOX_GAME -- set check-command.paradox"
            return 0
            ;;
    esac
    if ! command -v "$_rk_tiger" >/dev/null 2>&1; then
        echo "  paradox: $_rk_tiger is not on PATH -- linter skipped (install it, or set check-command.paradox)"
        return 0
    fi
    echo -e "${BLUE}Linting the mod with $_rk_tiger ($_rk_target)...${NC}"
    _rk_report="$(git rev-parse --absolute-git-dir 2>/dev/null)/repokit-$_rk_tiger.txt"
    _rk_nocolor=""
    [ "$_rk_mode" = rich ] || _rk_nocolor=--no-color
    # $_rk_nocolor unquoted: empty, it adds no argument
    "$_rk_tiger" $_rk_nocolor "$_rk_target" > "$_rk_report" 2>&1
    _rc=$?
    if [ $_rc -ne 0 ]; then
        tail -n 15 "$_rk_report"
        echo -e "${YELLOW}${RK_WARN}${NC} $_rk_tiger could not run (exit $_rc) -- the mod was not linted; not blocking"
        return 0
    fi
    grep -q "PLEASE UPDATE" "$_rk_report" &&
        echo "  $_rk_tiger is older than the game it found; some reports may be wrong"
    _rk_summary="$(sed 's/\x1b\[[0-9;]*m//g' "$_rk_report" | grep -E '^fatal: [0-9]+, error: [0-9]+' | tail -n1)"
    if [ -z "$_rk_summary" ]; then
        echo -e "${YELLOW}${RK_WARN}${NC} $_rk_tiger gave no summary line -- see the report"
    elif printf '%s' "$_rk_summary" | grep -qE '^fatal: 0, error: 0,'; then
        echo -e "${GREEN}${RK_OK}${NC} $_rk_tiger: $_rk_summary"
    else
        echo -e "${YELLOW}${RK_WARN}${NC} $_rk_tiger: $_rk_summary (not blocking)"
    fi
    echo "  full report: $_rk_report"
}

# product: no debugger or print-style checks; the linter is the check.
rk_profile_paradox_product() {
    echo "  paradox: no debugger or print checks (the linter is the check)"
}

# precommit: localization encoding. Paradox games read localization .yml only
# as UTF-8 with a BOM; a file without one is skipped with no error, and its
# keys show raw in the game. The staged content is checked, not the working
# file, on every branch (pre-commit calls this before its private-branch exit).
rk_profile_paradox_precommit() {
    _rk_nobom=$(git -c core.quotePath=false diff --cached --name-only --diff-filter=ACMR |
        grep -E '(^|/)locali[sz]ation/.*\.yml$' |
        while IFS= read -r _rk_f; do
            [ "$(git show ":$_rk_f" 2>/dev/null | head -c 3 | od -An -tx1 | tr -d ' \n')" = efbbbf ] ||
                printf '%s\n' "$_rk_f"
        done)
    if [ -n "$_rk_nobom" ]; then
        echo ""
        echo "${RK_FAIL} COMMIT BLOCKED - localization file without a UTF-8 BOM"
        echo ""
        printf '%s\n' "$_rk_nobom" | while IFS= read -r _rk_f; do echo "  - $_rk_f"; done
        echo ""
        echo "The game skips such a file without an error. Save it as \"UTF-8 with BOM\","
        echo "stage it again, and commit."
        exit 1
    fi
}
