#include "server_controller/board_identity.hpp"
#include "server_controller/board_monitor.hpp"
#include "server_controller/management_link.hpp"

#include <filesystem>
#include <iomanip>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#ifdef __linux__
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <net/if_arp.h>
#include <netpacket/packet.h>
#endif

namespace daphne_sc {
namespace {
#ifdef __linux__
daphne::ManagementNetworkObservation sample(const std::string& interface) {
  ifaddrs* addresses = nullptr;
  if (getifaddrs(&addresses) != 0) throw std::runtime_error("Management network enumeration failed");
  std::unique_ptr<ifaddrs, decltype(&freeifaddrs)> owned(addresses, freeifaddrs);
  daphne::ManagementNetworkObservation result;
  result.set_interface_name(interface);
  result.set_present(false);
  bool packet_found = false;
  std::set<std::string> ipv4s;
  for (const auto* item = addresses; item; item = item->ifa_next) {
    if (!item->ifa_name || interface != item->ifa_name) continue;
    result.set_present(true);
    if (result.has_flags_raw() && result.flags_raw() != item->ifa_flags)
      throw std::runtime_error("Management interface flags changed during enumeration");
    result.set_flags_raw(item->ifa_flags);
    if (!item->ifa_addr) continue;
    if (item->ifa_addr->sa_family == AF_PACKET) {
      const auto* link = reinterpret_cast<const sockaddr_ll*>(item->ifa_addr);
      if (packet_found || link->sll_hatype != ARPHRD_ETHER || link->sll_halen != 6 || link->sll_ifindex <= 0)
        throw std::runtime_error("Management interface link identity is unavailable or ambiguous");
      packet_found = true;
      result.set_interface_index(link->sll_ifindex);
      std::ostringstream mac;
      mac << std::hex << std::setfill('0');
      for (unsigned n = 0; n < 6; ++n) {
        if (n) mac << ':';
        mac << std::setw(2) << unsigned(link->sll_addr[n]);
      }
      result.set_mac_address(mac.str());
    } else if (item->ifa_addr->sa_family == AF_INET) {
      if (!item->ifa_netmask || item->ifa_netmask->sa_family != AF_INET)
        throw std::runtime_error("Management IPv4 prefix is unavailable");
      char address[INET_ADDRSTRLEN];
      const auto* ip = reinterpret_cast<const sockaddr_in*>(item->ifa_addr);
      if (!inet_ntop(AF_INET, &ip->sin_addr, address, sizeof(address)))
        throw std::runtime_error("Management IPv4 formatting failed");
      const auto mask = ntohl(reinterpret_cast<const sockaddr_in*>(item->ifa_netmask)->sin_addr.s_addr);
      unsigned prefix = 0;
      bool zero_seen = false;
      for (int bit = 31; bit >= 0; --bit) {
        if (mask & (uint32_t(1) << bit)) {
          if (zero_seen) throw std::runtime_error("Management IPv4 mask is non-contiguous");
          ++prefix;
        } else zero_seen = true;
      }
      ipv4s.insert(std::string(address) + '/' + std::to_string(prefix));
    }
  }
  if (result.present()) {
    if (!packet_found) throw std::runtime_error("Management interface has no Ethernet identity");
    result.set_interface_up((result.flags_raw() & IFF_UP) != 0);
    result.set_running_flag((result.flags_raw() & IFF_RUNNING) != 0);
    // The selected interface name was validated before this collector is called.
    const auto node = std::filesystem::read_symlink(
        std::filesystem::path("/sys/class/net") / interface / "device/of_node");
    result.set_controller_node(node.filename().string());
  }
  for (const auto& ip : ipv4s) result.add_ipv4_cidrs(ip);
  result.set_quality(daphne::MEASUREMENT_GOOD);
  return result;
}
#endif
}

daphne::ManagementNetworkObservation read_management_network(const daphne::ManagementIdentityBinding& binding) {
  const auto start = monotonic_time_ns();
  daphne::ManagementNetworkObservation result;
  result.set_interface_name(binding.interface_name());
  try {
    // Defend this public collector even if called without the artifact loader.
    if (binding.interface_name().empty() || binding.interface_name().size() >= 16 ||
        binding.interface_name() == "." || binding.interface_name() == ".." ||
        binding.interface_name().find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-") != std::string::npos)
      throw std::runtime_error("Invalid selected management interface");
#ifdef __linux__
    bool stable = false;
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
      const auto first = sample(binding.interface_name());
      const auto link = first.present() ? read_management_link_linux(binding.interface_name(), first.interface_index()) :
                                         daphne::ManagementLinkStatus{};
      const auto second = sample(binding.interface_name());
      if (first.SerializeAsString() != second.SerializeAsString()) continue;
      result = second;
      if (first.present()) *result.mutable_link() = link;
      stable = true;
      break;
    }
    if (!stable) throw std::runtime_error("Management identity changed in all sampled read pairs");
    result.set_message("Two matching Linux getifaddrs/controller observations, not an atomic or authenticated identity; IPv4 scope only");
#else
    result.set_quality(daphne::MEASUREMENT_UNAVAILABLE);
    result.set_message("Management identity collection requires Linux");
#endif
  } catch (const std::exception&) {
    result.Clear();
    result.set_interface_name(binding.interface_name());
    result.set_quality(daphne::MEASUREMENT_ERROR);
    result.set_message("Management identity collection failed; no private exception/path details exported");
  }
  result.set_acquisition_started_monotonic_ns(start);
  result.set_observed_monotonic_ns(monotonic_time_ns());
  result.set_observed_host_unix_ns(host_unix_time_ns());
  return result;
}
}
