# Run before compiling the metadata consumer on EVERY build, not just configure.
# No build paths, host/user names, remotes, environment or timestamps are emitted.
cmake_minimum_required(VERSION 3.10)
foreach(required SOURCE_DIR OUTPUT_HEADER COMPILER_ID COMPILER_VERSION TARGET_ARCH PROTOBUF_VERSION)
  if(NOT DEFINED ${required} OR "${${required}}" STREQUAL "")
    message(FATAL_ERROR "Missing server-build metadata input: ${required}")
  endif()
endforeach()
foreach(label COMPILER_ID COMPILER_VERSION TARGET_ARCH PROTOBUF_VERSION)
  string(LENGTH "${${label}}" length)
  if(length GREATER 80 OR NOT "${${label}}" MATCHES "^[A-Za-z0-9_.+-]+$")
    message(FATAL_ERROR "Invalid server-build metadata label: ${label}")
  endif()
endforeach()

file(SHA256 "${SOURCE_DIR}/srcs/protobuf/daphneV3_high_level_confs.proto" HIGH_SCHEMA_SHA256)
file(SHA256 "${SOURCE_DIR}/srcs/protobuf/daphneV3_low_level_confs.proto" LOW_SCHEMA_SHA256)
set(SOURCE_COMMIT "")
set(SOURCE_TREE "")
set(SOURCE_DIRTY "")
# A Git-less source export must not acquire the identity of an unrelated parent
# repository. The exact server directory must exist as a committed tree.
find_package(Git QUIET)
if(GIT_FOUND)
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_DIR}" rev-parse --verify HEAD
    RESULT_VARIABLE head_result OUTPUT_VARIABLE head OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET TIMEOUT 5)
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_DIR}" rev-parse --show-prefix
    RESULT_VARIABLE prefix_result OUTPUT_VARIABLE prefix OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET TIMEOUT 5)
  string(REGEX REPLACE "/$" "" prefix "${prefix}")
  if(prefix STREQUAL "")
    set(tree_selector "${head}^{tree}")
  else()
    set(tree_selector "${head}:${prefix}")
  endif()
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_DIR}" rev-parse --verify "${tree_selector}"
    RESULT_VARIABLE tree_result OUTPUT_VARIABLE tree OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET TIMEOUT 5)
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_DIR}" cat-file -t "${tree}"
    RESULT_VARIABLE type_result OUTPUT_VARIABLE tree_type OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET TIMEOUT 5)
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_DIR}" status --porcelain=v1 --untracked-files=all -- .
    RESULT_VARIABLE status_result OUTPUT_VARIABLE status ERROR_QUIET TIMEOUT 5)
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SOURCE_DIR}" rev-parse --verify HEAD
    RESULT_VARIABLE after_result OUTPUT_VARIABLE after OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET TIMEOUT 5)
  string(LENGTH "${head}" head_length)
  string(LENGTH "${tree}" tree_length)
  if(head_result EQUAL 0 AND prefix_result EQUAL 0 AND tree_result EQUAL 0 AND
     type_result EQUAL 0 AND tree_type STREQUAL "tree" AND
     status_result EQUAL 0 AND after_result EQUAL 0 AND head STREQUAL after AND
     head MATCHES "^[0-9a-f]+$" AND tree MATCHES "^[0-9a-f]+$" AND
     (head_length EQUAL 40 OR head_length EQUAL 64) AND head_length EQUAL tree_length)
    set(SOURCE_COMMIT "${head}")
    set(SOURCE_TREE "${tree}")
    if(status STREQUAL "")
      set(SOURCE_DIRTY "false")
    else()
      set(SOURCE_DIRTY "true")
    endif()
  endif()
endif()
configure_file("${CMAKE_CURRENT_LIST_DIR}/server_build_info.hpp.in" "${OUTPUT_HEADER}" @ONLY)
