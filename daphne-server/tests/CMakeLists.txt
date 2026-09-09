add_executable(ads1261_tests ads1261_tests.cpp)
target_link_libraries(ads1261_tests PRIVATE daphne_current_adc)
add_test(NAME ads1261_unit COMMAND ads1261_tests)
set_tests_properties(ads1261_unit PROPERTIES LABELS unit)

add_executable(board_spi_tests board_spi_tests.cpp)
target_link_libraries(board_spi_tests PRIVATE daphne_current_adc)
add_test(NAME board_spi_unit COMMAND board_spi_tests)
set_tests_properties(board_spi_unit PROPERTIES LABELS unit)

add_executable(board_i2c_tests board_i2c_tests.cpp)
target_link_libraries(board_i2c_tests PRIVATE daphne_i2c_hw)
add_test(NAME board_i2c_unit COMMAND board_i2c_tests)
set_tests_properties(board_i2c_unit PROPERTIES LABELS unit)

add_executable(register_reads_tests register_reads_tests.cpp)
target_link_libraries(register_reads_tests PRIVATE daphne_gateware)
add_test(NAME register_reads_unit COMMAND register_reads_tests)
set_tests_properties(register_reads_unit PROPERTIES LABELS unit)

add_executable(hdmezz_driver_tests
  hdmezz_driver_tests.cpp
)
target_link_libraries(hdmezz_driver_tests PRIVATE daphne_i2c_hw)
if(MSVC)
  target_compile_options(hdmezz_driver_tests PRIVATE /W4)
else()
  target_compile_options(hdmezz_driver_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
add_test(NAME hdmezz_driver_unit COMMAND hdmezz_driver_tests)
set_tests_properties(hdmezz_driver_unit PROPERTIES LABELS unit)

add_executable(gateware_mode_tests
  gateware_mode_tests.cpp
)
target_link_libraries(gateware_mode_tests PRIVATE daphne_gateware)
if(MSVC)
  target_compile_options(gateware_mode_tests PRIVATE /W4)
else()
  target_compile_options(gateware_mode_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
add_test(NAME gateware_mode_unit COMMAND gateware_mode_tests)
set_tests_properties(gateware_mode_unit PROPERTIES LABELS unit)

if(DAPHNE_ENABLE_HARDWARE_TESTS AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
  add_executable(i2c_hdmezz_smoke
    i2c_hdmezz_smoke.cpp
  )
  target_link_libraries(i2c_hdmezz_smoke PRIVATE daphne_i2c_hw)
  add_test(NAME i2c_hdmezz_smoke
           COMMAND i2c_hdmezz_smoke /dev/i2c-2 0)
  set_tests_properties(i2c_hdmezz_smoke PROPERTIES
    LABELS "hardware;i2c"
    RUN_SERIAL TRUE
  )
endif()
