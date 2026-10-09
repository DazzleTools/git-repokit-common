cmake_minimum_required(VERSION 3.20)

# The version lives in one place: include/__RK_SNAKE__/version.h (edited by
# repokit-common's sync-versions.py). CMake reads it here; it is never typed twice.
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/include/__RK_SNAKE__/version.h" _rk_ver
     REGEX "^#define __RK_MACRO___VERSION_(MAJOR|MINOR|PATCH) ")
foreach(_line IN LISTS _rk_ver)
    string(REGEX MATCH "_(MAJOR|MINOR|PATCH) +([0-9]+)" _m "${_line}")
    set(_rk_${CMAKE_MATCH_1} ${CMAKE_MATCH_2})
endforeach()

project(__RK_PROJECT__
    VERSION ${_rk_MAJOR}.${_rk_MINOR}.${_rk_PATCH}
    DESCRIPTION "__RK_DESCRIPTION__"
    LANGUAGES CXX RC)
message(STATUS "__RK_PROJECT__ version ${PROJECT_VERSION}")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
    add_compile_options(/utf-8 /W4)
endif()

# Build stamp, generated at build time so commits never dirty the tree:
# <version>_<branch>_<build count>-<date>-<short hash>.
add_custom_target(__RK_SNAKE___stamp ALL
    COMMAND ${CMAKE_COMMAND}
        -DSRC_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DOUT_FILE=${CMAKE_CURRENT_BINARY_DIR}/generated/__RK_SNAKE___stamp.h
        -DBASE_VERSION=${PROJECT_VERSION}
        -DMACRO=__RK_MACRO__
        -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/GenerateStamp.cmake
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/generated/__RK_SNAKE___stamp.h
    COMMENT "Version stamp")

add_executable(__RK_PROJECT__ src/main.cpp)
if(WIN32)
    target_sources(__RK_PROJECT__ PRIVATE src/app.rc)
endif()
target_include_directories(__RK_PROJECT__ PRIVATE
    include ${CMAKE_CURRENT_BINARY_DIR}/generated)
add_dependencies(__RK_PROJECT__ __RK_SNAKE___stamp)

enable_testing()
add_executable(test_version tests/test_version.cpp)
target_include_directories(test_version PRIVATE include)
add_test(NAME version COMMAND test_version)
