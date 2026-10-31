# shellcheck shell=sh
#
# repokit-common language profile: csharp. The profile contract is described in
# python.sh. POSIX sh.

rk_profile_csharp_product() {
    _rk_debug_check csharp "Debugger\.Break\(\)" "Debugger.Break() calls" --include="*.cs"
    _rk_noise_check csharp "Console.WriteLine(" "Console.WriteLine()" --include="*.cs"
}
