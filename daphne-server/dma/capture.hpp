#pragma once
#include "daphne_dma_uapi.h"
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace daphne_dma {
enum class Method { Spybuffer, Diagnostic };
Method parse_method(const std::string& value);
struct Layout { uint64_t packet_bytes, total_bytes, blocks; };
Layout validate(const daphne_dma_config& config);
bool active(uint32_t state);
const char* state_name(uint32_t state);

class Backend {
 public:
  virtual ~Backend() = default;
  virtual void prepare(const daphne_dma_config&) = 0;
  virtual void start() = 0;
  virtual void stop() = 0;
  virtual void abort() = 0;
  virtual daphne_dma_status status() = 0;
  virtual daphne_dma_block_info block(uint32_t index) = 0;
  virtual size_t read(void* target, size_t size) = 0;
};

// Streaming checker: packet and beat indices never restart at read boundaries.
class PatternChecker {
 public:
  PatternChecker(uint32_t path, uint32_t beats, uint32_t seed);
  void consume(const void* bytes, size_t count);
  void finish(uint64_t expected_bytes) const;
 private:
  uint32_t path_, beats_, seed_;
  uint64_t words_ = 0, bytes_ = 0;
  uint32_t partial_ = 0;
  unsigned partial_bytes_ = 0;
};

struct Request { uint32_t path; daphne_dma_config config; };
struct Result {
  daphne_dma_status status;
  std::vector<daphne_dma_block_info> blocks;
  bool verified = false;
};
struct Options {
  uint32_t stop_after_ms = 0, abort_after_ms = 0;
  std::function<bool()> cancelled = [] { return false; };
  std::function<void(const daphne_dma_status&)> observe_status;
};
using Factory = std::function<std::unique_ptr<Backend>(uint32_t)>;
// Factory is never invoked for omitted selection / Spybuffer.
std::vector<Result> run(Method method, const std::vector<Request>& requests,
                        const Factory& factory, const Options& options = {});
std::unique_ptr<Backend> linux_backend(uint32_t path);
}
