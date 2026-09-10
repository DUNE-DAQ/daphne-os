#include "server_controller/management_link.hpp"
#include "server_controller/board_monitor.hpp"

#include <array>
#include <cerrno>
#include <limits>
#include <stdexcept>
#include <system_error>
#ifdef __linux__
#include <fcntl.h>
#include <linux/magic.h>
#include <sys/vfs.h>
#include <unistd.h>
#endif

namespace daphne_sc {
namespace {
using Observation = daphne::ManagementLinkObservation;
struct Spec { daphne::ManagementLinkMetric metric; const char* path; const char* unit; uint32_t width; };
constexpr std::array<Spec, 14> specs{{
    {daphne::MANAGEMENT_LINK_OPERSTATE, "operstate", "1", 0},
    {daphne::MANAGEMENT_LINK_CARRIER, "carrier", "1", 0},
    {daphne::MANAGEMENT_LINK_SPEED_MBPS, "speed", "Mbit/s", 0},
    {daphne::MANAGEMENT_LINK_DUPLEX, "duplex", "1", 0},
    {daphne::MANAGEMENT_LINK_MTU_BYTES, "mtu", "B", 0},
    {daphne::MANAGEMENT_LINK_RX_BYTES, "statistics/rx_bytes", "B", 64},
    {daphne::MANAGEMENT_LINK_RX_PACKETS, "statistics/rx_packets", "packet", 64},
    {daphne::MANAGEMENT_LINK_RX_ERRORS, "statistics/rx_errors", "packet", 64},
    {daphne::MANAGEMENT_LINK_RX_DROPPED, "statistics/rx_dropped", "packet", 64},
    {daphne::MANAGEMENT_LINK_TX_BYTES, "statistics/tx_bytes", "B", 64},
    {daphne::MANAGEMENT_LINK_TX_PACKETS, "statistics/tx_packets", "packet", 64},
    {daphne::MANAGEMENT_LINK_TX_ERRORS, "statistics/tx_errors", "packet", 64},
    {daphne::MANAGEMENT_LINK_TX_DROPPED, "statistics/tx_dropped", "packet", 64},
    {daphne::MANAGEMENT_LINK_CARRIER_CHANGES, "carrier_changes", "count", 32}}};
class Unavailable : public std::runtime_error { using std::runtime_error::runtime_error; };
std::string token(std::string input) {
  if (input.empty() || input.size() > 64) throw std::runtime_error("Invalid link input size");
  if (input.back() == '\n') input.pop_back();
  if (input.empty() || input.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789-") != std::string::npos)
    throw std::runtime_error("Invalid link token");
  return input;
}
uint64_t integer(const std::string& value) {
  if (value.empty() || value.size() > 20 || value.find_first_not_of("0123456789") != std::string::npos)
    throw std::runtime_error("Invalid link integer");
  return std::stoull(value);
}
void fail(Observation& item, daphne::MeasurementQuality quality, const char* reason) {
  item.clear_value(); item.clear_observed_monotonic_ns(); item.clear_observed_host_unix_ns();
  item.set_quality(quality); item.set_detail(reason);
}
void decode(Observation& item, const std::string& text) {
  switch (item.metric()) {
    case daphne::MANAGEMENT_LINK_OPERSTATE:
      if (text != "unknown" && text != "notpresent" && text != "down" && text != "lowerlayerdown" &&
          text != "testing" && text != "dormant" && text != "up") throw std::runtime_error("Invalid operstate");
      item.set_text_value(text); return;
    case daphne::MANAGEMENT_LINK_CARRIER:
      if (text != "0" && text != "1") throw std::runtime_error("Invalid carrier");
      item.set_flag_value(text == "1"); return;
    case daphne::MANAGEMENT_LINK_DUPLEX:
      if (text == "unknown") throw Unavailable("Unknown duplex");
      if (text != "half" && text != "full") throw std::runtime_error("Invalid duplex");
      item.set_text_value(text); return;
    case daphne::MANAGEMENT_LINK_SPEED_MBPS:
      if (text == "-1" || text == "4294967295") throw Unavailable("Unknown speed");
      break;
    default: break;
  }
  const auto value = integer(text);
  if ((item.metric() == daphne::MANAGEMENT_LINK_SPEED_MBPS || item.metric() == daphne::MANAGEMENT_LINK_MTU_BYTES) &&
      (!value || value > UINT32_MAX)) throw std::runtime_error("Invalid link setting range");
  if (item.counter_width_bits() == 32 && value > UINT32_MAX) throw std::runtime_error("Link counter overflow");
  item.set_unsigned_value(value);
}
bool unavailable_errno(const std::error_code& code) {
  return code == std::errc::no_such_file_or_directory || code == std::errc::no_such_device ||
      code == std::errc::permission_denied || code == std::errc::operation_not_supported ||
      code == std::errc::invalid_argument; // sysfs carrier/speed can reject an admin-down device.
}
Observation collect(ManagementLinkIo& io, const Spec& spec) {
  Observation item;
  item.set_metric(spec.metric); item.set_source(spec.path); item.set_unit(spec.unit);
  item.set_counter_width_bits(spec.width);
  try {
    item.set_acquisition_started_monotonic_ns(io.now().monotonic_ns);
    decode(item, token(io.read_file(spec.path, 64)));
    const auto end = io.now();
    if (!item.acquisition_started_monotonic_ns() || end.monotonic_ns < item.acquisition_started_monotonic_ns())
      throw std::runtime_error("Invalid link acquisition clock");
    item.set_quality(daphne::MEASUREMENT_GOOD); item.set_observed_monotonic_ns(end.monotonic_ns);
    item.set_observed_host_unix_ns(end.host_unix_ns);
    item.set_detail(spec.width ? "Cumulative driver-exported count; reset epoch and hardware counter width not observed" :
                                "Sampled Linux attribute; no end-to-end connectivity inference");
  } catch (const Unavailable&) {
    fail(item, daphne::MEASUREMENT_UNAVAILABLE, "Driver reports unknown link setting");
  } catch (const std::system_error& e) {
    fail(item, unavailable_errno(e.code()) ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR,
         "Link attribute unavailable or read failed; private details suppressed");
  } catch (const std::exception&) {
    fail(item, daphne::MEASUREMENT_ERROR, "Invalid link data or observation clock");
  }
  return item;
}
void invalidate(daphne::ManagementLinkStatus& result, daphne::MeasurementQuality quality) {
  result.set_quality(quality); result.set_detail("Management interface bracket unavailable or changed; no values retained");
  result.clear_interface_index(); result.clear_observed_monotonic_ns(); result.clear_observed_host_unix_ns();
  result.set_link_state_bracket_verified(false);
  for (auto& item : *result.mutable_observations()) fail(item, quality, "Management interface bracket not verified");
}
daphne::ManagementLinkStatus empty_status() {
  daphne::ManagementLinkStatus result;
  for (const auto& spec : specs) {
    auto* item = result.add_observations();
    item->set_metric(spec.metric); item->set_source(spec.path); item->set_unit(spec.unit); item->set_counter_width_bits(spec.width);
  }
  return result;
}
#ifdef __linux__
class LinuxLink final : public ManagementLinkIo {
 public:
  explicit LinuxLink(const std::string& interface) {
    if (interface.empty() || interface.size() >= 16 || interface == "." || interface == ".." ||
        interface.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-") != std::string::npos)
      throw std::runtime_error("Invalid selected interface");
    fd_ = open(("/sys/class/net/" + interface).c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd_ < 0) throw std::system_error(errno, std::generic_category());
    struct statfs info{};
    if (fstatfs(fd_, &info) != 0 || info.f_type != SYSFS_MAGIC) {
      close(fd_); fd_ = -1; throw std::runtime_error("Not a sysfs interface directory");
    }
  }
  ~LinuxLink() override { if (fd_ >= 0) close(fd_); }
  std::string read_file(const char* path, size_t maximum) override {
    bool allowed = std::string(path) == "ifindex";
    for (const auto& spec : specs) allowed |= std::string(path) == spec.path;
    if (!allowed || maximum != 64) throw std::runtime_error("Unapproved link attribute");
    const int input = openat(fd_, path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (input < 0) throw std::system_error(errno, std::generic_category());
    std::string data;
    try {
      char buffer[65];
      for (;;) {
        const auto count = read(input, buffer, maximum + 1 - data.size());
        if (count < 0) {
          if (errno == EINTR) continue;
          throw std::system_error(errno, std::generic_category());
        }
        if (!count) break;
        data.append(buffer, static_cast<size_t>(count));
        if (data.size() > maximum) throw std::runtime_error("Oversized link attribute");
      }
    } catch (...) { close(input); throw; }
    close(input); return data;
  }
  ManagementLinkTime now() override { return {host_unix_time_ns(), monotonic_time_ns()}; }
 private:
  int fd_ = -1;
};
#endif
}  // namespace

daphne::ManagementLinkStatus read_management_link(ManagementLinkIo& io, uint32_t expected_index) {
  auto result = empty_status();
  try {
    result.set_acquisition_started_monotonic_ns(io.now().monotonic_ns);
    if (!expected_index || expected_index > INT32_MAX ||
        integer(token(io.read_file("ifindex", 64))) != expected_index) throw std::runtime_error("Wrong interface index");
    result.set_interface_index(expected_index);
    for (size_t n = 0; n < specs.size(); ++n) *result.mutable_observations(n) = collect(io, specs[n]);
    const auto state_after = collect(io, specs[0]), carrier_after = collect(io, specs[1]);
    const auto& state = result.observations(0);
    const auto& carrier = result.observations(1);
    const bool stable = state.quality() == daphne::MEASUREMENT_GOOD && carrier.quality() == daphne::MEASUREMENT_GOOD &&
        state_after.quality() == daphne::MEASUREMENT_GOOD && carrier_after.quality() == daphne::MEASUREMENT_GOOD &&
        state.text_value() == state_after.text_value() && carrier.flag_value() == carrier_after.flag_value();
    result.set_link_state_bracket_verified(stable);
    if (!stable || !carrier.flag_value() || state.text_value() != "up") {
      for (int n : {2, 3}) fail(*result.mutable_observations(n), daphne::MEASUREMENT_UNAVAILABLE,
          "Current negotiation not established by matching carrier-up/operstate-up bracket");
    }
    if (integer(token(io.read_file("ifindex", 64))) != expected_index) throw std::runtime_error("Interface index changed");
    const auto end = io.now();
    if (!result.acquisition_started_monotonic_ns() || end.monotonic_ns < result.acquisition_started_monotonic_ns())
      throw std::runtime_error("Invalid link bracket clock");
    for (const auto& item : result.observations()) if (item.quality() == daphne::MEASUREMENT_GOOD &&
        (item.acquisition_started_monotonic_ns() < result.acquisition_started_monotonic_ns() || item.observed_monotonic_ns() > end.monotonic_ns))
      throw std::runtime_error("Invalid metric bracket clock");
    for (const auto* item : {&state_after, &carrier_after}) if (item->quality() == daphne::MEASUREMENT_GOOD &&
        (item->acquisition_started_monotonic_ns() < result.acquisition_started_monotonic_ns() || item->observed_monotonic_ns() > end.monotonic_ns))
      throw std::runtime_error("Invalid final state bracket clock");
    result.set_quality(daphne::MEASUREMENT_GOOD); result.set_observed_monotonic_ns(end.monotonic_ns);
    result.set_observed_host_unix_ns(end.host_unix_ns);
    result.set_detail("Matching ifindex bracket; inspect individual metric quality. Sequential, not atomic; counter reset epoch unobserved");
  } catch (const std::system_error& e) {
    invalidate(result, unavailable_errno(e.code()) ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR);
  } catch (const std::exception&) { invalidate(result, daphne::MEASUREMENT_ERROR); }
  return result;
}

daphne::ManagementLinkStatus read_management_link_linux(const std::string& interface, uint32_t expected_index) {
  auto result = empty_status();
  try {
#ifdef __linux__
    LinuxLink io(interface);
    return read_management_link(io, expected_index);
#else
    (void)interface; (void)expected_index;
    invalidate(result, daphne::MEASUREMENT_UNAVAILABLE);
#endif
  } catch (const std::system_error& e) {
    invalidate(result, unavailable_errno(e.code()) ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR);
  } catch (const std::exception&) { invalidate(result, daphne::MEASUREMENT_ERROR); }
  return result;
}
}  // namespace daphne_sc
