#include "server_controller/configuration_fingerprint.hpp"
#include "server_controller/configuration_plan.hpp"
#include <algorithm>
#include <array>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>

namespace daphne_sc {
namespace {
constexpr std::array<uint32_t, 64> kRound{{
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
}};
uint32_t rotate(uint32_t word, unsigned count) { return (word >> count) | (word << (32 - count)); }
}

std::string sha256_hex(const std::string& bytes) {
  std::vector<uint8_t> input(bytes.begin(), bytes.end());
  const auto bits = static_cast<uint64_t>(input.size()) * 8;
  input.push_back(0x80);
  while (input.size() % 64 != 56) input.push_back(0);
  for (int i = 7; i >= 0; --i) input.push_back(static_cast<uint8_t>(bits >> (i * 8)));
  std::array<uint32_t, 8> hash{{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                              0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
  for (size_t block = 0; block < input.size(); block += 64) {
    std::array<uint32_t, 64> words{};
    for (unsigned i = 0; i < 16; ++i) for (unsigned j = 0; j < 4; ++j)
      words[i] = (words[i] << 8) | input[block + 4 * i + j];
    for (unsigned i = 16; i < 64; ++i) {
      const auto x = words[i - 15], y = words[i - 2];
      words[i] = words[i - 16] + (rotate(x,7) ^ rotate(x,18) ^ (x >> 3)) + words[i - 7] +
          (rotate(y,17) ^ rotate(y,19) ^ (y >> 10));
    }
    auto state = hash;
    for (unsigned i = 0; i < 64; ++i) {
      const auto a = state[0], b = state[1], c = state[2], e = state[4], f = state[5], g = state[6];
      const uint32_t t1 = state[7] + (rotate(e,6) ^ rotate(e,11) ^ rotate(e,25)) +
          ((e & f) ^ (~e & g)) + kRound[i] + words[i];
      const uint32_t t2 = (rotate(a,2) ^ rotate(a,13) ^ rotate(a,22)) + ((a & b) ^ (a & c) ^ (b & c));
      for (unsigned j = 7; j > 0; --j) state[j] = state[j - 1];
      state[4] += t1;
      state[0] = t1 + t2;
    }
    for (unsigned i = 0; i < 8; ++i) hash[i] += state[i];
  }
  std::ostringstream out;
  out.imbue(std::locale::classic());
  out << std::hex << std::setfill('0');
  for (auto word : hash) out << std::setw(8) << word;
  return out.str();
}

bool is_complete_configuration(const daphne::ConfigureRequest& config) {
  validate_analog_configuration(config);
  return config.channels_size() == 40 && config.afes_size() == 5;
}

std::string canonical_configuration_evidence(
    const daphne::ConfigureRequest& config, const ConfigurationProfile& profile,
    std::vector<std::pair<uint32_t, uint32_t>> observations) {
  validate_analog_configuration(config);
  validate_gateware_identity(profile.identity, profile.mode);
  const std::vector<uint32_t> streams(config.full_stream_channels().begin(), config.full_stream_channels().end());
  (void)make_mode_register_plan(profile.mode, streams);
  std::sort(observations.begin(), observations.end());
  for (size_t i = 1; i < observations.size(); ++i)
    if (observations[i - 1].first == observations[i].first)
      throw std::invalid_argument("Duplicate configuration observation address");
  std::ostringstream out;
  out.imbue(std::locale::classic());
  out << "daphne-executed-configuration-v2\n";
  out << "profile=" << profile.identity.magic << ',' << profile.identity.abi << ','
      << profile.identity.variant << ',' << profile.identity.build_id << '\n';
  out << "mode=" << gateware_mode_name(profile.mode) << '\n';
  out << "reset=" << profile.reset_enabled << "\nauto_align=" << profile.automatic_alignment << '\n';
  out << "complete=" << is_complete_configuration(config) << '\n';
  // Evidence of DAQ commands must not claim an SC-owned enable was applied.
  out << "biasctrl=" << config.biasctrl() << "\nbias_enable_command=none\n";
  std::vector<daphne::ChannelConfig> channels(config.channels().begin(), config.channels().end());
  std::sort(channels.begin(), channels.end(), [](const auto& a, const auto& b) { return a.id() < b.id(); });
  for (const auto& channel : channels)
    out << "channel=" << channel.id() << ',' << channel.trim() << ',' << channel.offset() << ','
        << (offset_gain_bit(channel.gain()) ? 2 : 1) << '\n';
  std::vector<daphne::AFEConfig> afes(config.afes().begin(), config.afes().end());
  std::sort(afes.begin(), afes.end(), [](const auto& a, const auto& b) { return a.id() < b.id(); });
  for (const auto& afe : afes) {
    out << "afe=" << afe.id() << ',' << afe.attenuators() << ',' << afe.v_bias() << '\n';
    for (const auto& function : make_afe_function_plan(afe))
      out << "function=" << afe.id() << ',' << function.function << ',' << function.value << '\n';
  }
  if (profile.mode == GatewareMode::kSelfTrigger) {
    const auto threshold = config.self_trigger_xcorr() ? (config.self_trigger_xcorr() & 0x0fffffffULL) :
        std::min<uint64_t>(config.self_trigger_threshold(), 0x0fffffffULL);
    out << "threshold_command=" << threshold << '\n';
    // Conditional legacy controls are represented by actual post-application
    // observations below, not by pretending an omitted command wrote zero.
  } else {
    for (size_t i = 0; i < streams.size(); ++i) out << "stream=" << i << ',' << streams[i] << '\n';
  }
  for (const auto& observed : observations)
    out << "observed_control=" << observed.first << ',' << observed.second << '\n';
  return out.str();
}
}
