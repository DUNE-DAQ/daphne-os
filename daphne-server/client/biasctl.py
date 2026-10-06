#!/usr/bin/env python3
"""Targeted DAPHNE V2 bias commands; never sends CONFIGURE_FE.

Run from the repository root after generating matching Python protobuf bindings:
  python daphne-server/client/biasctl.py --ip "$BOARD_IP" status
  python daphne-server/client/biasctl.py --ip "$BOARD_IP" set-afe-dac --afe 4 --dac CODE
  python daphne-server/client/biasctl.py --ip "$BOARD_IP" set-global --dac CODE --enable yes
  python daphne-server/client/biasctl.py --ip "$BOARD_IP" set-afe --afe 4 --volts VOLTS

CODE and VOLTS are placeholders for the intended settings. Feedback control
requires working onboard ADC monitoring. A failed feedback command may already
have changed the AFE DAC; inspect its response before retrying. DAC readbacks
are server cache values, not independently measured DAC voltages.
"""
import argparse
import json
import math
import os
import sys
import time
import zmq
from google.protobuf.json_format import MessageToDict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as low


def dac_code(value):
    try:
        code = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('DAC code must be an integer') from exc
    if not 0 <= code <= 4095:
        raise argparse.ArgumentTypeError('DAC code must be in 0..4095')
    return code


def exchange(sock, request, req_type, resp_type, response_cls, route):
    ident = time.time_ns() & ((1 << 63) - 1)
    env = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST,
        type=req_type, task_id=ident, msg_id=ident, timestamp_ns=time.time_ns(),
        route=route, payload=request.SerializeToString())
    sock.send(env.SerializeToString())
    reply = high.ControlEnvelopeV2.FromString(sock.recv_multipart()[-1])
    if (reply.version != 2 or reply.dir != high.DIR_RESPONSE or
        reply.type != resp_type or reply.task_id != ident or reply.correl_id != ident):
        raise RuntimeError('Response envelope type or correlation mismatch')
    out = response_cls.FromString(reply.payload)
    if not out.success:
        raise RuntimeError(json.dumps(MessageToDict(out, preserving_proto_field_name=True)))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--ip', required=True)
    p.add_argument('--port', type=int, default=40001)
    p.add_argument('--route', default='mezz/0')
    p.add_argument('--timeout', type=int, default=15000)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='Read cached setpoints and bias ADC monitoring')
    a = sub.add_parser('set-afe', help='Use server feedback for just one AFE')
    a.add_argument('--afe', type=int, choices=range(5), required=True)
    a.add_argument('--volts', type=float, required=True)
    a.add_argument('--tolerance-mv', type=int, default=20)
    a.add_argument('--settling-ms', type=int, default=2000)
    d = sub.add_parser('set-afe-dac', help='Write only one AFE DAC, without voltage feedback')
    d.add_argument('--afe', type=int, choices=range(5), required=True)
    d.add_argument('--dac', type=dac_code, required=True)
    g = sub.add_parser('set-global', help='Explicitly change global DAC and enable')
    g.add_argument('--dac', type=dac_code, required=True)
    g.add_argument('--enable', choices=['yes', 'no'], required=True)
    args = p.parse_args()
    if args.timeout <= 0:
        p.error('--timeout must be positive')
    if args.command == 'set-afe':
        if not math.isfinite(args.volts) or not 0 <= args.volts <= 75:
            p.error('--volts must be finite and in the schematic supply range 0..75 V')
        if args.tolerance_mv <= 0 or not 0 < args.settling_ms < args.timeout:
            p.error('Tolerance must be positive; settling time must be below socket timeout')
    with zmq.Context() as ctx:
        with ctx.socket(zmq.DEALER) as sock:
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, args.timeout)
            sock.setsockopt(zmq.SNDTIMEO, args.timeout)
            sock.connect(f'tcp://{args.ip}:{args.port}')
            def call(req, stem, cls):
                return exchange(sock, req, getattr(high, 'MT2_'+stem+'_REQ'),
                    getattr(high, 'MT2_'+stem+'_RESP'), cls, args.route)
            if args.command == 'status':
                raw = call(low.cmd_readVbiasControl(), 'READ_VBIAS_CONTROL', low.cmd_readVbiasControl_response)
                result = {'global_dac_cached': raw.vBiasControlValue,
                    'note': 'DAC values are server cache; bias monitor readings are cached ADC samples with no freshness timestamp.',
                    'afes': []}
                for afe in range(5):
                    dac = call(low.cmd_readAFEBiasSet(afeBlock=afe), 'READ_AFE_BIAS_SET', low.cmd_readAFEBiasSet_response)
                    monitor = call(low.cmd_readBiasVoltageMonitor(afeBlock=afe), 'READ_BIAS_VOLTAGE_MONITOR', low.cmd_readBiasVoltageMonitor_response)
                    result['afes'].append({'afe': afe, 'dac_cached': dac.biasValue,
                        'bias_monitor_mv_cached': monitor.biasVoltageValue, 'monitor_message': monitor.message})
                print(json.dumps(result, indent=2))
            elif args.command == 'set-global':
                out = call(low.cmd_writeVbiasControl(vBiasControlValue=args.dac, enable=args.enable=='yes'),
                    'WRITE_VBIAS_CONTROL', low.cmd_writeVbiasControl_response)
                print(json.dumps(MessageToDict(out, preserving_proto_field_name=True), indent=2))
            elif args.command == 'set-afe-dac':
                out = call(low.cmd_writeAFEBiasSet(afeBlock=args.afe, biasValue=args.dac),
                    'WRITE_AFE_BIAS_SET', low.cmd_writeAFEBiasSet_response)
                print(json.dumps({'response': MessageToDict(out, preserving_proto_field_name=True),
                    'voltage_verified': False}, indent=2))
            else:
                req = low.cmd_writeAFEBiasControlledSet(afe_block=args.afe,
                    target_bias_mv=round(args.volts*1000), tolerance_mv=args.tolerance_mv,
                    settling_time_ms=args.settling_ms, dwell_time_ms=100,
                    samples_per_read=4, max_iterations=20, max_dac_step=64,
                    slope_tolerance_mv_per_s=5, required_stable_samples=2)
                out = call(req, 'WRITE_AFE_BIAS_CONTROLLED_SET', low.cmd_writeAFEBiasControlledSet_response)
                print(json.dumps(MessageToDict(out, preserving_proto_field_name=True), indent=2))
                if (not out.settled or out.status != low.AFE_BIAS_CONTROL_STATUS_SETTLED
                    or abs(out.error_mv) > args.tolerance_mv
                    or abs(out.measured_bias_mv-req.target_bias_mv) > args.tolerance_mv):
                    raise RuntimeError('Target was not confirmed settled within tolerance; DAC may have changed. Inspect response before retrying.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, zmq.ZMQError) as exc:
        print(json.dumps({'error': str(exc)}))
        raise SystemExit(1)
