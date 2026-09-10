cmake_minimum_required(VERSION 3.10)

# Some macOS CommandLineTools installs require an explicit sysroot for libc++ headers.
if(APPLE AND (NOT CMAKE_OSX_SYSROOT OR CMAKE_OSX_SYSROOT STREQUAL ""))
  execute_process(
    COMMAND xcrun --show-sdk-path
    OUTPUT_VARIABLE _SDKROOT
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(_SDKROOT)
    set(CMAKE_OSX_SYSROOT "${_SDKROOT}" CACHE PATH "macOS SDK root" FORCE)
  endif()
endif()

if(APPLE AND EXISTS "${CMAKE_OSX_SYSROOT}/usr/include/c++/v1")
  add_compile_options(-isystem "${CMAKE_OSX_SYSROOT}/usr/include/c++/v1")
endif()

project(daphne_server LANGUAGES CXX)

# ---------------- Basics ----------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

option(DAPHNE_BUILD_PY_PROTO "Generate python *_pb2.py into build tree" ON)
option(DAPHNE_BUNDLE_ZEROMQ "Build bundled libzmq from third_party" OFF)
option(DAPHNE_BUILD_SERVER "Build the full ZMQ server" ON)
option(DAPHNE_BUILD_PROTOCOL_TESTS "Build hardware-free protobuf tests (also on x86)" OFF)
option(DAPHNE_ENABLE_HARDWARE_TESTS "Enable tests that access real DAPHNE hardware" OFF)
set(DAPHNE_DEPS_TARBALL_DIR "" CACHE PATH "Directory containing the pinned dependency tarball (see deps/deps.lock.cmake)")
include(CTest)

if(DAPHNE_DEPS_TARBALL_DIR AND NOT DAPHNE_DEPS_TARBALL_DIR STREQUAL "")
  include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/daphne_deps.cmake")
  daphne_use_locked_deps(TARBALL_DIR "${DAPHNE_DEPS_TARBALL_DIR}")
endif()

# ---------------- Hardware I2C layer ----
find_package(Threads REQUIRED)
find_library(I2C_LIB NAMES i2c HINTS /usr/lib /usr/local/lib)

if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND NOT I2C_LIB)
  message(FATAL_ERROR "libi2c is required by I2CDevice SMBus operations")
endif()

add_library(daphne_i2c_hw
  srcs/BoardI2C.cpp
  srcs/I2CDevice.cpp
  srcs/DaphneI2CDrivers.cpp
)
target_include_directories(daphne_i2c_hw PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/srcs
)
target_link_libraries(daphne_i2c_hw PUBLIC Threads::Threads)
if(I2C_LIB)
  target_link_libraries(daphne_i2c_hw PUBLIC ${I2C_LIB})
endif()

add_library(daphne_gateware
  srcs/server_controller/gateware.cpp
)
target_include_directories(daphne_gateware PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/srcs
)

add_library(daphne_current_adc srcs/ADS1261.cpp srcs/BoardSPI.cpp srcs/SpiDevice.cpp)
target_include_directories(daphne_current_adc PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/srcs)
target_link_libraries(daphne_current_adc PUBLIC daphne_gateware Threads::Threads)
if(BUILD_TESTING)
  add_executable(current_spi_probe tests/current_spi_probe.cpp)
  target_link_libraries(current_spi_probe PRIVATE daphne_current_adc)
  # Explicit diagnostic executable; never registered as an automatic hardware test.
endif()

if(BUILD_TESTING)
  add_subdirectory(tests)
endif()

# Everything below this point belongs to the full server and its dependencies.
if(DAPHNE_BUILD_SERVER)

# ---------------- OpenMP (optional) -----
find_package(OpenMP QUIET)
if(OpenMP_CXX_FOUND)
  message(STATUS "OpenMP found")
else()
  message(STATUS "OpenMP not found; continuing without it")
endif()
endif()

# ---------------- Protobuf --------------
if(DAPHNE_BUILD_SERVER OR DAPHNE_BUILD_PROTOCOL_TESTS)
find_path(DAPHNE_SYSTEMD_INCLUDE_DIR systemd/sd-bus.h)
find_library(DAPHNE_SYSTEMD_LIBRARY NAMES systemd libsystemd.so.0)
if(NOT DAPHNE_SYSTEMD_INCLUDE_DIR OR NOT DAPHNE_SYSTEMD_LIBRARY)
  message(FATAL_ERROR "libsystemd headers/library are required for read-only timesync service observations")
endif()
find_package(Protobuf REQUIRED)
message(STATUS "Using protoc: ${Protobuf_PROTOC_EXECUTABLE}")
include_directories(${Protobuf_INCLUDE_DIRS})

set(PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf)
set(PROTO_FILES
  ${PROTO_DIR}/daphneV3_high_level_confs.proto
  ${PROTO_DIR}/daphneV3_low_level_confs.proto
)

# Generate into build tree, mirroring source paths, so headers are at:
#   ${CMAKE_CURRENT_BINARY_DIR}/srcs/protobuf/*.pb.h
protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS ${PROTO_FILES})

add_library(daphne_proto ${PROTO_SRCS} ${PROTO_HDRS})
target_include_directories(daphne_proto PUBLIC
  ${CMAKE_CURRENT_BINARY_DIR}
  ${CMAKE_CURRENT_BINARY_DIR}/srcs
  ${PROTO_DIR}
)
target_link_libraries(daphne_proto PUBLIC protobuf::libprotobuf)

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/server_build_target.cmake")
add_library(daphne_software_build srcs/server_controller/software_build.cpp "${DAPHNE_BUILD_INFO_HEADER}")
add_dependencies(daphne_software_build daphne_build_metadata)
target_include_directories(daphne_software_build PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/srcs"
  PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(daphne_software_build PUBLIC daphne_proto)

add_library(daphne_telemetry_protocol
  srcs/server_controller/hdmezz_protocol.cpp
  srcs/server_controller/afe_global.cpp
  srcs/server_controller/protocol_errors.cpp
  srcs/server_controller/native_timestamp.cpp
  srcs/server_controller/regulator_monitor.cpp
  srcs/server_controller/regulator_linux.cpp
  srcs/server_controller/sfp_monitor.cpp
  srcs/server_controller/sfp_linux.cpp
  srcs/server_controller/ams_temperature.cpp
  srcs/server_controller/carrier_temperature.cpp
  srcs/server_controller/temperature_alarm.cpp
  srcs/server_controller/current_monitor_protocol.cpp
  srcs/server_controller/service_status.cpp
  srcs/server_controller/host_resources.cpp
  srcs/server_controller/host_software.cpp
  srcs/server_controller/host_clock.cpp
  srcs/server_controller/timesync.cpp
  srcs/server_controller/timesync_linux.cpp
  srcs/server_controller/telemetry_protocol.cpp
  srcs/server_controller/timing_status.cpp
  srcs/server_controller/fpga_health.cpp
  srcs/server_controller/fpga_programming_linux.cpp
  srcs/server_controller/readonly_mmio.cpp
)
target_include_directories(daphne_telemetry_protocol PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/srcs)
target_include_directories(daphne_telemetry_protocol PUBLIC ${DAPHNE_SYSTEMD_INCLUDE_DIR})
target_link_libraries(daphne_telemetry_protocol PUBLIC ${DAPHNE_SYSTEMD_LIBRARY})
target_link_libraries(daphne_telemetry_protocol PUBLIC daphne_proto daphne_software_build daphne_gateware daphne_i2c_hw daphne_current_adc Threads::Threads)
add_library(daphne_configuration
  srcs/server_controller/configuration_plan.cpp
  srcs/server_controller/runtime_state.cpp
  srcs/server_controller/configuration_fingerprint.cpp
)
target_include_directories(daphne_configuration PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/srcs)
target_link_libraries(daphne_configuration PUBLIC daphne_proto daphne_software_build daphne_gateware)
add_library(daphne_identity
  srcs/server_controller/management_link.cpp
  srcs/server_controller/board_identity.cpp
  srcs/server_controller/board_identity_linux.cpp
)
target_include_directories(daphne_identity PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/srcs)
target_link_libraries(daphne_identity PUBLIC daphne_configuration)
add_library(daphne_fpga_status srcs/server_controller/fpga_status.cpp)
target_include_directories(daphne_fpga_status PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/srcs)
target_link_libraries(daphne_fpga_status PUBLIC daphne_telemetry_protocol daphne_configuration)
if(BUILD_TESTING)
  add_executable(software_build_tests tests/software_build_tests.cpp)
  add_executable(hdmezz_protocol_tests tests/hdmezz_protocol_tests.cpp)
  target_link_libraries(hdmezz_protocol_tests PRIVATE daphne_telemetry_protocol daphne_i2c_hw)
  add_test(NAME hdmezz_protocol_unit COMMAND hdmezz_protocol_tests)
  set_tests_properties(hdmezz_protocol_unit PROPERTIES LABELS unit)
  add_executable(host_software_tests tests/host_software_tests.cpp)
  target_link_libraries(host_software_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME host_software_unit COMMAND host_software_tests)
  set_tests_properties(host_software_unit PROPERTIES LABELS unit)
  add_executable(host_software_probe tests/host_software_probe.cpp)
  target_link_libraries(host_software_probe PRIVATE daphne_telemetry_protocol)
  target_link_libraries(software_build_tests PRIVATE daphne_configuration)
  add_test(NAME software_build_unit COMMAND software_build_tests)
  set_tests_properties(software_build_unit PROPERTIES LABELS unit)
  add_executable(software_build_probe tests/software_build_probe.cpp)
  target_link_libraries(software_build_probe PRIVATE daphne_software_build)
  add_executable(fpga_status_tests tests/fpga_status_tests.cpp)
  target_link_libraries(fpga_status_tests PRIVATE daphne_fpga_status)
  add_test(NAME fpga_status_unit COMMAND fpga_status_tests)
  set_tests_properties(fpga_status_unit PROPERTIES LABELS unit)
  add_executable(afe_global_tests tests/afe_global_tests.cpp)
  target_link_libraries(afe_global_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME afe_global_unit COMMAND afe_global_tests)
  set_tests_properties(afe_global_unit PROPERTIES LABELS unit)
  add_executable(afe_global_probe tests/afe_global_probe.cpp)
  target_link_libraries(afe_global_probe PRIVATE daphne_fpga_status)
  add_executable(native_timestamp_tests tests/native_timestamp_tests.cpp)
  add_executable(protocol_error_tests tests/protocol_error_tests.cpp)
  target_link_libraries(protocol_error_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME protocol_error_unit COMMAND protocol_error_tests)
  set_tests_properties(protocol_error_unit PROPERTIES LABELS unit)
  target_link_libraries(native_timestamp_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME native_timestamp_unit COMMAND native_timestamp_tests)
  set_tests_properties(native_timestamp_unit PROPERTIES LABELS unit)
  add_executable(regulator_monitor_tests tests/regulator_monitor_tests.cpp)
  target_link_libraries(regulator_monitor_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME regulator_monitor_unit COMMAND regulator_monitor_tests)
  set_tests_properties(regulator_monitor_unit PROPERTIES LABELS unit)
  add_executable(regulator_probe tests/regulator_probe.cpp)
  target_link_libraries(regulator_probe PRIVATE daphne_telemetry_protocol)
  # Explicit read-only hardware diagnostic, never an automatic CTest.
  add_executable(identity_probe tests/identity_probe.cpp)
  target_link_libraries(identity_probe PRIVATE daphne_identity)
  # Opt-in local network read only; not an automatic hardware test.
  add_executable(board_identity_tests tests/board_identity_tests.cpp)
  target_link_libraries(board_identity_tests PRIVATE daphne_identity)
  add_test(NAME board_identity_unit COMMAND board_identity_tests)
  set_tests_properties(board_identity_unit PROPERTIES LABELS unit)
  add_executable(management_link_tests tests/management_link_tests.cpp)
  target_link_libraries(management_link_tests PRIVATE daphne_identity)
  add_test(NAME management_link_unit COMMAND management_link_tests)
  set_tests_properties(management_link_unit PROPERTIES LABELS unit)
  add_executable(management_link_probe tests/management_link_probe.cpp)
  target_link_libraries(management_link_probe PRIVATE daphne_identity)
  # Explicit read-only network probe, never an automatic hardware test.
  add_executable(current_mux_tests tests/current_mux_tests.cpp)
  target_link_libraries(current_mux_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME current_mux_unit COMMAND current_mux_tests)
  set_tests_properties(current_mux_unit PROPERTIES LABELS unit)
  add_executable(sfp_monitor_tests tests/sfp_monitor_tests.cpp)
  target_link_libraries(sfp_monitor_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME sfp_monitor_unit COMMAND sfp_monitor_tests)
  set_tests_properties(sfp_monitor_unit PROPERTIES LABELS unit)
  add_executable(sfp_probe tests/sfp_probe.cpp)
  target_link_libraries(sfp_probe PRIVATE daphne_telemetry_protocol)
  # Never an automatic hardware test; operator must explicitly opt in.
  add_executable(temperature_alarm_tests tests/temperature_alarm_tests.cpp)
  target_link_libraries(temperature_alarm_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME temperature_alarm_unit COMMAND temperature_alarm_tests)
  set_tests_properties(temperature_alarm_unit PROPERTIES LABELS unit)
  add_executable(configuration_fingerprint_tests tests/configuration_fingerprint_tests.cpp)
  target_link_libraries(configuration_fingerprint_tests PRIVATE daphne_configuration)
  add_test(NAME configuration_fingerprint_unit COMMAND configuration_fingerprint_tests)
  set_tests_properties(configuration_fingerprint_unit PROPERTIES LABELS unit)
  add_executable(serial_executor_tests tests/serial_executor_tests.cpp)
  target_link_libraries(serial_executor_tests PRIVATE daphne_configuration Threads::Threads)
  add_test(NAME serial_executor_unit COMMAND serial_executor_tests)
  set_tests_properties(serial_executor_unit PROPERTIES LABELS unit TIMEOUT 10)
  add_executable(runtime_state_tests tests/runtime_state_tests.cpp)
  target_link_libraries(runtime_state_tests PRIVATE daphne_configuration Threads::Threads)
  add_test(NAME runtime_state_unit COMMAND runtime_state_tests)
  set_tests_properties(runtime_state_unit PROPERTIES LABELS unit)
  add_executable(service_status_tests tests/service_status_tests.cpp)
  target_link_libraries(service_status_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME service_status_unit COMMAND service_status_tests)
  set_tests_properties(service_status_unit PROPERTIES LABELS unit)
  add_executable(host_resources_tests tests/host_resources_tests.cpp)
  target_link_libraries(host_resources_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME host_resources_unit COMMAND host_resources_tests)
  set_tests_properties(host_resources_unit PROPERTIES LABELS unit)
  add_executable(host_resources_probe tests/host_resources_probe.cpp)
  target_link_libraries(host_resources_probe PRIVATE daphne_telemetry_protocol)
  add_executable(host_clock_tests tests/host_clock_tests.cpp)
  target_link_libraries(host_clock_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME host_clock_unit COMMAND host_clock_tests)
  set_tests_properties(host_clock_unit PROPERTIES LABELS unit)
  add_executable(host_clock_probe tests/host_clock_probe.cpp)
  target_link_libraries(host_clock_probe PRIVATE daphne_telemetry_protocol)
  add_executable(timesync_tests tests/timesync_tests.cpp)
  target_link_libraries(timesync_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME timesync_unit COMMAND timesync_tests)
  set_tests_properties(timesync_unit PROPERTIES LABELS unit)
  add_executable(timesync_probe tests/timesync_probe.cpp)
  target_link_libraries(timesync_probe PRIVATE daphne_telemetry_protocol)
  add_executable(timesync_bus_tests tests/timesync_bus_tests.cpp)
  target_link_libraries(timesync_bus_tests PRIVATE daphne_telemetry_protocol Threads::Threads)
  add_test(NAME timesync_bus_unit COMMAND timesync_bus_tests)
  set_tests_properties(timesync_bus_unit PROPERTIES LABELS unit TIMEOUT 10)
  add_executable(carrier_temperature_tests tests/carrier_temperature_tests.cpp)
  target_link_libraries(carrier_temperature_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME carrier_temperature_unit COMMAND carrier_temperature_tests)
  set_tests_properties(carrier_temperature_unit PROPERTIES LABELS unit)
  add_executable(ams_temperature_tests tests/ams_temperature_tests.cpp)
  target_link_libraries(ams_temperature_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME ams_temperature_unit COMMAND ams_temperature_tests)
  set_tests_properties(ams_temperature_unit PROPERTIES LABELS unit)
  add_executable(timing_status_tests tests/timing_status_tests.cpp)
  target_link_libraries(timing_status_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME timing_status_unit COMMAND timing_status_tests)
  set_tests_properties(timing_status_unit PROPERTIES LABELS unit)
  add_executable(fpga_health_tests tests/fpga_health_tests.cpp)
  target_link_libraries(fpga_health_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME fpga_health_unit COMMAND fpga_health_tests)
  set_tests_properties(fpga_health_unit PROPERTIES LABELS unit TIMEOUT 10)
  add_executable(fpga_programming_probe tests/fpga_programming_probe.cpp)
  target_link_libraries(fpga_programming_probe PRIVATE daphne_telemetry_protocol)
  # Explicit sysfs readback only; not registered as an automatic hardware test.
  add_executable(configuration_plan_tests tests/configuration_plan_tests.cpp)
  target_link_libraries(configuration_plan_tests PRIVATE daphne_configuration)
  add_test(NAME configuration_plan_unit COMMAND configuration_plan_tests)
  set_tests_properties(configuration_plan_unit PROPERTIES LABELS unit)
  add_executable(board_monitor_tests tests/board_monitor_tests.cpp)
  target_link_libraries(board_monitor_tests PRIVATE daphne_telemetry_protocol)
  add_test(NAME board_monitor_unit COMMAND board_monitor_tests)
  set_tests_properties(board_monitor_unit PROPERTIES LABELS unit)
endif()

if(DAPHNE_BUILD_PY_PROTO)
  # Also regenerate Python stubs in the build tree so clients can import the
  # same schema the C++ binary was built against.
  set(PY_PROTO_OUT ${CMAKE_CURRENT_BINARY_DIR}/srcs/protobuf)
  file(MAKE_DIRECTORY ${PY_PROTO_OUT})
  add_custom_command(
    OUTPUT
      ${PY_PROTO_OUT}/daphneV3_high_level_confs_pb2.py
      ${PY_PROTO_OUT}/daphneV3_low_level_confs_pb2.py
    COMMAND ${Protobuf_PROTOC_EXECUTABLE}
      --python_out=${PY_PROTO_OUT}
      -I ${PROTO_DIR}
      ${PROTO_DIR}/daphneV3_high_level_confs.proto
      ${PROTO_DIR}/daphneV3_low_level_confs.proto
    DEPENDS ${PROTO_FILES}
    COMMENT "Generating Python protobuf stubs"
  )
  add_custom_target(daphne_proto_py ALL DEPENDS
    ${PY_PROTO_OUT}/daphneV3_high_level_confs_pb2.py
    ${PY_PROTO_OUT}/daphneV3_low_level_confs_pb2.py
  )
endif()
endif()

# ---------------- cppzmq / libzmq -------
if(DAPHNE_BUILD_SERVER)
find_package(cppzmq CONFIG QUIET)
if(cppzmq_FOUND)
  message(STATUS "cppzmq package found")
else()
  message(STATUS "cppzmq package not found; using header-only fallback")
  find_path(CPPZMQ_INCLUDE_DIR NAMES zmq.hpp
            HINTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/cppzmq
                  /usr/include /usr/local/include /opt/homebrew/include /opt/local/include
                  $ENV{HOME}/.local/include)
  if(NOT CPPZMQ_INCLUDE_DIR)
    message(FATAL_ERROR "zmq.hpp not found; set CPPZMQ_INCLUDE_DIR or install cppzmq headers")
  endif()
  add_library(cppzmq INTERFACE)
  target_include_directories(cppzmq INTERFACE ${CPPZMQ_INCLUDE_DIR})
endif()

set(DAPHNE_ZMQ_TARGET "")
if(DAPHNE_BUNDLE_ZEROMQ)
  if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/third_party/zeromq-4.3.4/CMakeLists.txt")
    message(FATAL_ERROR "DAPHNE_BUNDLE_ZEROMQ=ON but third_party/zeromq-4.3.4 is missing")
  endif()

  # Keep the bundled build as small and dependency-free as possible.
  set(BUILD_SHARED OFF CACHE BOOL "" FORCE)
  set(BUILD_STATIC ON CACHE BOOL "" FORCE)
  set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(WITH_DOC OFF CACHE BOOL "" FORCE)
  set(WITH_DOCS OFF CACHE BOOL "" FORCE)
  set(ENABLE_CURVE OFF CACHE BOOL "" FORCE)
  set(WITH_LIBSODIUM OFF CACHE BOOL "" FORCE)
  set(WITH_TLS OFF CACHE BOOL "" FORCE)

  add_subdirectory(third_party/zeromq-4.3.4 EXCLUDE_FROM_ALL)
  set(DAPHNE_ZMQ_TARGET libzmq-static)
else()
  find_library(ZMQ_LIB NAMES zmq HINTS /usr/lib /usr/local/lib /lib)
  if(NOT ZMQ_LIB)
    message(FATAL_ERROR "libzmq not found; set DAPHNE_BUNDLE_ZEROMQ=ON or install zeromq (libzmq)")
  endif()
  add_library(daphne_zmq_lib INTERFACE)
  target_link_libraries(daphne_zmq_lib INTERFACE ${ZMQ_LIB})
  set(DAPHNE_ZMQ_TARGET daphne_zmq_lib)
endif()

# ---------------- CLI11 (fallback) ------
find_package(CLI11 CONFIG QUIET)
if(CLI11_FOUND)
  message(STATUS "CLI11 package found")
else()
  message(STATUS "CLI11 package not found; using header-only fallback")
  find_path(CLI11_INCLUDE_DIR NAMES CLI/CLI.hpp
            HINTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/CLI11/include
                  /usr/include /usr/local/include /opt/homebrew/include /opt/local/include
                  $ENV{HOME}/.local/include
                  /home/petalinux/zmq/CLI11 /home/petalinux/zmq/CLI11/include)
  if(NOT CLI11_INCLUDE_DIR)
    message(FATAL_ERROR "CLI/CLI.hpp not found; set CLI11_INCLUDE_DIR or install CLI11 headers")
  endif()
  add_library(CLI11::CLI11 INTERFACE IMPORTED)
  set_target_properties(CLI11::CLI11 PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${CLI11_INCLUDE_DIR}")
endif()

# ---------------- Sources ----------------
set(SOURCES
  srcs/DevMem.cpp
  srcs/FpgaRegDict.cpp
  srcs/reg.cpp
  srcs/FpgaReg.cpp
  srcs/Spi.cpp
  srcs/SpyBuffer.cpp
  srcs/Afe.cpp
  srcs/FrontEnd.cpp
  srcs/Endpoint.cpp
  srcs/Dac.cpp
  srcs/Daphne.cpp
  srcs/server_controller/handlers.cpp
  srcs/server_controller/current_monitor.cpp
  srcs/server_controller/devmem_mmio.cpp
  srcs/server_controller/monitoring.cpp
  srcs/server_controller/spybuffer_chunker.cpp
  srcs/server_controller/router_server.cpp
  srcs/server_controller/main.cpp
)

set(DAPHNE_PROTO_DEPRECATION_WARNING_SOURCES
  srcs/server_controller/handlers.cpp
  srcs/server_controller/spybuffer_chunker.cpp
  srcs/server_controller/router_server.cpp
)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  set_source_files_properties(${DAPHNE_PROTO_DEPRECATION_WARNING_SOURCES}
    PROPERTIES COMPILE_OPTIONS "-Wno-deprecated-declarations"
  )
endif()

add_executable(daphneServer ${SOURCES})
target_include_directories(daphneServer PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/srcs
  ${CMAKE_CURRENT_BINARY_DIR}
  ${CMAKE_CURRENT_BINARY_DIR}/srcs
  ${CMAKE_CURRENT_BINARY_DIR}/srcs/protobuf
  ${PROTO_DIR}
)
target_link_libraries(daphneServer PRIVATE
  daphne_i2c_hw
  daphne_current_adc
  daphne_gateware
  daphne_proto
  daphne_telemetry_protocol
  daphne_configuration
  daphne_identity
  daphne_fpga_status
  cppzmq
  ${DAPHNE_ZMQ_TARGET}
  CLI11::CLI11
  Threads::Threads
)
if(OpenMP_CXX_FOUND)
  target_link_libraries(daphneServer PRIVATE OpenMP::OpenMP_CXX)
endif()
add_executable(daphne_zmq_server
  srcs/srv.cpp
  srcs/DevMem.cpp
)
target_link_libraries(daphne_zmq_server PRIVATE
  cppzmq
  ${DAPHNE_ZMQ_TARGET}
)
if(OpenMP_CXX_FOUND)
  target_link_libraries(daphne_zmq_server PRIVATE OpenMP::OpenMP_CXX)
endif()

# ---------------- Diagnostics ------------
message(STATUS "ZMQ lib: ${ZMQ_LIB}")
message(STATUS "ZMQ target: ${DAPHNE_ZMQ_TARGET} (bundled=${DAPHNE_BUNDLE_ZEROMQ})")
message(STATUS "cppzmq target: " $<TARGET_EXISTS:cppzmq>)
message(STATUS "CLI11 target: " $<TARGET_EXISTS:CLI11::CLI11>)
message(STATUS "I2C lib: ${I2C_LIB}")

endif()
