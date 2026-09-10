#include "server_controller/board_identity.hpp"
#include "server_controller/configuration_fingerprint.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cctype>
#include <climits>
#include <fcntl.h>
#include <map>
#include <regex>
#include <set>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>
#include <google/protobuf/descriptor.h>
#include <google/protobuf/message.h>

namespace daphne_sc {
namespace {
constexpr size_t kMaximumArtifactBytes = 65536;
using Sources = std::map<std::string, std::string>;
void need(bool condition, const char* message) {
  if (!condition) throw std::invalid_argument(message);
}
bool text(const std::string& value, size_t maximum = 256) {
  return !value.empty() && value.size() <= maximum &&
      std::all_of(value.begin(), value.end(), [](unsigned char c) { return c >= 32 && c <= 126; });
}
bool token(const std::string& value) {
  return text(value) && value.find_first_not_of(
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-") == std::string::npos;
}
bool digest(const std::string& value) {
  return value.size() == 64 && value.find_first_not_of("0123456789abcdef") == std::string::npos;
}
bool relative_file(const std::string& value) {
  return text(value) && value.front() != '/' && value.back() != '/' &&
      value.find("..") == std::string::npos && value.find("//") == std::string::npos &&
      value.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-") == std::string::npos;
}
bool ipv4(const std::string& value) {
  static const std::regex format(R"((0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2}))");
  std::smatch match;
  if (!std::regex_match(value, match, format)) return false;
  uint32_t number = 0;
  for (int n = 1; n <= 4; ++n) {
    auto part = std::stoul(match[n]);
    if (part > 255) return false;
    number = (number << 8) | part;
  }
  return number != 0 && number != 0xffffffff && (number >> 24) != 127 &&
      (number >> 28) != 14;
}
bool cidr(const std::string& value) {
  const auto slash = value.find('/');
  if (slash == std::string::npos || !ipv4(value.substr(0, slash))) return false;
  const auto prefix = value.substr(slash + 1);
  return !prefix.empty() && prefix.size() <= 2 &&
      prefix.find_first_not_of("0123456789") == std::string::npos &&
      (prefix.size() == 1 || prefix.front() != '0') && std::stoul(prefix) <= 32;
}
bool mac(const std::string& value) {
  static const std::regex format("[0-9a-f]{2}(:[0-9a-f]{2}){5}");
  return std::regex_match(value, format) && value != "00:00:00:00:00:00" &&
      !(std::stoul(value.substr(0, 2), nullptr, 16) & 1);
}
bool host(const std::string& value) {
  if (value.find_first_not_of("0123456789.") == std::string::npos) return ipv4(value);
  static const std::regex format(R"([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?)");
  return value.size() <= 254 && std::regex_match(value, format);
}
void no_unknown_fields(const google::protobuf::Message& message) {
  const auto* reflection = message.GetReflection();
  need(reflection->GetUnknownFields(message).empty(), "Identity artifact contains unknown fields");
  std::vector<const google::protobuf::FieldDescriptor*> fields;
  reflection->ListFields(message, &fields);
  for (auto* field : fields) {
    if (field->cpp_type() != google::protobuf::FieldDescriptor::CPPTYPE_MESSAGE) continue;
    if (field->is_repeated()) {
      for (int n = 0; n < reflection->FieldSize(message, field); ++n)
        no_unknown_fields(reflection->GetRepeatedMessage(message, field, n));
    } else no_unknown_fields(reflection->GetMessage(message, field));
  }
}
void source_file(const daphne::IdentitySourceFile& file) {
  need(relative_file(file.file()) && digest(file.sha256()) && file.bytes() > 0 &&
       file.bytes() <= 4 * 1024 * 1024, "Invalid identity source-file descriptor");
}
void provenance(const daphne::IdentityValueSource& source, const Sources& sources) {
  const auto found = sources.find(source.file());
  need(found != sources.end() && source.sha256() == found->second &&
       token(source.object_class()) && token(source.object_id()) && token(source.attribute()),
       "Identity value provenance does not match the source manifest");
}
template <typename Value>
bool assigned(const Value& value, const Sources& sources) {
  if (value.has_value()) {
    need(value.has_source() && value.unavailable_reason().empty(), "Assigned identity value has inconsistent provenance/state");
    provenance(value.source(), sources);
    return true;
  }
  need(!value.has_source() && text(value.unavailable_reason(), 512), "Missing identity value requires an explicit unavailable reason");
  return false;
}
template <typename Values, typename Validator>
void list(const Values& values, size_t minimum, size_t maximum, Validator valid) {
  need(static_cast<size_t>(values.size()) >= minimum && static_cast<size_t>(values.size()) <= maximum,
       "Identity list size is outside supported bounds");
  std::set<std::string> seen;
  for (const auto& value : values)
    need(valid(value) && seen.insert(value).second, "Identity list contains an invalid or duplicate value");
}
std::set<std::string> address_set(const google::protobuf::RepeatedPtrField<std::string>& values) {
  return {values.begin(), values.end()};
}
}

void validate_identity_artifact(const daphne::BoardIdentityAssignmentFile& artifact) {
  no_unknown_fields(artifact);
  need(artifact.format_version() == 1 && artifact.has_assignments() && artifact.has_binding(),
       "Unsupported or incomplete identity artifact");
  const auto& a = artifact.assignments();
  need(token(a.application_object_id()) && token(a.board_object_id()), "Missing/invalid database object selectors");
  need(a.sources_size() > 0 && a.sources_size() <= 32, "Invalid identity source count");
  Sources sources;
  std::string manifest = "[", previous;
  for (const auto& file : a.sources()) {
    source_file(file);
    need(file.file() > previous, "Identity source manifest must have unique sorted file names");
    previous = file.file();
    sources.emplace(file.file(), file.sha256());
    if (manifest.size() > 1) manifest += ',';
    // File names and lowercase hashes above cannot contain JSON escapes.
    manifest += "{\"bytes\":" + std::to_string(file.bytes()) + ",\"file\":\"" + file.file() +
                "\",\"sha256\":\"" + file.sha256() + "\"}";
  }
  manifest += ']';
  need(a.source_revision_sha256() == sha256_hex(manifest), "Identity source revision hash disagrees with manifest");
  assigned(a.crate_id(), sources);
  assigned(a.slot_id(), sources);
  assigned(a.detector_id(), sources);
  if (assigned(a.timing_endpoint_address(), sources))
    need(a.timing_endpoint_address().value() <= 65535, "Timing endpoint assignment exceeds 16 bits");
  if (assigned(a.management_address(), sources)) need(host(a.management_address().value()), "Invalid assigned management address");
  if (assigned(a.management_mac_address(), sources)) need(mac(a.management_mac_address().value()), "Invalid assigned management MAC");
  need(a.hermes_interfaces_size() <= 16, "Too many Hermes interface assignments");
  std::set<std::string> interfaces, senders;
  for (const auto& link : a.hermes_interfaces()) {
    need(token(link.connection_object_id()) && token(link.sender_object_id()) && token(link.interface_object_id()) &&
         interfaces.insert(link.interface_object_id()).second && senders.insert(link.sender_object_id()).second,
         "Invalid or duplicate Hermes object selectors");
    list(link.stream_object_ids(), 1, 64, token);
    // Multiple streams may legitimately reference the same GeoId.
    need(link.geo_object_ids_size() == link.stream_object_ids_size(), "Missing Hermes stream placement provenance");
    for (const auto& geo : link.geo_object_ids()) need(token(geo), "Invalid Hermes GeoId selector");
    if (assigned(link.control_host(), sources)) need(host(link.control_host().value()), "Invalid Hermes control host");
    if (assigned(link.mac_address(), sources)) need(mac(link.mac_address().value()), "Invalid Hermes MAC assignment");
    if (link.ip_addresses().values_size()) {
      need(link.ip_addresses().has_source() && link.ip_addresses().unavailable_reason().empty(), "Inconsistent Hermes IP assignment state");
      provenance(link.ip_addresses().source(), sources);
      list(link.ip_addresses().values(), 1, 16, ipv4);
    } else need(!link.ip_addresses().has_source() && text(link.ip_addresses().unavailable_reason(), 512), "Missing Hermes addresses need a reason");
    assigned(link.hermes_link_id(), sources);
    if (assigned(link.physical_connector(), sources)) {
      const std::set<std::string> names{"GTH0", "GTH1", "GTH2", "GTH3"};
      need(names.count(link.physical_connector().value()), "Unsupported Hermes physical connector assignment");
    }
  }
  need(a.limitations_size() > 0 && a.limitations_size() <= 16, "Identity assignment scope/limitations are required");
  for (const auto& limitation : a.limitations()) need(text(limitation, 512), "Invalid identity limitation text");
  const auto& binding = artifact.binding();
  need(token(binding.interface_name()) && binding.interface_name().size() < 16 && binding.interface_name() != "lo",
       "Invalid management interface binding");
  need(std::regex_match(binding.controller_node(), std::regex("ethernet@[0-9a-f]{1,16}")), "Invalid management controller binding");
  need(mac(binding.expected_mac_address()), "Invalid protected management MAC baseline");
  list(binding.expected_ipv4_cidrs(), 1, 16, cidr);
  source_file(binding.approved_link_file());
  source_file(binding.approved_network_file());
  need(binding.approved_link_file().file() != binding.approved_network_file().file(), "Management baseline files must be distinct");
}

LoadedBoardIdentity parse_identity_artifact(const std::string& bytes) {
  need(!bytes.empty() && bytes.size() <= kMaximumArtifactBytes, "Identity artifact exceeds size bounds or is empty");
  LoadedBoardIdentity result;
  need(result.artifact.ParseFromString(bytes), "Cannot parse binary identity artifact");
  validate_identity_artifact(result.artifact);
  // No maps: generated Python/C++ writers share this canonical field order.
  // Reject duplicate fields, unknown wire data and alternate encodings.
  need(result.artifact.SerializeAsString() == bytes, "Identity artifact is not canonically encoded");
  result.artifact_sha256 = sha256_hex(bytes);
  return result;
}

LoadedBoardIdentity load_identity_artifact(const std::string& path) {
  const int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
  need(fd >= 0, "Cannot open private identity artifact");
  std::string bytes;
  try {
    struct stat info{};
    need(fstat(fd, &info) == 0 && S_ISREG(info.st_mode) && (info.st_mode & 0077) == 0 &&
         (info.st_uid == 0 || info.st_uid == geteuid()) && info.st_size > 0 &&
         info.st_size <= static_cast<off_t>(kMaximumArtifactBytes), "Identity artifact must be a bounded private owner/root-owned regular file");
    std::array<char, 4096> chunk;
    for (;;) {
      const auto count = read(fd, chunk.data(), chunk.size());
      if (count < 0 && errno == EINTR) continue;
      need(count >= 0, "Cannot read private identity artifact");
      if (!count) break;
      bytes.append(chunk.data(), count);
      need(bytes.size() <= kMaximumArtifactBytes, "Private identity artifact grew beyond limit");
    }
    need(bytes.size() == static_cast<size_t>(info.st_size), "Private identity artifact changed size during read");
  } catch (...) { close(fd); throw; }
  close(fd);
  return parse_identity_artifact(bytes);
}

daphne::BoardIdentityStatus make_board_identity_status(
    const LoadedBoardIdentity* loaded, const daphne::ManagementNetworkObservation& observed,
    bool include_details, uint64_t now) {
  daphne::BoardIdentityStatus result;
  result.set_observed_monotonic_ns(now);
  result.set_details_included(include_details);
  if (!loaded) {
    result.set_message("No private identity assignment file configured; no assignments or zero values inferred");
    return result;
  }
  result.set_assignment_configured(true);
  result.set_assignment_artifact_sha256(loaded->artifact_sha256);
  result.set_source_revision_sha256(loaded->artifact.assignments().source_revision_sha256());
  const auto& binding = loaded->artifact.binding();
  if (observed.quality() != daphne::MEASUREMENT_GOOD || !observed.has_present() || !now ||
      !observed.observed_monotonic_ns() || observed.observed_monotonic_ns() > now ||
      now - observed.observed_monotonic_ns() > 5'000'000'000ULL) {
    result.set_binding_state(daphne::IDENTITY_BINDING_ERROR);
    result.set_message("Private assignments loaded, but a current management-identity comparison is unavailable; no network writes");
  } else {
    const bool matches = observed.present() && observed.interface_name() == binding.interface_name() &&
        observed.controller_node() == binding.controller_node() && observed.has_mac_address() &&
        observed.mac_address() == binding.expected_mac_address() &&
        address_set(observed.ipv4_cidrs()) == address_set(binding.expected_ipv4_cidrs());
    result.set_binding_state(matches ? daphne::IDENTITY_BINDING_MATCH : daphne::IDENTITY_BINDING_MISMATCH);
    result.set_message(matches ?
        "Management identity matches the protected host baseline. Database values remain assignments, not FPGA readback or authentication; no network writes" :
        "Management identity differs from the private artifact binding. Do not use these assignments for this board without reconciliation; no network writes");
  }
  if (include_details) {
    *result.mutable_assignments() = loaded->artifact.assignments();
    *result.mutable_binding() = binding;
    *result.mutable_management() = observed;
  }
  return result;
}
}
