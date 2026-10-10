#pragma once

#include <cstddef>
#include <atomic>
#include <string>
#include <unordered_map>

#include <zmq.hpp>

#include "server_controller/handlers.hpp"

class Daphne;

namespace daphne_sc {
class DmaService;

struct RouterServerOptions {
  int sndhwm = 20000;
  int sndbuf = 4 * 1024 * 1024;
  int rcvhwm = 20000;
  bool immediate = true;
  size_t max_envelope_bytes = 4 * 1024 * 1024;
  DmaService* dma = nullptr;
  const std::atomic<bool>* stop = nullptr;
};

void run_router_server(zmq::context_t& ctx,
                       const std::string& bind_endpoint,
                       Daphne& daphne,
                       const std::unordered_map<daphne::MessageTypeV2, V2Handler>& handlers,
                       const RouterServerOptions& options);

}  // namespace daphne_sc

