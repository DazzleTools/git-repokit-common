// __RK_PROJECT__ -- __RK_DESCRIPTION__
#include <cstdio>
#include <cstring>

#include "__RK_SNAKE__/version.h"
#include "__RK_SNAKE___stamp.h"

int main(int argc, char** argv) {
    if (argc > 1 && std::strcmp(argv[1], "--version") == 0) {
        std::printf("__RK_PROJECT__ %s (%s)\n", __RK_MACRO___VERSION_STRING, __RK_MACRO___VERSION_FULL);
        return 0;
    }
    std::printf("__RK_PROJECT__: try --version\n");
    return 0;
}
