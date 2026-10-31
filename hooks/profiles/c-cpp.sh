# shellcheck shell=sh
#
# repokit-common language profile: c-cpp (functions use c_cpp: a hyphen cannot
# appear in a shell function name). The profile contract is described in
# python.sh. POSIX sh.

rk_profile_c_cpp_product() {
    echo "  c-cpp: no product checks (the build and tests are the gate)"
}
