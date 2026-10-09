#ifndef __RK_MACRO___VERSION_H
#define __RK_MACRO___VERSION_H

/* The single source of the version. Edit it with repokit-common's
 * sync-versions.py (--bump, --set); CMake, the .rc file and the code read it.
 * Only #define lines: the resource compiler includes this file too. */
#define __RK_MACRO___VERSION_MAJOR 0
#define __RK_MACRO___VERSION_MINOR 1
#define __RK_MACRO___VERSION_PATCH 0
#define __RK_MACRO___VERSION_PHASE ""
#define __RK_MACRO___VERSION_STRING "0.1.0"

#endif
