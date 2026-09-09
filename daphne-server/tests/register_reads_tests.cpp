#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <utility>
#include <vector>

#include "server_controller/register_reads.hpp"

namespace {
void require(bool ok) {
  if (!ok) throw std::runtime_error("register read assertion failed");
}
template <typename Function>
void rejects(Function function) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  require(rejected);
}
uint64_t scripted_read(const std::vector<std::pair<uint32_t, uint32_t>>& script) {
  size_t index = 0;
  auto read = [&](uint32_t address) {
    const auto item = script.at(index++);
    require(address == item.first);
    return item.second;
  };
  const auto result = daphne_sc::read_stable_counter64(read, 0, 4);
  require(index == script.size());
  return result;
}
}

int main() {
  using namespace daphne_sc;
  validate_counter_request(kSelfTriggerBaseAddress, {0, 39});
  rejects([] { validate_counter_request(0x94000000, {0}); });
  rejects([] { validate_counter_request(kSelfTriggerBaseAddress, {0, 40}); });
  rejects([] { validate_counter_request(kSelfTriggerBaseAddress, {UINT32_MAX}); });
  require(scripted_read({{4, 0}, {0, 0}, {4, 0}}) == 0);
  require(scripted_read({{4, 7}, {0, UINT32_MAX}, {4, 7}}) == 0x7FFFFFFFFULL);
  require(scripted_read({{4, 7}, {0, 0}, {4, 8}, {4, 8}, {0, 3}, {4, 8}})
          == 0x800000003ULL);
  unsigned reads = 0;
  rejects([&] {
    read_stable_counter64([&](uint32_t) { return reads++; }, 0, 4);
  });
  require(reads == 9);
  std::cout << "Counter address, channel, rollover and exhaustion tests passed\n";
}
