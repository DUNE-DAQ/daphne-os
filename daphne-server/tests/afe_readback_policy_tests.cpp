#include "server_controller/afe_readback_policy.hpp"
#include <cstdlib>
#include <sstream>
#include <thread>

using namespace daphne_sc;
static void require(bool value) { if (!value) std::abort(); }
template<class F> void throws(F action, const std::string& expected) {
  try { action(); } catch (const std::exception& e) {
    require(std::string(e.what()).find(expected) != std::string::npos); return;
  }
  std::abort();
}

int main() {
  require(parse_afe_readback_policy("strict") == AfeReadbackPolicy::kStrict);
  require(parse_afe_readback_policy("warn") == AfeReadbackPolicy::kWarn);
  throws([] { parse_afe_readback_policy("ignore"); }, "strict or warn");
  std::ostringstream log;
  AfeReadbackVerifier strict(AfeReadbackPolicy::kStrict, "test", log);
  require(strict.check(0, "FORMAT", 1, 1, "mismatch"));
  require(strict.summary().empty() && log.str().empty());
  // No AFE index is special: strict rejects and warn observes any of the five.
  AfeReadbackVerifier warn(AfeReadbackPolicy::kWarn, "test", log);
  for (uint32_t afe = 0; afe < 5; ++afe) {
    throws([&] { strict.check(afe, "FORMAT", 1, 0, "mismatch"); },
           "AFE" + std::to_string(afe) + " FORMAT expected=1 actual=0");
    require(!warn.check(afe, "FORMAT", 1, 0, "mismatch"));
    require(warn.summary().find("AFE" + std::to_string(afe)) != std::string::npos);
  }
  require(warn.summary().find("policy=warn") != std::string::npos);
  require(warn.summary().find("not guaranteed") != std::string::npos);
  const auto once = log.str();
  std::thread first([&] { for (unsigned n=0;n<1000;++n) warn.check(0,"FORMAT",1,0,"mismatch"); });
  std::thread second([&] { for (unsigned n=0;n<1000;++n) warn.check(0,"FORMAT",1,0,"mismatch"); });
  first.join(); second.join(); require(log.str() == once);
  // Only unequal values are tolerated. An exception during a physical read is
  // evaluated before check() and must propagate rather than becoming a warning.
  throws([&] { auto read = []() -> uint32_t { throw std::runtime_error("SPI timeout"); };
               warn.check(0,"FORMAT",1,read(),"mismatch"); }, "SPI timeout");
  require(with_afe_readback_notice("failure",AfeReadbackPolicy::kStrict)=="failure");
  require(with_afe_readback_notice("failure",AfeReadbackPolicy::kWarn).find("failure")!=std::string::npos);
  for (uint32_t value=2;value<1024;++value) warn.check(0,"NOISY",1,value,"mismatch");
  require(warn.summary().size()<40000);
  require(warn.summary().find("suppressed")!=std::string::npos);
  std::cout << "AFE readback strict/warn, all AFEs, concurrent deduplication, bounded logs and SPI errors: PASS\n";
}
