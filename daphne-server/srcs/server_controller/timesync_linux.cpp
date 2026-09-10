#include "server_controller/timesync_bus.hpp"
#include "server_controller/board_monitor.hpp"
#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <memory>
#include <regex>
#include <set>
#include <stdexcept>
#include <system_error>

namespace daphne_sc {
namespace {
constexpr const char* daemon = "org.freedesktop.DBus";
constexpr const char* daemon_path = "/org/freedesktop/DBus";
constexpr const char* service = "org.freedesktop.timesync1";
constexpr const char* path = "/org/freedesktop/timesync1";
constexpr const char* interface = "org.freedesktop.timesync1.Manager";
using Message = std::unique_ptr<sd_bus_message, decltype(&sd_bus_message_unref)>;
void need(bool value) { if (!value) throw std::runtime_error("Invalid timesync bus data"); }
void okay(int value) { if (value < 0) throw std::system_error(-value, std::generic_category()); }
void present(int value) { okay(value); need(value > 0); }
std::string bounded(const char* value, size_t maximum) {
  need(value != nullptr && strnlen(value, maximum + 1) <= maximum);
  return value;
}
void exit_container(sd_bus_message* message) {
  need(sd_bus_message_at_end(message, 0) > 0);
  okay(sd_bus_message_exit_container(message));
}
std::string string_reply(sd_bus_message* message, size_t maximum) {
  need(bounded(sd_bus_message_get_signature(message, 1), 16) == "s");
  need(bounded(sd_bus_message_get_sender(message), 80) == daemon);
  const char* value = nullptr;
  present(sd_bus_message_read(message, "s", &value));
  need(sd_bus_message_at_end(message, 1) > 0);
  return bounded(value, maximum);
}
struct BusCloser { void operator()(sd_bus* bus) const { sd_bus_close(bus); sd_bus_unref(bus); } };
using Bus = std::unique_ptr<sd_bus, BusCloser>;
class LinuxTimesync final : public TimesyncIo {
 public:
  uint64_t monotonic_ns() override { return monotonic_time_ns(); }
  TimesyncRaw query(uint64_t deadline_ns) override {
    sd_bus* pointer = nullptr;
    okay(sd_bus_new(&pointer));
    Bus bus(pointer);
    // Do not honor DBUS_SYSTEM_BUS_ADDRESS or other environment-selected routes.
    okay(sd_bus_set_address(bus.get(), "unix:path=/run/dbus/system_bus_socket"));
    okay(sd_bus_set_bus_client(bus.get(), 1));
    okay(sd_bus_set_method_call_timeout(bus.get(), 500000));
    okay(sd_bus_set_allow_interactive_authorization(bus.get(), 0));
    okay(sd_bus_set_exit_on_disconnect(bus.get(), 0));
    okay(sd_bus_start(bus.get()));
    return query_timesync_bus(bus.get(), deadline_ns, [this] { return monotonic_ns(); });
  }
};
}  // namespace

sd_bus_message* make_timesync_bus_request(sd_bus* bus, TimesyncBusQuery query, const std::string& unique) {
  const bool properties = query == TimesyncBusQuery::Properties;
  need(query == TimesyncBusQuery::BusId || query == TimesyncBusQuery::Owner || properties);
  if (properties) need(unique.size() <= 80 && std::regex_match(unique, std::regex(":[0-9]+(?:\\.[0-9]+)+")));
  else need(unique.empty());
  sd_bus_message* pointer = nullptr;
  okay(sd_bus_message_new_method_call(bus, &pointer, properties ? unique.c_str() : daemon,
      properties ? path : daemon_path, properties ? "org.freedesktop.DBus.Properties" : daemon,
      properties ? "GetAll" : query == TimesyncBusQuery::BusId ? "GetId" : "GetNameOwner"));
  Message message(pointer, sd_bus_message_unref);
  okay(sd_bus_message_set_auto_start(message.get(), 0));
  okay(sd_bus_message_set_allow_interactive_authorization(message.get(), 0));
  okay(sd_bus_message_set_expect_reply(message.get(), 1));
  if (properties || query == TimesyncBusQuery::Owner)
    okay(sd_bus_message_append(message.get(), "s", properties ? interface : service));
  return message.release();
}

TimesyncRaw parse_timesync_properties(sd_bus_message* message) {
  TimesyncRaw result;
  need(bounded(sd_bus_message_get_signature(message, 1), 16) == "a{sv}");
  result.reply_sender = bounded(sd_bus_message_get_sender(message), 80);
  const std::set<std::string> required{"ServerName", "ServerAddress", "PollIntervalUSec", "PollIntervalMinUSec",
      "PollIntervalMaxUSec", "RootDistanceMaxUSec", "NTPMessage", "Frequency"};
  std::set<std::string> seen;
  present(sd_bus_message_enter_container(message, 'a', "{sv}"));
  for (unsigned count = 0;; ++count) {
    const int entry = sd_bus_message_enter_container(message, 'e', "sv");
    okay(entry);
    if (!entry) break;
    need(count < 32);
    const char* key_raw = nullptr;
    present(sd_bus_message_read(message, "s", &key_raw));
    const auto key = bounded(key_raw, 80);
    need(seen.insert(key).second);
    if (!required.count(key)) {
      // Ignore unrelated server lists/properties, never copy or publish them.
      present(sd_bus_message_skip(message, "v"));
      exit_container(message);
      continue;
    }
    const char* signature = key == "ServerName" ? "s" : key == "ServerAddress" ? "(iay)" :
        key == "NTPMessage" ? "(uuuuittayttttbtt)" : key == "Frequency" ? "x" : "t";
    present(sd_bus_message_enter_container(message, 'v', signature));
    if (key == "ServerName") {
      const char* value = nullptr;
      present(sd_bus_message_read(message, "s", &value));
      result.selected_name = bounded(value, 253);
    } else if (key == "ServerAddress") {
      present(sd_bus_message_enter_container(message, 'r', "iay"));
      int family = 0; const void* bytes = nullptr; size_t size = 0;
      present(sd_bus_message_read(message, "i", &family));
      present(sd_bus_message_read_array(message, 'y', &bytes, &size));
      if (!(family == AF_UNSPEC && size == 0)) {
        need((family == AF_INET && size == 4) || (family == AF_INET6 && size == 16));
        char text[INET6_ADDRSTRLEN];
        need(inet_ntop(family, bytes, text, sizeof(text)) != nullptr);
        result.selected_address = text;
      }
      exit_container(message);
    } else if (key == "NTPMessage") {
      auto& raw = result.sample;
      present(sd_bus_message_enter_container(message, 'r', "uuuuittayttttbtt"));
      present(sd_bus_message_read(message, "uuuuitt", &raw.leap, &raw.version, &raw.mode, &raw.stratum,
          &raw.precision, &raw.root_delay_us, &raw.root_dispersion_us));
      const void* discarded_reference_id = nullptr; size_t size = 0;
      present(sd_bus_message_read_array(message, 'y', &discarded_reference_id, &size));
      need(size == 4); // May contain a private upstream IP: never retained/exported.
      int spike = 0;
      present(sd_bus_message_read(message, "ttttbtt", &raw.timestamps_us[0], &raw.timestamps_us[1],
          &raw.timestamps_us[2], &raw.timestamps_us[3], &spike, &raw.count, &raw.jitter_us));
      need(spike == 0 || spike == 1); raw.ignored_spike = spike;
      exit_container(message);
    } else if (key == "Frequency") {
      present(sd_bus_message_read(message, "x", &result.frequency_scaled_ppm));
    } else {
      auto* destination = key == "PollIntervalUSec" ? &result.poll_us : key == "PollIntervalMinUSec" ? &result.poll_min_us :
          key == "PollIntervalMaxUSec" ? &result.poll_max_us : &result.root_max_us;
      present(sd_bus_message_read(message, "t", destination));
    }
    exit_container(message); // variant
    exit_container(message); // dictionary entry
  }
  exit_container(message); // array
  need(sd_bus_message_at_end(message, 1) > 0);
  for (const auto& key : required) need(seen.count(key));
  return result;
}

TimesyncRaw query_timesync_bus(sd_bus* bus, uint64_t deadline, const std::function<uint64_t()>& now) {
  auto call = [&](TimesyncBusQuery query, const std::string& unique = std::string{}) {
    Message request(make_timesync_bus_request(bus, query, unique), sd_bus_message_unref);
    const auto time = now();
    need(time && time < deadline);
    const auto remaining_us = std::min<uint64_t>(500000, (deadline - time) / 1000);
    need(remaining_us > 0); // zero would select sd-bus's much longer default timeout.
    sd_bus_message* pointer = nullptr;
    const auto outcome = sd_bus_call(bus, request.get(), remaining_us, nullptr, &pointer);
    Message reply(pointer, sd_bus_message_unref);
    okay(outcome); need(reply != nullptr);
    return reply;
  };
  const auto id = string_reply(call(TimesyncBusQuery::BusId).get(), 32);
  const auto before = string_reply(call(TimesyncBusQuery::Owner).get(), 80);
  auto result = parse_timesync_properties(call(TimesyncBusQuery::Properties, before).get());
  result.bus_id = id; result.owner_before = before;
  result.owner_after = string_reply(call(TimesyncBusQuery::Owner).get(), 80);
  return result;
}
std::unique_ptr<TimesyncIo> make_linux_timesync_io() { return std::make_unique<LinuxTimesync>(); }
}  // namespace daphne_sc
