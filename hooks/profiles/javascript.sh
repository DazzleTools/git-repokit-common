# shellcheck shell=sh
#
# repokit-common language profile: javascript (typescript.sh reuses it).
# The profile contract is described in python.sh. POSIX sh.

# _rk_js_product LANGUAGE -- debugger statements (an error) and console.log
# noise (a warning) in the JavaScript and TypeScript sources.
_rk_js_product() {
    _rk_debug_check "$1" "^[[:space:]]*debugger;?[[:space:]]*$" "debugger statements" \
        --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.mjs" --include="*.cjs"
    _rk_noise_check "$1" "console.log(" "console.log()" \
        --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.mjs" --include="*.cjs"
}

rk_profile_javascript_product() {
    _rk_js_product javascript
}
