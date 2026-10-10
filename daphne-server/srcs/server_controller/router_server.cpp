#include "server_controller/router_server.hpp"

#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include "Daphne.hpp"
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/spybuffer_chunker.hpp"
#include "server_controller/v2_envelope.hpp"
#include "server_controller/dma_service.hpp"
#include "server_controller/hardware_admission.hpp"

namespace daphne_sc {
namespace {

bool recv_multipart(zmq::socket_t& sock, std::vector<zmq::message_t>& frames) {
  frames.clear();
  while (true) {
    zmq::message_t part;
    if (!sock.recv(part, zmq::recv_flags::none)) return false;
    frames.emplace_back(std::move(part));
    const bool more = sock.get(zmq::sockopt::rcvmore);
    if (!more) break;
  }
  return true;
}

void send_to(zmq::socket_t& router, const std::string& client_id, const std::string& bytes) {
  router.send(zmq::buffer(client_id.data(), client_id.size()), zmq::send_flags::sndmore);
  router.send(zmq::buffer(bytes.data(), bytes.size()), zmq::send_flags::none);
}

}  // namespace

void run_router_server(zmq::context_t& ctx,
                       const std::string& bind_endpoint,
                       Daphne& daphne,
                       const std::unordered_map<daphne::MessageTypeV2, V2Handler>& handlers,
                       const RouterServerOptions& options) {
  zmq::socket_t router(ctx, ZMQ_ROUTER);
  router.set(zmq::sockopt::linger, 0);
  router.set(zmq::sockopt::sndhwm, options.sndhwm);
  router.set(zmq::sockopt::rcvhwm, options.rcvhwm);
  router.set(zmq::sockopt::sndbuf, options.sndbuf);
  router.set(zmq::sockopt::immediate, options.immediate ? 1 : 0);
  if (options.dma) {
    router.set(zmq::sockopt::sndtimeo, 100);
    router.set(zmq::sockopt::sndhwm, 8);
    router.set(zmq::sockopt::rcvhwm, 64);
    router.set(zmq::sockopt::maxmsgsize, static_cast<int64_t>(options.max_envelope_bytes));
  }
  router.bind(bind_endpoint);

  while (!options.stop || !options.stop->load()) {
    if (options.dma) options.dma->expire();
    zmq::pollitem_t item{router.handle(), 0, ZMQ_POLLIN, 0};
    try { zmq::poll(&item, 1, std::chrono::milliseconds(50)); }
    catch (const zmq::error_t& e) { if (e.num() == EINTR) continue; throw; }
    if (!(item.revents & ZMQ_POLLIN)) continue;
    std::vector<zmq::message_t> frames;
    if (!recv_multipart(router, frames)) continue;
    if (frames.size() < 2) continue;

    const zmq::message_t& id_frame = frames.front();
    const zmq::message_t& payload = frames.back();

    if (payload.size() > options.max_envelope_bytes) {
      continue;
    }

    const std::string client_id(static_cast<const char*>(id_frame.data()), id_frame.size());

    daphne::ControlEnvelopeV2 req;
    if (!req.ParseFromArray(payload.data(), static_cast<int>(payload.size()))) {
      daphne::ControlEnvelope legacy;
      if (legacy.ParseFromArray(payload.data(), static_cast<int>(payload.size()))) {
        std::cerr << "Received deprecated v1 ControlEnvelope from client '" << client_id
                  << "' (type=" << legacy.type() << "); v2-only server ignores it." << std::endl;
      }
      continue;
    }

    if (req.version() != 2 || req.dir() != daphne::DIR_REQUEST) {
      continue;
    }

    if (options.dma) {
      std::string response;
      if (options.dma->dispatch(req, client_id, response)) {
        send_to(router, client_id, v2::make_response(req, v2::response_type(req.type()), std::move(response)).SerializeAsString());
        continue;
      }
      // Controls share one hardware owner with acquisition and calibration.
      if (options.dma->busy()) {
        send_to(router, client_id, v2::make_response(req, v2::response_type(req.type()),
                control_error_payload(req.type(), "BUSY: DMA owns the hardware")).SerializeAsString());
        continue;
      }
      try { options.dma->verify_live(); }
      catch (const std::exception& e) {
        options.dma->invalidate(true);
        send_to(router, client_id, v2::make_response(req, v2::response_type(req.type()),
                control_error_payload(req.type(), e.what())).SerializeAsString());
        continue;
      }
      const int t = static_cast<int>(req.type());
      // All writes, resets, clocks, power and manual timing invalidate evidence,
      // including requests that fail after a partial hardware update.
      const bool read_only = (t >= 224 && t <= 246) || t == 304 || t == 322 || t == 404 || t == 408;
      if (!read_only) options.dma->invalidate();
    } else if (req.type() == daphne::MT2_ACQUISITION_CAPABILITIES_REQ) {
      daphne::AcquisitionCapabilitiesResponse response;
      response.set_success(true); response.set_protocol_revision(1);
      response.set_backend(daphne::ACQUISITION_SPYBUFFER);
      response.add_available_backends(daphne::ACQUISITION_SPYBUFFER);
      response.set_maximum_samples(2048);
      send_to(router, client_id, v2::make_response(req, daphne::MT2_ACQUISITION_CAPABILITIES_RESP,
              response.SerializeAsString()).SerializeAsString());
      continue;
    } else if (static_cast<int>(req.type()) >= 338 && static_cast<int>(req.type()) <= 346) {
      send_to(router, client_id, v2::make_response(req, v2::response_type(req.type()),
              control_error_payload(req.type(), "BACKEND_MISMATCH: server has no DMA backend")).SerializeAsString());
      continue;
    }

    if (req.type() == daphne::MT2_DUMP_SPYBUFFER_CHUNK_REQ) {
      if (!daphne.hasSpyBuffer()) {
        daphne::DumpSpyBuffersChunkResponse response;
        response.set_success(false); response.set_isfinal(true);
        response.set_message("SPYBUFFER_UNAVAILABLE: raw-dma backend");
        send_to(router, client_id, v2::make_response(req, daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP,
                response.SerializeAsString()).SerializeAsString());
        continue;
      }
      daphne::DumpSpyBuffersChunkRequest chunk_req;
      if (!chunk_req.ParseFromString(req.payload())) {
        daphne::DumpSpyBuffersChunkResponse chunk_resp;
        chunk_resp.set_success(false);
        chunk_resp.set_message("Bad DumpSpyBuffersChunkRequest payload");
        chunk_resp.set_isfinal(true);
        const auto env = v2::make_response(req, daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP, chunk_resp.SerializeAsString());
        send_to(router, client_id, env.SerializeAsString());
        continue;
      }

      try {
        for_each_spybuffer_chunk(chunk_req, daphne, [&](const daphne::DumpSpyBuffersChunkResponse& resp) {
          const auto env = v2::make_response(req, daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP, resp.SerializeAsString());
          send_to(router, client_id, env.SerializeAsString());
        });
      } catch (const std::exception& e) {
        daphne::DumpSpyBuffersChunkResponse chunk_resp;
        chunk_resp.set_success(false);
        chunk_resp.set_message(std::string("Chunked dump failed: ") + e.what());
        chunk_resp.set_isfinal(true);
        const auto env = v2::make_response(req, daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP, chunk_resp.SerializeAsString());
        send_to(router, client_id, env.SerializeAsString());
      }

      continue;
    }

    const auto it = handlers.find(req.type());
    if (it == handlers.end()) {
      std::cerr << "No handler for MessageTypeV2=" << static_cast<int>(req.type()) << std::endl;
      const auto env = v2::make_response(req, v2::response_type(req.type()), std::string{});
      send_to(router, client_id, env.SerializeAsString());
      continue;
    }

    std::string resp_payload;
    try {
      it->second(req.payload(), resp_payload, daphne);
      if (options.dma && req.type() == daphne::MT2_CONFIGURE_FE_REQ) {
        daphne::ConfigureResponse response;
        daphne::ConfigureRequest configuration;
        if (response.ParseFromString(resp_payload) && response.success() && configuration.ParseFromString(req.payload()))
          options.dma->configured(configuration);
      }
    } catch (const std::exception& e) {
      std::cerr << "Handler threw exception: " << e.what() << std::endl;
      const auto env = v2::make_response(req, v2::response_type(req.type()), std::string{});
      send_to(router, client_id, env.SerializeAsString());
      continue;
    }

    const auto env = v2::make_response(req, v2::response_type(req.type()), std::move(resp_payload));
    send_to(router, client_id, env.SerializeAsString());
  }
}

}  // namespace daphne_sc
