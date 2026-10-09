/* __RK_PROJECT__ -- __RK_DESCRIPTION__ */
#include <stdio.h>
#include <string.h>

#include "__RK_SNAKE__/version.h"

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--version") == 0) {
        printf("__RK_PROJECT__ %s\n", __RK_MACRO___VERSION_STRING);
        return 0;
    }
    printf("__RK_PROJECT__: try --version\n");
    return 0;
}
