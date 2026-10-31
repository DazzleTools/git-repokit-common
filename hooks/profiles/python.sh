# shellcheck shell=sh
#
# repokit-common language profile: python.
#
# A profile is sourced by the hooks (lib.sh, rk_load_profiles) for a project
# whose languages include it, and may define any of these steps; a step it does
# not define is simply skipped:
#
#   rk_profile_<language>_setup      pre-push, before the checks (sets state)
#   rk_profile_<language>_check      pre-push: the language's default check
#                                    step, replaced by check-command.<language>
#   rk_profile_<language>_product    pre-push: product checks (debugger
#                                    statements, print-style noise)
#   rk_profile_<language>_precommit  pre-commit: checks on the staged files
#
# Profiles are POSIX sh, because pre-commit runs under sh and sources them all:
# no arrays, no [[ ]], no PIPESTATUS. The pre-push steps run inside pre-push
# (bash) and use its helpers: _rk_debug_check, _rk_noise_check,
# _rk_run_streamed, and the output variables from rk_setup_output.

# setup: the package directory (__init__.py at the root or under src/). The
# product checks scan it; with none they scan every .py file from the root.
rk_profile_python_setup() {
    for dir in */; do
        if [ -f "${dir}__init__.py" ]; then
            PACKAGE_DIR="${dir%/}"
            break
        fi
    done

    # Also check src/ layout (PEP 517 / setuptools src layout)
    if [ -z "$PACKAGE_DIR" ] && [ -d "src" ]; then
        for dir in src/*/; do
            if [ -f "${dir}__init__.py" ]; then
                PACKAGE_DIR="${dir%/}"
                break
            fi
        done
    fi

    if [ -z "$PACKAGE_DIR" ]; then
        # Warn only a project that declares itself a Python package; there a
        # missing __init__.py is worth saying. A TypeScript, C or Rust project
        # whose Python is only tooling would get it on every push, which teaches
        # people to skip the real warnings. Either way the checks below then
        # cover every .py file.
        if [ -f setup.py ] || [ -f setup.cfg ] || \
           { [ -f pyproject.toml ] && grep -qE '^[[:space:]]*\[project\]' pyproject.toml; }; then
            echo -e "${YELLOW}Warning: No Python package directory found (no __init__.py)${NC}"
            echo "Skipping package-specific checks"
        fi
    fi
}

# check: the syntax check. compileall checks recursively, handles the src/
# layout and does not fail when there are no .py files. Root-level .py files (a
# package's __init__.py or version.py kept at the root) are checked too,
# non-recursively, when the package lives elsewhere. The bytecode goes to a
# throwaway folder (PYTHONPYCACHEPREFIX), never beside the sources: left in the
# project it is junk at best, and in a template tree it gets copied into every
# project made from it (git-repokit 0.7.2 found seven such files in its
# output). A syntax error blocks any branch.
rk_profile_python_check() {
    echo -e "${BLUE}Checking Python syntax...${NC}"
    _syntax_failed=false
    _rk_pyc="$(python -c "import tempfile; print(tempfile.mkdtemp(prefix='rk-syntax-'))" 2>/dev/null)"
    _syntax_out="$(PYTHONPYCACHEPREFIX="$_rk_pyc" python -m compileall -q "$PACKAGE_DIR" 2>&1)" || _syntax_failed=true
    if [ "$PACKAGE_DIR" != "." ]; then
        _root_out="$(PYTHONPYCACHEPREFIX="$_rk_pyc" python -m compileall -q -l . 2>&1)" || { _syntax_failed=true; _syntax_out="$_syntax_out$_root_out"; }
    fi
    [ -n "$_rk_pyc" ] && python -c "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$_rk_pyc" 2>/dev/null
    if [ "$_syntax_failed" = true ]; then
        echo -e "${RED}${RK_FAIL} Python syntax errors found${NC}"
        echo "$_syntax_out"
        echo "Fix syntax errors before pushing"
        exit 1
    fi
    echo -e "${GREEN}${RK_OK}${NC} Python syntax check passed"
}

# product: exactly the checks every Python consumer had before profiles existed.
rk_profile_python_product() {
    _rk_debug_check python "import pdb|pdb\.set_trace\(\)" "pdb statements" --include="*.py"
    _rk_noise_check python "print(" "print()" --include="*.py"
}
