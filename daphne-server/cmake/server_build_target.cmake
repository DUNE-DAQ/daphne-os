# Shared by the real server and incremental-build regression fixtures.
set(DAPHNE_BUILD_INFO_HEADER "${CMAKE_CURRENT_BINARY_DIR}/server_build_info.generated.hpp")
add_custom_target(daphne_build_metadata
  COMMAND "${CMAKE_COMMAND}"
    "-DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
    "-DOUTPUT_HEADER=${DAPHNE_BUILD_INFO_HEADER}"
    "-DCOMPILER_ID=${CMAKE_CXX_COMPILER_ID}"
    "-DCOMPILER_VERSION=${CMAKE_CXX_COMPILER_VERSION}"
    "-DTARGET_ARCH=${CMAKE_SYSTEM_PROCESSOR}"
    "-DPROTOBUF_VERSION=${Protobuf_VERSION}"
    -P "${CMAKE_CURRENT_LIST_DIR}/server_build_info.cmake"
  BYPRODUCTS "${DAPHNE_BUILD_INFO_HEADER}"
  COMMENT "Refreshing compiled server build/schema identity"
  VERBATIM)
