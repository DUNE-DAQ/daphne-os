#include "capture.hpp"
#include <algorithm>
#include <csignal>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <sys/utsname.h>

namespace {
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int) { interrupted = 1; }
uint32_t number(const std::string& s) {
  if (s.empty() || s[0] == '-' || s[0] == '+' || s[0] == ' ')
    throw std::invalid_argument("invalid unsigned value: " + s);
  size_t used;
  auto v = std::stoull(s, &used, 0);
  if (used != s.size() || v > std::numeric_limits<uint32_t>::max())
    throw std::invalid_argument("unsigned value outside 32 bits: " + s);
  return uint32_t(v);
}
std::vector<std::string> split(const std::string& s, char separator) {
  std::vector<std::string> result;
  std::istringstream input(s);
  std::string item;
  while (std::getline(input, item, separator)) result.push_back(item);
  if (result.empty() || s.back() == separator)
    throw std::invalid_argument("empty list item");
  return result;
}
std::string quote(const std::string& s) {
  std::ostringstream out;
  out << '"';
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
    else out << c;
  }
  out << '"';
  return out.str();
}
std::string meminfo() {
  std::ifstream in("/proc/meminfo");
  std::string line, result;
  while (std::getline(in, line))
    if (line.rfind("CmaTotal:", 0) == 0 || line.rfind("CmaFree:", 0) == 0)
      result += line + "\n";
  return result;
}
}
int main(int argc, char** argv) {
  using namespace daphne_dma;
  try {
    std::string method = "spybuffer", routes = "0", rates = "1/1";
    daphne_dma_config config{DAPHNE_DMA_ABI, 1048576, 4, 0, 1, 1, 10000, 0};
    uint32_t repeat = 1;
    bool expected_build = false, validate_only = false;
    Options options;
    std::string command;
    for (int i = 0; i < argc; ++i) command += (i ? " " : "") + std::string(argv[i]);
    for (int i = 1; i < argc; ++i) {
      const std::string flag = argv[i];
      if (flag == "--help") {
        std::cout << "DAPHNE raw-dma diagnostic (NOT AFE samples)\n"
          "No acquisition selection: spybuffer default, no DMA access.\n"
          "--acquisition dma-diagnostic --expected-build-id ID\n"
          "[--routes 0,1,2] [--rates 5/8,5/8,5/16] [--beats N] [--packets N]\n"
          "[--seed N] [--timeout-ms N] [--repeat N] [--validate-only]\n"
          "[--stop-after-ms N | --abort-after-ms N]\n"
          "JSON Lines on stdout; compile/install/overlay loading are separate.\n";
        return 0;
      }
      if (flag == "--validate-only") { validate_only = true; continue; }
      if (i + 1 == argc) throw std::invalid_argument("missing value for " + flag);
      const std::string value = argv[++i];
      if (flag == "--acquisition") method = value;
      else if (flag == "--routes") routes = value;
      else if (flag == "--rates") rates = value;
      else if (flag == "--beats") config.beats = number(value);
      else if (flag == "--packets") config.packets = number(value);
      else if (flag == "--seed") config.seed = number(value);
      else if (flag == "--timeout-ms") config.timeout_ms = number(value);
      else if (flag == "--expected-build-id") {
        config.expected_build_id = number(value); expected_build = true;
      }
      else if (flag == "--repeat") repeat = number(value);
      else if (flag == "--stop-after-ms") options.stop_after_ms = number(value);
      else if (flag == "--abort-after-ms") options.abort_after_ms = number(value);
      else throw std::invalid_argument("unknown option " + flag);
    }
    if (parse_method(method) == Method::Spybuffer) {
      std::cout << "spybuffer remains default; DMA not initialized; use daphneServer for spybuffer acquisition\n";
      return 0;
    }
    if (!expected_build) throw std::invalid_argument("explicit --expected-build-id is required");
    if (!repeat || repeat > 10000 || (options.stop_after_ms && options.abort_after_ms))
      throw std::invalid_argument("invalid repeat count or conflicting STOP/abort options");
    const auto path_list = split(routes, ',');
    const auto rate_list = split(rates, ',');
    if (rate_list.size() != 1 && rate_list.size() != path_list.size())
      throw std::invalid_argument("rates must contain one fraction or one per selected route");
    std::vector<Request> requests;
    uint64_t total = 0;
    for (size_t i = 0; i < path_list.size(); ++i) {
      const auto path = number(path_list[i]);
      if (path > 2 || std::any_of(requests.begin(), requests.end(),
          [path](const Request& r) { return r.path == path; }))
        throw std::invalid_argument("invalid or duplicate route");
      const auto rate = split(rate_list[rate_list.size() == 1 ? 0 : i], '/');
      if (rate.size() != 2) throw std::invalid_argument("rate requires numerator/denominator");
      auto c = config;
      c.rate_num = number(rate[0]); c.rate_den = number(rate[1]);
      total += validate(c).total_bytes;
      requests.push_back({path, c});
    }
    if (total > uint64_t(480) * 1024 * 1024)
      throw std::invalid_argument("combined request exceeds maximum diagnostic pool");
    if (validate_only) {
      std::cout << "{\"hardware\":false,\"validation\":\"pass\",\"payload_bytes\":"
        << total << ",\"note\":\"allocation and hardware not tested\"}\n";
      return 0;
    }
    std::signal(SIGINT, interrupt); std::signal(SIGTERM, interrupt);
    options.cancelled = [] { return interrupted != 0; };
    options.observe_status = [](const daphne_dma_status& s) {
      if (s.error || s.state == DAPHNE_DMA_ERROR || s.state == DAPHNE_DMA_QUARANTINED)
        std::cout << "{\"event\":\"route_failure\",\"path\":" << s.path
          << ",\"state\":" << quote(state_name(s.state)) << ",\"error\":" << s.error
          << ",\"dma_control\":" << s.dma_control << ",\"dma_status\":" << s.dma_status
          << ",\"producer_status\":" << s.producer_status << ",\"accepted_beats\":" << s.accepted_beats
          << ",\"producer_packets\":" << s.producer_packets << ",\"completed_packets\":" << s.completed_packets
          << ",\"received_bytes\":" << s.received_bytes << ",\"allocated_bytes\":" << s.allocated_bytes
          << ",\"guards_ok\":" << s.guards_ok << "}\n" << std::flush;
    };
    struct utsname kernel{};
    if (uname(&kernel)) throw std::runtime_error("cannot read kernel identity");
    std::cout << "{\"event\":\"begin\",\"hardware\":true,\"command\":" << quote(command)
      << ",\"kernel\":" << quote(kernel.release) << ",\"machine\":" << quote(kernel.machine)
      << ",\"cma_before\":" << quote(meminfo()) << ",\"repeat\":" << repeat << "}\n" << std::flush;
    for (uint32_t iteration = 0; iteration < repeat; ++iteration) {
      const auto results = run(Method::Diagnostic, requests, linux_backend, options);
      uint64_t begin = std::numeric_limits<uint64_t>::max(), end = 0, bytes = 0;
      bool verified = true, saw_abort = false;
      for (size_t i = 0; i < results.size(); ++i) {
        const auto& r = results[i]; const auto& s = r.status;
        const auto& c = requests[i].config;
        verified &= r.verified;
        saw_abort |= s.state == DAPHNE_DMA_ABORTED;
        begin = std::min<uint64_t>(begin, s.start_ns); end = std::max<uint64_t>(end, s.end_ns);
        bytes += s.received_bytes;
        const double seconds = s.start_ns && s.end_ns > s.start_ns ? double(s.end_ns - s.start_ns) / 1e9 : 0;
        std::cout << std::setprecision(12) << "{\"event\":\"route\",\"iteration\":" << iteration
          << ",\"path\":" << s.path << ",\"state\":" << quote(state_name(s.state))
          << ",\"verified\":" << (r.verified ? "true" : "false")
          << ",\"build_id\":" << s.build_id << ",\"capabilities\":" << s.capabilities
          << ",\"beats\":" << c.beats << ",\"packets\":" << c.packets << ",\"seed\":" << c.seed
          << ",\"rate_num\":" << c.rate_num << ",\"rate_den\":" << c.rate_den
          << ",\"timeout_ms\":" << c.timeout_ms << ",\"requested_bytes\":" << s.requested_bytes
          << ",\"allocated_bytes\":" << s.allocated_bytes << ",\"received_bytes\":" << s.received_bytes
          << ",\"completed_packets\":" << s.completed_packets << ",\"accepted_beats\":" << s.accepted_beats
          << ",\"producer_packets\":" << s.producer_packets << ",\"producer_status\":" << s.producer_status
          << ",\"dma_control\":" << s.dma_control << ",\"dma_status\":" << s.dma_status
          << ",\"guards_ok\":" << s.guards_ok << ",\"start_ns\":" << s.start_ns
          << ",\"end_ns\":" << s.end_ns << ",\"seconds\":" << seconds
          << ",\"bytes_per_second\":" << (seconds ? s.received_bytes / seconds : 0)
          << ",\"buffers\":[";
        for (size_t b = 0; b < r.blocks.size(); ++b) {
          const auto& block = r.blocks[b];
          if (b) std::cout << ',';
          std::cout << "{\"dma_address\":" << block.dma_address << ",\"length\":" << block.length
            << ",\"offset\":" << block.logical_offset << '}';
        }
        std::cout << "]}\n";
      }
      const double seconds = begin && end > begin ? double(end - begin) / 1e9 : 0;
      std::cout << "{\"event\":\"combined\",\"iteration\":" << iteration
        << ",\"verified\":" << (verified ? "true" : "false") << ",\"received_bytes\":" << bytes
        << ",\"seconds\":" << seconds << ",\"bytes_per_second\":" << (seconds ? bytes / seconds : 0)
        << ",\"cma_after_close\":" << quote(meminfo()) << "}\n" << std::flush;
      if (interrupted) return 130;
      if (!verified && !(saw_abort && options.abort_after_ms))
        throw std::runtime_error("capture did not verify");
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "DMA diagnostic failed: " << e.what() << '\n';
    std::cout << "{\"event\":\"failure\",\"error\":" << quote(e.what()) << "}\n";
    return interrupted ? 130 : 1;
  }
}
