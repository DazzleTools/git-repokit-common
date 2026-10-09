// The version string agrees with its components. A plain assert executable,
// registered with CTest (the xormove pattern: no test framework needed).
#include <cassert>
#include <cstdio>
#include <string>

#include "__RK_SNAKE__/version.h"

int main() {
    std::string expected = std::to_string(__RK_MACRO___VERSION_MAJOR) + "." +
                           std::to_string(__RK_MACRO___VERSION_MINOR) + "." +
                           std::to_string(__RK_MACRO___VERSION_PATCH);
    std::string phase = __RK_MACRO___VERSION_PHASE;
    if (!phase.empty()) expected += "-" + phase;
    if (expected != __RK_MACRO___VERSION_STRING) {
        std::printf("version string %s != components %s\n", __RK_MACRO___VERSION_STRING, expected.c_str());
        return 1;
    }
    return 0;
}
