#include <iostream>
#include "server_controller/software_build.hpp"

// Software-only native diagnostic: no runtime initialization or external I/O.
int main() {
  const auto bytes = daphne_sc::server_build_info().SerializeAsString();
  constexpr char digits[] = "0123456789abcdef";
  std::cout << "{\"build_wire_hex\":\"";
  for (unsigned char byte : bytes) std::cout << digits[byte >> 4] << digits[byte & 15];
  std::cout << "\"}\n";
}
