# shellcheck shell=sh
#
# repokit-common language profile: typescript. The same checks as javascript,
# named as typescript's. The profile contract is described in python.sh.

. "$RK_PROFILES_DIR/javascript.sh"

rk_profile_typescript_product() {
    _rk_js_product typescript
}
