#include "server_controller/router_server.hpp"

#include <chrono>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include "Daphne.hpp"
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/serial_executor.hpp"
#include "server_controller/spybuffer_chunker.hpp"
#include "server_controller/v2_envelope.hpp"

namespace daphne_sc {
namespace {
struct Reply { std::string client_id; std::string bytes; };

bool recv_multipart(zmq::socket_t& sock, std::vector<zmq::message_t>& frames) {
  frames.clear();
  while (true) {
    zmq::message_t part;
    if (!sock.recv(part, zmq::recv_flags::none)) return false;
    frames.emplace_back(std::move(part));
    if (!sock.get(zmq::sockopt::rcvmore)) break;
  }
  return true;
}

void send_to(zmq::socket_t& router, const Reply& reply) {
  router.send(zmq::buffer(reply.client_id.data(), reply.client_id.size()), zmq::send_flags::sndmore);
  router.send(zmq::buffer(reply.bytes.data(), reply.bytes.size()), zmq::send_flags::none);
}

Reply error_reply(const std::string& client, const daphne::ControlEnvelopeV2& req, const std::string& error) {
  auto response = v2::make_response(req, v2::response_type(req.type()), {});
  response.set_transport_error(error);
  return {client, response.SerializeAsString()};
}
}

void run_router_server(zmq::context_t& ctx,
                       const std::string& bind_endpoint,
                       Daphne& daphne,
                       const std::unordered_map<daphne::MessageTypeV2, V2Handler>& handlers,
                       const RouterServerOptions& options) {
  if (!daphne.runtime) throw std::invalid_argument("Router requires process bookkeeping state");
  zmq::socket_t router(ctx, ZMQ_ROUTER);
  router.set(zmq::sockopt::linger, 0);
  router.set(zmq::sockopt::sndhwm, options.sndhwm);
  router.set(zmq::sockopt::rcvhwm, options.rcvhwm);
  router.set(zmq::sockopt::sndbuf, options.sndbuf);
  router.set(zmq::sockopt::immediate, options.immediate ? 1 : 0);
  router.bind(bind_endpoint);
  SerialExecutor<Reply> executor(16);

  while (true) {
    daphne.runtime->tick();
    Reply reply;
    for (unsigned n = 0; n < 8 && executor.try_take(reply); ++n) send_to(router, reply);
    zmq::pollitem_t item{router.handle(), 0, ZMQ_POLLIN, 0};
    zmq::poll(&item, 1, std::chrono::milliseconds(10));
    if (!(item.revents & ZMQ_POLLIN)) continue;

    std::vector<zmq::message_t> frames;
    if (!recv_multipart(router, frames) || frames.size() < 2) continue;
    const auto& payload = frames.back();
    if (payload.size() > options.max_envelope_bytes) continue;
    const std::string client_id(static_cast<const char*>(frames.front().data()), frames.front().size());
    daphne::ControlEnvelopeV2 req;
    if (!req.ParseFromArray(payload.data(), static_cast<int>(payload.size())) ||
        req.version() != v2::kControlEnvelopeVersion || req.dir() != daphne::DIR_REQUEST) continue;

    if (req.type() == daphne::MT2_READ_SERVER_STATE_REQ) {
      daphne::ReadServerStateRequest query;
      if (!query.ParseFromString(req.payload())) {
        send_to(router, error_reply(client_id, req, "Bad ReadServerStateRequest payload"));
      } else {
        const auto response = v2::make_response(req, daphne::MT2_READ_SERVER_STATE_RESP,
                                               daphne.runtime->snapshot().SerializeAsString());
        send_to(router, {client_id, response.SerializeAsString()});
      }
      continue;
    }
    if (req.type() != daphne::MT2_DUMP_SPYBUFFER_CHUNK_REQ && handlers.find(req.type()) == handlers.end()) {
      send_to(router, error_reply(client_id, req, "Unsupported request type"));
      continue;
    }
    const bool accepted = executor.try_submit([&, req, client_id](const SerialExecutor<Reply>::Publish& publish) {
      auto respond = [&](daphne::MessageTypeV2 type, const std::string& bytes) {
        const auto env = v2::make_response(req, type, bytes);
        publish({client_id, env.SerializeAsString()});
      };
      daphne.runtime->begin_operation(static_cast<uint32_t>(req.type()), req.task_id(), req.msg_id());
      try {
        if (invalidates_configuration(req.type()))
          daphne.runtime->invalidate("Direct configuration/reset/power operation requested outside the canonical aggregate");
        if (req.type() == daphne::MT2_DUMP_SPYBUFFER_CHUNK_REQ) {
          daphne::DumpSpyBuffersChunkRequest chunk_req;
          if (!chunk_req.ParseFromString(req.payload())) throw std::invalid_argument("Bad DumpSpyBuffersChunkRequest payload");
          for_each_spybuffer_chunk(chunk_req, daphne, [&](const daphne::DumpSpyBuffersChunkResponse& response) {
            respond(daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP, response.SerializeAsString());
          });
        } else {
          std::string bytes;
          handlers.at(req.type())(req.payload(), bytes, daphne);
          respond(v2::response_type(req.type()), bytes);
        }
      } catch (const std::exception& e) {
        if (daphne.runtime->snapshot().configuration_in_progress())
          daphne.runtime->finish_configuration(false, e.what());
        try { publish(error_reply(client_id, req, e.what())); } catch (...) {}
      }
      daphne.runtime->end_operation();
    });
    if (!accepted) send_to(router, error_reply(client_id, req, "Hardware queue full; request was not executed"));
  }
}
}
