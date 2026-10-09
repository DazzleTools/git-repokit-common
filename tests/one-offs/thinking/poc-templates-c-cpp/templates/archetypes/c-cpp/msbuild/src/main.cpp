// __RK_PROJECT__ -- __RK_DESCRIPTION__
#include <cstdio>
#include <cstring>

#include "__RK_SNAKE__/version.h"

int main(int argc, char** argv) {
    if (argc > 1 && std::strcmp(argv[1], "--version") == 0) {
        std::printf("__RK_PROJECT__ %s\n", __RK_MACRO___VERSION_STRING);
        return 0;
    }
    std::printf("__RK_PROJECT__: try --version\n");
    return 0;
}
