# Writes OUT_FILE with <MACRO>_VERSION_FULL in the house format:
#   <base>_<branch>_<build count>-<YYYYMMDD>-<short hash>
# Outside a git checkout (a source archive) the git fields read "unknown".
# The file is rewritten only when its content changes, so builds stay incremental.
function(_rk_git out)
    execute_process(COMMAND git ${ARGN} WORKING_DIRECTORY "${SRC_DIR}"
        OUTPUT_VARIABLE _o ERROR_QUIET RESULT_VARIABLE _rc OUTPUT_STRIP_TRAILING_WHITESPACE)
    if(_rc EQUAL 0 AND NOT _o STREQUAL "")
        set(${out} "${_o}" PARENT_SCOPE)
    else()
        set(${out} "unknown" PARENT_SCOPE)
    endif()
endfunction()

# Only this project's own repository counts. A source tree unpacked inside
# another checkout (an archive under a home-directory repo, a vendored copy)
# must not take that outer repository's branch, count and hash.
_rk_git(_top rev-parse --show-toplevel)
get_filename_component(_src_real "${SRC_DIR}" REALPATH)
if(NOT _top STREQUAL "unknown")
    get_filename_component(_top "${_top}" REALPATH)
endif()
string(TOLOWER "${_src_real}" _src_l)
string(TOLOWER "${_top}" _top_l)
if(_top_l STREQUAL _src_l)
    _rk_git(_branch rev-parse --abbrev-ref HEAD)
    _rk_git(_count rev-list --count HEAD)
    _rk_git(_hash rev-parse --short HEAD)
    _rk_git(_date log -1 --format=%cd --date=format:%Y%m%d)
else()
    foreach(_v _branch _count _hash _date)
        set(${_v} "unknown")
    endforeach()
endif()

set(_full "${BASE_VERSION}_${_branch}_${_count}-${_date}-${_hash}")
set(_text "#pragma once\n#define ${MACRO}_VERSION_FULL \"${_full}\"\n")
if(EXISTS "${OUT_FILE}")
    file(READ "${OUT_FILE}" _old)
else()
    set(_old "")
endif()
if(NOT _old STREQUAL _text)
    file(WRITE "${OUT_FILE}" "${_text}")
endif()
