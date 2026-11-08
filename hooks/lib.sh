# shellcheck shell=sh
#
# repokit-common hook library -- sourced by hooks/pre-commit, post-commit and
# pre-push, from the folder they sit in. POSIX sh (pre-commit runs under sh).
# Nothing here exits: each hook decides what a failure means.
#
# Installed hooks are small stubs in .git/hooks (written by install-hooks.sh)
# that run the real hook from this checkout's vendored copy, so a hook finds
# its copy as the folder above hooks/. The candidate-path lookup below is the
# fallback for a hook copied straight into .git/hooks (older installs, tests).
# One place for all of this, so a fix reaches every hook (#14).

RK_DEFAULT_STRICT_BRANCHES="main master staging live"
RK_DEFAULT_PRIVATE_BRANCHES="local private feature/* feat/* prototype/* experiment/* spike/*"

# Sets REPO_ROOT, RK_DIR (the vendored copy), CONFIG_TOOL, VENDORED_DIR (RK_DIR
# relative to the root; empty when repokit-common is the project itself),
# SYNC_SCRIPT, UPDATE_SCRIPT and CURRENT_BRANCH.
rk_locate() {
    # Which overrides came from the environment, noted before any settings are
    # read: an empty REPOKIT_STRICT_BRANCHES in the environment means "no gated
    # branches this run", while an unset strict-branches setting reads as empty
    # too and means "the default set".
    _RK_ENV_STRICT="${REPOKIT_STRICT_BRANCHES+set}"
    _RK_ENV_PRIVATE="${REPOKIT_PRIVATE_BRANCHES+set}"
    _RK_ENV_OUTPUT="${REPOKIT_OUTPUT+set}"
    # One path form throughout: git answers C:/..., sh's pwd /c/...; resolving
    # through cd makes prefix stripping below reliable.
    REPO_ROOT="$(cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" && pwd)"
    _rk_hooks="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
    RK_DIR=""
    if [ -f "$_rk_hooks/../repokit_config.py" ]; then
        RK_DIR="$(cd "$_rk_hooks/.." && pwd)"
    else
        for _rk_cand in "$REPO_ROOT/scripts/repokit-common" "$REPO_ROOT/scripts" "$REPO_ROOT"; do
            [ -f "$_rk_cand/repokit_config.py" ] && { RK_DIR="$_rk_cand"; break; }
        done
        if [ -z "$RK_DIR" ]; then
            _rk_rel="$(git ls-files -- ':(glob)**/repokit_config.py' 2>/dev/null | head -n1)"
            [ -n "$_rk_rel" ] && [ -f "$REPO_ROOT/$_rk_rel" ] && RK_DIR="$(cd "$(dirname "$REPO_ROOT/$_rk_rel")" && pwd)"
        fi
    fi
    CONFIG_TOOL=""
    VENDORED_DIR=""
    if [ -n "$RK_DIR" ]; then
        CONFIG_TOOL="$RK_DIR/repokit_config.py"
        [ "$RK_DIR" != "$REPO_ROOT" ] && VENDORED_DIR="${RK_DIR#"$REPO_ROOT"/}"
    fi

    # The version tools: beside the copy when there is one, else the layouts
    # consumers have used, a bounded find under scripts/, then git's index
    # (layout-agnostic, no directory walk).
    SYNC_SCRIPT=""
    UPDATE_SCRIPT=""
    [ -n "$RK_DIR" ] && [ -f "$RK_DIR/sync-versions.py" ] && SYNC_SCRIPT="$RK_DIR/sync-versions.py"
    [ -n "$RK_DIR" ] && [ -f "$RK_DIR/update-version.sh" ] && UPDATE_SCRIPT="$RK_DIR/update-version.sh"
    if [ -z "$SYNC_SCRIPT" ]; then
        for _rk_cand in "$REPO_ROOT/scripts/repokit-common/sync-versions.py" "$REPO_ROOT/scripts/sync-versions.py"; do
            [ -f "$_rk_cand" ] && { SYNC_SCRIPT="$_rk_cand"; break; }
        done
        [ -z "$SYNC_SCRIPT" ] && SYNC_SCRIPT="$(find "$REPO_ROOT/scripts" -name sync-versions.py -type f -print 2>/dev/null | head -n1)"
        if [ -z "$SYNC_SCRIPT" ]; then
            _rk_rel="$(git ls-files -- '*sync-versions.py' 2>/dev/null | head -n1)"
            [ -n "$_rk_rel" ] && [ -f "$REPO_ROOT/$_rk_rel" ] && SYNC_SCRIPT="$REPO_ROOT/$_rk_rel"
        fi
    fi
    if [ -z "$UPDATE_SCRIPT" ]; then
        for _rk_cand in "$REPO_ROOT/scripts/repokit-common/update-version.sh" "$REPO_ROOT/scripts/update-version.sh"; do
            [ -f "$_rk_cand" ] && { UPDATE_SCRIPT="$_rk_cand"; break; }
        done
        if [ -z "$UPDATE_SCRIPT" ]; then
            _rk_rel="$(git ls-files -- '*update-version.sh' 2>/dev/null | head -n1)"
            [ -n "$_rk_rel" ] && [ -f "$REPO_ROOT/$_rk_rel" ] && UPDATE_SCRIPT="$REPO_ROOT/$_rk_rel"
        fi
    fi

    # symbolic-ref first: on a branch with no commits yet (a new or orphan
    # branch's first commit) rev-parse --abbrev-ref answers "HEAD".
    CURRENT_BRANCH="$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
}

# rk_read_settings KEY... -- sets REPOKIT_<KEY> for each key from the project's
# [tool.repokit-common] (one call to repokit_config.py). A variable already set
# in the environment wins over the setting, so REPOKIT_OUTPUT=plain or
# REPOKIT_STRICT_BRANCHES="" loosen or change one run without editing files.
# Returns 1 when a settings file exists but cannot be read; 0 otherwise
# (including no copy found or no python: nothing is set).
rk_read_settings() {
    [ -n "$CONFIG_TOOL" ] || return 0
    command -v python >/dev/null 2>&1 || return 0
    _rk_keep=""
    for _rk_key in "$@"; do
        _rk_var="REPOKIT_$(printf '%s' "$_rk_key" | tr 'abcdefghijklmnopqrstuvwxyz-' 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_')"
        if eval "[ \"\${$_rk_var+set}\" = set ]"; then
            _rk_keep="$_rk_keep $_rk_var"
            eval "_rk_saved_$_rk_var=\"\$$_rk_var\""
        fi
    done
    _rk_out="$(python "$CONFIG_TOOL" --shell "$@")" || return 1
    eval "$_rk_out"
    for _rk_var in $_rk_keep; do
        eval "$_rk_var=\"\$_rk_saved_$_rk_var\""
    done
    return 0
}

# rk_setup_output -- sets RK_OK, RK_WARN, RK_FAIL, RK_INFO and the colour codes
# RED, GREEN, YELLOW, BLUE, NC. The `output` setting (or REPOKIT_OUTPUT, which
# wins) is auto, plain or rich. auto: rich when the hook's output is a terminal,
# plain otherwise -- captured output (an IDE's git panel, CI, a tool) gets
# [OK]/[!]/[X] and no escape codes, which every console can show. Rich uses
# BMP symbols only; the astral emoji some consoles cannot draw are not used.
# Read settings (with the output key) first.
rk_setup_output() {
    _rk_mode="${REPOKIT_OUTPUT:-auto}"
    if [ "$_rk_mode" = auto ]; then
        if [ -t 1 ]; then _rk_mode=rich; else _rk_mode=plain; fi
    fi
    if [ "$_rk_mode" = rich ]; then
        RK_OK="✓"; RK_WARN="⚠"; RK_FAIL="✗"; RK_INFO="▸"
        RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
    else
        RK_OK="[OK]"; RK_WARN="[!]"; RK_FAIL="[X]"; RK_INFO="--"
        RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
    fi
}

# rk_load_profiles -- sources hooks/profiles/<language>.sh, beside this
# library, for each of REPOKIT_LANGUAGES that has one; sets RK_PROFILES_DIR.
# A profile holds one language's steps (see profiles/python.sh for the
# contract); a language without one gets no language-specific steps. Only
# names made of a-z, 0-9 and "-" are looked up. Returns 1 when the profiles
# folder itself is missing: the hook must stop rather than silently drop
# every language's checks. Run rk_locate first: _rk_hooks is the hooks'
# folder resolved before pre-push's cd, when a relative $0 still points at it.
# Read settings (with the languages key) first too.
rk_load_profiles() {
    RK_PROFILES_DIR="${_rk_hooks:-$(cd "$(dirname "$0")" 2>/dev/null && pwd)}/profiles"
    [ -d "$RK_PROFILES_DIR" ] || return 1
    for _rk_lp in ${REPOKIT_LANGUAGES:-}; do
        case "$_rk_lp" in *[!a-z0-9-]*|"") continue ;; esac
        [ -f "$RK_PROFILES_DIR/$_rk_lp.sh" ] && . "$RK_PROFILES_DIR/$_rk_lp.sh"
    done
    return 0
}

# rk_profile_fn LANGUAGE STEP -- prints the name of the function for STEP
# (setup, check, product, precommit) when LANGUAGE's profile defines it, and
# nothing otherwise. A hyphen in the language becomes "_" (c-cpp -> c_cpp).
rk_profile_fn() {
    _rk_pf="rk_profile_$(printf '%s' "$1" | tr -c 'A-Za-z0-9' '_')_$2"
    command -v "$_rk_pf" >/dev/null 2>&1 && printf '%s' "$_rk_pf"
    return 0
}

# rk_match_patterns BRANCH PATTERNS -- true when BRANCH matches one of the
# shell glob PATTERNS (space- or newline-separated). Patterns are matched,
# never expanded against files.
rk_match_patterns() {
    _rk_noglob_was=""
    case $- in *f*) _rk_noglob_was=1 ;; esac
    set -f
    for _rk_p in $2; do
        case "$1" in
            $_rk_p) [ -z "$_rk_noglob_was" ] && set +f; return 0 ;;
        esac
    done
    [ -z "$_rk_noglob_was" ] && set +f
    return 1
}

# rk_is_private_branch BRANCH -- true when private content may be committed on
# BRANCH: it matches private-branches (shell glob patterns), or the default
# set when the project sets none -- local, private, and the feature/, feat/,
# prototype/, experiment/ and spike/ prefixes. A project that names its own
# private branch (git-repokit's --private-branch) lists it here; the setting
# replaces the default, as strict-branches does. REPOKIT_PRIVATE_BRANCHES
# overrides it for one run, and an empty value makes every branch public.
# Read settings first.
rk_is_private_branch() {
    if [ "${_RK_ENV_PRIVATE-}" = set ] || [ -n "${REPOKIT_PRIVATE_BRANCHES-}" ]; then
        rk_match_patterns "$1" "${REPOKIT_PRIVATE_BRANCHES-}"
    else
        rk_match_patterns "$1" "$RK_DEFAULT_PRIVATE_BRANCHES"
    fi
}

# rk_is_strict_branch BRANCH -- true when BRANCH matches strict-branches (shell
# glob patterns, one per line or space-separated), or git-repokit's default set
# when the project sets none: main (passes CI), master (its other name),
# staging (pre-release) and live (production). Read settings first.
rk_is_strict_branch() {
    if [ "${_RK_ENV_STRICT-}" = set ] || [ -n "${REPOKIT_STRICT_BRANCHES-}" ]; then
        _rk_patterns="${REPOKIT_STRICT_BRANCHES-}"     # the environment's (even empty) or the setting's
    else
        _rk_patterns="$RK_DEFAULT_STRICT_BRANCHES"     # the project sets none
    fi
    rk_match_patterns "$1" "$_rk_patterns"
}

# The built-in private-content list, shared by pre-commit (staged paths) and
# pre-push (paths a push would add). Extended regular expressions.
RK_PRIVATE_PATH_RE="^.*/__private__.*|^.*/private_.*|^.*~$|\.backup$|\.bak$|\.log$|\.tmp$|^\.env.*|^\.env\.local$|^\.env\.private$|^convos/|^credentials/|^logs/|^nul$|^private/|^revisions/|^secrets/|^test-runs/|^test_runs/"

# rk_allowed PATH -- true when PATH is listed in the allowlist (one per line;
# # comments and blank lines allowed): a path that is deliberately public. The
# allowlist is RK_ALLOWLIST when set (pre-push sets it to the pushed tip's
# copy), else .repokit-allowlist at the repository root. Run rk_locate first.
rk_allowed() {
    _rk_al="${RK_ALLOWLIST:-$REPO_ROOT/.repokit-allowlist}"
    [ -f "$_rk_al" ] || return 1
    grep -v '^[[:space:]]*#' "$_rk_al" | grep -v '^[[:space:]]*$' | grep -Fxq -- "$1"
}

# rk_allowlist_add LIST -- appends each path in LIST (a file, one path per
# line) to .repokit-allowlist at the repository root, once each. The person's
# yes at a prompt (rk_ask) is the consent it records.
rk_allowlist_add() {
    _rk_al="$REPO_ROOT/.repokit-allowlist"
    if [ ! -f "$_rk_al" ]; then
        printf '%s\n' "# Paths that match the private-content list but are meant to be public." \
            "# One per line, from the repository root; read by the pre-commit and pre-push hooks." > "$_rk_al"
    fi
    while IFS= read -r _rk_ap; do
        [ -n "$_rk_ap" ] || continue
        grep -Fxq -- "$_rk_ap" "$_rk_al" || printf '%s\n' "$_rk_ap" >> "$_rk_al"
    done < "$1"
}

# rk_can_prompt -- true when a person can be asked, and the terminal is then
# open for reading on fd 3. Never in CI, never in a Claude Code session
# (CLAUDECODE; its commands cannot open a terminal anyway), never with
# REPOKIT_INTERACTIVE=0, and only when the terminal (REPOKIT_TTY, default
# /dev/tty) opens. Every other case answers no at once: an agent or a CI job
# gets the refusal and its machine-readable line, never a wait.
rk_can_prompt() {
    [ -z "${CI:-}" ] || return 1
    [ -z "${CLAUDECODE:-}" ] || return 1
    [ "${REPOKIT_INTERACTIVE:-1}" != 0 ] || return 1
    { exec 3<"${REPOKIT_TTY:-/dev/tty}"; } 2>/dev/null || return 1
    return 0
}

# rk_ask QUESTION -- asks on stderr and reads the answer from fd 3 (opened by
# rk_can_prompt); true only on y or yes. Bash waits at most 60 seconds; an
# empty answer, a timeout or end of input is no. Closes fd 3.
rk_ask() {
    printf '%s [y/N] ' "$1" >&2
    _rk_ans=""
    if [ -n "${BASH_VERSION:-}" ]; then
        read -r -t 60 _rk_ans <&3 || _rk_ans="${_rk_ans:-}"
    else
        read -r _rk_ans <&3 || _rk_ans="${_rk_ans:-}"
    fi
    exec 3<&-
    printf '\n' >&2
    _rk_ans="${_rk_ans%"$(printf '\r')"}"   # a Windows terminal or file may end the line with CR
    case "$_rk_ans" in [yY]|[yY][eE][sS]) return 0 ;; esac
    return 1
}

# rk_refused_lines KIND REASON REF FIX LIST -- one machine-readable line per
# path in LIST (a file, one path per line), on stderr, for agents and CI:
#   repokit-common: refused <KIND>=private-content reason=<REASON> ref=<REF> fix=<FIX> path=<path>
# git swallows a hook's exit code, so this line is the signal to read. path is
# last, so a path with spaces stays whole; FIX is comma-separated codes
# (allowlist, env:REPOKIT_ALLOW_PRIVATE_PUSH, config:repokit.allowPrivatePush, no-verify).
rk_refused_lines() {
    while IFS= read -r _rk_rp; do
        [ -n "$_rk_rp" ] || continue
        printf 'repokit-common: refused %s=private-content reason=%s ref=%s fix=%s path=%s\n' \
            "$1" "$2" "$3" "$4" "$_rk_rp" >&2
    done < "$5"
}

# rk_private_paths LIST -- prints, one per line and sorted, the paths in LIST (a
# file of NUL-delimited paths) that are private content: they match the
# built-in list, or one of the project's private-patterns (REPOKIT_PRIVATE_PATTERNS,
# literal path prefixes from the root, one per line; a leading "./" or "/" is
# ignored), and are not in .repokit-allowlist. One grep and one awk pass over
# the whole list; the allowlist is read only for paths that matched. Read
# settings (private-patterns) first.
rk_private_paths() {
    {
        tr '\0' '\n' < "$1" | grep -E "$RK_PRIVATE_PATH_RE"
        if [ -n "${REPOKIT_PRIVATE_PATTERNS-}" ]; then
            # The patterns travel in the environment (ENVIRON does no escape
            # processing, unlike awk -v); the paths on stdin.
            tr '\0' '\n' < "$1" | _RK_PP="$REPOKIT_PRIVATE_PATTERNS" awk '
                BEGIN {
                    m = split(ENVIRON["_RK_PP"], raw, "\n")
                    for (j = 1; j <= m; j++) {
                        e = raw[j]; sub(/\r$/, "", e); sub(/^\.\//, "", e); sub(/^\/+/, "", e)
                        if (e != "") p[++n] = e
                    }
                }
                { for (i = 1; i <= n; i++) if (index($0, p[i]) == 1) { print; next } }
            '
        fi
    } | sort -u | while IFS= read -r _rk_pp; do
        [ -n "$_rk_pp" ] || continue
        rk_allowed "$_rk_pp" || printf '%s\n' "$_rk_pp"
    done
}
