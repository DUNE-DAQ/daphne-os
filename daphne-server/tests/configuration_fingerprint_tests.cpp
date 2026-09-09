#include "server_controller/configuration_fingerprint.hpp"
#include <iostream>
#include <stdexcept>

void require(bool ok) { if (!ok) throw std::runtime_error("Configuration-fingerprint assertion failed"); }
int main() {
  using namespace daphne_sc;
  require(sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  require(sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  require(sha256_hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq") ==
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  require(sha256_hex(std::string(1000000, 'a')) == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
  daphne::ConfigureRequest config;
  for (unsigned i = 0; i < 40; ++i) { auto* ch = config.add_channels(); ch->set_id(i); ch->set_offset(2200); }
  for (unsigned i = 0; i < 5; ++i) { auto* afe = config.add_afes(); afe->set_id(i); afe->set_attenuators(1700); }
  ConfigurationProfile profile{{0x44415048, 0x20000, 1, 0x3f17f1b}, GatewareMode::kSelfTrigger, true, true};
  auto fingerprint = [&](const auto& request) { return sha256_hex(canonical_configuration_evidence(request, profile, {{0x9400002c, 0}})); };
  const auto original = fingerprint(config);
  require(is_complete_configuration(config));
  auto permuted = config;
  permuted.mutable_channels()->SwapElements(0, 39);
  permuted.mutable_afes()->SwapElements(0, 4);
  require(fingerprint(permuted) == original);
  permuted.set_daphne_address("ignored-client-destination");
  permuted.set_slot(7);
  permuted.set_timeout_ms(1234);
  for (auto& ch : *permuted.mutable_channels()) ch.set_gain(1);
  require(fingerprint(permuted) == original);
  permuted.mutable_channels(0)->set_offset(2199);
  require(fingerprint(permuted) != original);
  profile.identity.build_id++;
  require(fingerprint(config) != original);
  profile.identity.build_id--;
  require(sha256_hex(canonical_configuration_evidence(config, profile, {{0x9400002c, 1}})) != original);
  config.mutable_afes()->RemoveLast();
  require(!is_complete_configuration(config));
  bool rejected = false;
  try { (void)canonical_configuration_evidence(config, profile, {{1,2},{1,3}}); }
  catch (const std::invalid_argument&) { rejected = true; }
  require(rejected);
  profile.mode = GatewareMode::kFullStream;
  profile.identity.variant = 2;
  config.add_full_stream_channels(0);
  config.add_full_stream_channels(9);
  const auto stream_order = fingerprint(config);
  config.set_full_stream_channels(0, 9);
  config.set_full_stream_channels(1, 0);
  require(fingerprint(config) != stream_order);
  const auto reordered = fingerprint(config);
  config.set_self_trigger_threshold(123); // Ignored in full-stream mode.
  config.set_inverters(999);
  require(fingerprint(config) == reordered);
  std::cout << "SHA-256 vectors, canonical ordering, effective gain, ignored fields, profile and observation evidence checks passed\n";
}
