// Real sd-bus wire transport on a private socket pair; never the system bus.
#include "server_controller/timesync_bus.hpp"
#include "server_controller/board_monitor.hpp"
#include <atomic>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <sys/socket.h>
#include <thread>
#include <vector>

using namespace daphne_sc;
void require(bool good) { if (!good) throw std::runtime_error("Timesync private-bus test failed"); }
void okay(int status) { require(status >= 0); }
struct Closer { void operator()(sd_bus* bus) const { sd_bus_close(bus); sd_bus_unref(bus); } };
using Bus = std::unique_ptr<sd_bus, Closer>;
using Message = std::unique_ptr<sd_bus_message, decltype(&sd_bus_message_unref)>;

struct Harness {
  Bus client, server;
  std::string scenario;
  std::atomic<bool> stop{false}, failed{false};
  std::thread worker;
  std::vector<std::string> methods;
  unsigned owners = 0;
  explicit Harness(const std::string& selected) : scenario(selected) {
    sd_bus* pointer = nullptr;
    okay(sd_bus_new(&pointer)); client.reset(pointer);
    okay(sd_bus_new(&pointer)); server.reset(pointer);
    int pair[2]; require(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) == 0);
    okay(sd_bus_set_fd(client.get(), pair[0], pair[0]));
    okay(sd_bus_set_fd(server.get(), pair[1], pair[1]));
    okay(sd_bus_set_bus_client(client.get(), 0));
    sd_id128_t id{}; id.bytes[0] = 1;
    okay(sd_bus_set_server(server.get(), 1, id));
    okay(sd_bus_set_anonymous(server.get(), 1));
    okay(sd_bus_set_sender(client.get(), ":1.80"));
    okay(sd_bus_add_filter(server.get(), nullptr, &Harness::dispatch, this));
    okay(sd_bus_start(server.get())); okay(sd_bus_start(client.get()));
    worker = std::thread([this] {
      while (!stop) {
        const int status = sd_bus_process(server.get(), nullptr);
        if (status < 0) { if (!stop) failed = true; break; }
        if (!status && sd_bus_wait(server.get(), 1000) < 0) { if (!stop) failed = true; break; }
      }
    });
  }
  void finish() { stop = true; if (worker.joinable()) worker.join(); }
  ~Harness() { finish(); }
  static int dispatch(sd_bus_message* request, void* data, sd_bus_error*) {
    auto& self = *static_cast<Harness*>(data);
    try { return self.handle(request); }
    catch (...) {
      self.failed = true;
      return sd_bus_reply_method_errorf(request, SD_BUS_ERROR_FAILED, "Synthetic private-bus failure");
    }
  }
  void payload(sd_bus_message* message) {
    okay(sd_bus_message_open_container(message, 'a', "{sv}"));
    auto entry = [&](const std::string& key, const char* type, auto put) {
      okay(sd_bus_message_open_container(message, 'e', "sv"));
      okay(sd_bus_message_append(message, "s", key.c_str()));
      okay(sd_bus_message_open_container(message, 'v', type));
      put();
      okay(sd_bus_message_close_container(message)); okay(sd_bus_message_close_container(message));
    };
    const std::string peer = scenario == "oversized-name" ? std::string(254, 'a') : "private-peer.example.invalid";
    entry("ServerName", "s", [&] { okay(sd_bus_message_append(message, "s", peer.c_str())); });
    entry("ServerAddress", "(iay)", [&] {
      const uint8_t bytes[] = {192, 0, 2, 10};
      okay(sd_bus_message_open_container(message, 'r', "iay"));
      okay(sd_bus_message_append(message, "i", scenario == "bad-family" ? 999 : AF_INET));
      okay(sd_bus_message_append_array(message, 'y', bytes, sizeof(bytes)));
      okay(sd_bus_message_close_container(message));
    });
    for (const auto& item : std::vector<std::pair<std::string, uint64_t>>{{"PollIntervalUSec", 32000000},
         {"PollIntervalMinUSec", 32000000}, {"PollIntervalMaxUSec", 2048000000}, {"RootDistanceMaxUSec", 5000000}})
      entry(item.first, "t", [&] { okay(sd_bus_message_append(message, "t", item.second)); });
    if (scenario != "missing-frequency")
      entry("Frequency", scenario == "wrong-type" ? "s" : "x", [&] {
        if (scenario == "wrong-type") okay(sd_bus_message_append(message, "s", "private-secret"));
        else okay(sd_bus_message_append(message, "x", int64_t{-123456}));
      });
    entry("NTPMessage", "(uuuuittayttttbtt)", [&] {
      okay(sd_bus_message_open_container(message, 'r', "uuuuittayttttbtt"));
      okay(sd_bus_message_append(message, "uuuuitt", uint32_t{0}, uint32_t{4}, uint32_t{4}, uint32_t{2},
          int32_t{-20}, uint64_t{1000}, uint64_t{2000}));
      const uint8_t reference[] = {198, 51, 100, 1};
      okay(sd_bus_message_append_array(message, 'y', reference, scenario == "bad-reference" ? 3 : 4));
      okay(sd_bus_message_append(message, "ttttbtt", uint64_t{1700000000000000}, uint64_t{1700000000000101},
          uint64_t{1700000000000111}, uint64_t{1700000000000200}, 1, UINT64_MAX, uint64_t{300}));
      okay(sd_bus_message_close_container(message));
    });
    entry("SystemNTPServers", "as", [&] {
      okay(sd_bus_message_open_container(message, 'a', "s"));
      okay(sd_bus_message_append(message, "s", "unused-private.example.invalid"));
      okay(sd_bus_message_close_container(message));
    });
    if (scenario == "duplicate") entry("ServerName", "s", [&] { okay(sd_bus_message_append(message, "s", "duplicate")); });
    if (scenario == "too-many") for (int index = 0; index < 32; ++index)
      entry("Extra" + std::to_string(index), "t", [&] { okay(sd_bus_message_append(message, "t", uint64_t{0})); });
    okay(sd_bus_message_close_container(message));
  }
  int handle(sd_bus_message* request) {
    uint8_t type = 0; okay(sd_bus_message_get_type(request, &type));
    if (type != SD_BUS_MESSAGE_METHOD_CALL) return 0;
    require(sd_bus_message_get_auto_start(request) == 0);
    require(sd_bus_message_get_allow_interactive_authorization(request) == 0);
    require(sd_bus_message_get_expect_reply(request) > 0);
    const std::string member = sd_bus_message_get_member(request);
    methods.push_back(member);
    const bool properties = member == "GetAll";
    require(properties || member == "GetId" || member == "GetNameOwner"); // No setters, activation, scans or arbitrary calls.
    require(std::string(sd_bus_message_get_path(request)) == (properties ? "/org/freedesktop/timesync1" : "/org/freedesktop/DBus"));
    require(std::string(sd_bus_message_get_interface(request)) == (properties ? "org.freedesktop.DBus.Properties" : "org.freedesktop.DBus"));
    require(std::string(sd_bus_message_get_destination(request)) == (properties ? ":1.55" : "org.freedesktop.DBus"));
    if (properties || member == "GetNameOwner") {
      const char* argument = nullptr; require(sd_bus_message_read(request, "s", &argument) > 0);
      require(std::string(argument) == (properties ? "org.freedesktop.timesync1.Manager" : "org.freedesktop.timesync1"));
    }
    require(sd_bus_message_at_end(request, 1) > 0);
    if (scenario == "timeout" && properties) return 1;
    if (scenario == "no-owner" && member == "GetNameOwner")
      return sd_bus_reply_method_errorf(request, SD_BUS_ERROR_NAME_HAS_NO_OWNER, "Synthetic absent owner");
    sd_bus_message* pointer = nullptr;
    okay(sd_bus_message_new_method_return(request, &pointer));
    Message reply(pointer, sd_bus_message_unref);
    okay(sd_bus_message_set_sender(reply.get(), properties ? (scenario == "wrong-sender" ? ":1.99" : ":1.55") : "org.freedesktop.DBus"));
    if (properties) payload(reply.get());
    else if (member == "GetId") okay(sd_bus_message_append(reply.get(), "s", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));
    else {
      ++owners;
      okay(sd_bus_message_append(reply.get(), "s", scenario == "owner-change" && owners == 2 ? ":1.56" : ":1.55"));
    }
    okay(sd_bus_send(server.get(), reply.get(), nullptr));
    return 1;
  }
};
struct Io final : TimesyncIo {
  sd_bus* bus;
  explicit Io(sd_bus* value) : bus(value) {}
  uint64_t monotonic_ns() override { return monotonic_time_ns(); }
  TimesyncRaw query(uint64_t deadline) override { return query_timesync_bus(bus, deadline, [this] { return monotonic_ns(); }); }
};
int main() {
  for (const std::string scenario : {"valid", "private", "owner-change", "wrong-sender", "no-owner", "timeout", "oversized-name",
                                   "bad-family", "wrong-type", "missing-frequency", "bad-reference", "duplicate", "too-many"}) {
    Harness server(scenario); Io io(server.client.get()); TimesyncHistory history;
    const auto result = read_timesync(io, history, scenario == "private");
    server.finish(); require(!server.failed);
    if (scenario == "valid" || scenario == "private") {
      require(result.quality() == daphne::MEASUREMENT_GOOD && result.processed_packet_count() == UINT64_MAX);
      require(result.last_sample().offset_ns() == 6000 && result.last_sample().ignored_spike());
      require(result.last_sample().round_trip_delay_ns() == 190000);
      require(result.has_selected_server_name() == (scenario == "private"));
      require(result.has_selected_server_address() == (scenario == "private"));
      require(result.SerializeAsString().find("unused-private") == std::string::npos);
      require(result.SerializeAsString().find("198.51.100.1") == std::string::npos);
      if (scenario == "valid") require(result.SerializeAsString().find("private-peer") == std::string::npos);
      require(server.methods == std::vector<std::string>{"GetId", "GetNameOwner", "GetAll", "GetNameOwner"});
    } else {
      require(result.quality() != daphne::MEASUREMENT_GOOD);
      require(!result.observed_monotonic_ns() && !result.has_processed_packet_count() && !result.details_included());
      require(!result.has_selected_server_name() && !result.has_selected_server_address());
      require(result.SerializeAsString().find("private-secret") == std::string::npos);
    }
  }
  std::cout << "Private socket-pair sd-bus methods/no-activation flags, exact uint64, parser, privacy, owner, timeout and malformed-reply tests passed\n";
}
