#!/usr/bin/env python3
"""Prepare and verify the qualified DMA frontend through localhost RPC."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

RUNTIME = Path('/opt/daphne-dma-persistent-manual-20261012')
os.environ['DAPHNE_PROTO_PYTHON_DIR'] = str(RUNTIME / 'protobuf')
SOURCE_CLIENT = Path(__file__).resolve().parents[2] / 'daphne-server/client'
if SOURCE_CLIENT.is_dir():
    sys.path.insert(0, str(SOURCE_CLIENT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('dependencies', 'prepare', 'status'))
    from identity_cli import add_identity_argument
    add_identity_argument(parser)
    args = parser.parse_args()
    from google.protobuf.json_format import MessageToDict
    from protobuf_loader import load_protobuf_modules
    from v2_client import V2Client
    from dma_client import DmaClient
    from configure_fe_min_v2 import make_default_config, set_adc_fields
    pb, low = load_protobuf_modules(require_dma=True)
    if not hasattr(pb, 'DMA_CAPTURE_PERSISTENT'):
        raise RuntimeError('Persistent bindings are required')
    if args.command == 'dependencies':
        print('DMA frontend dependencies and revision-3 bindings OK')
        return
    with V2Client(pb, '127.0.0.1', 40001, timeout_ms=10000,
                  identity=args.identity or 'manual-mode-'+str(os.getpid())) as link:
        client = DmaClient(pb, link.rpc)
        caps = client.probe('software', 'persistent')
        if caps.gateware_build_id != 0x0630a9da:
            raise RuntimeError('Unexpected DMA image')
        evidence = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        if args.command == 'prepare':
            directory = Path('/var/lib/daphne-manual-mode') / ('frontend-'+time.strftime('%Y%m%d-%H%M%S'))
            directory.mkdir(parents=True, exist_ok=False)
            cfg = make_default_config(ip='193.206.157.36', timeout_ms=30000, vgain=1700,
                per_ch_offset=2275, per_ch_trim=0, biasctrl=1300,
                lpf_cutoff=4, pga_clamp_level=0, pga_gain=0, lna_gain=2, lna_clamp=2)
            cfg.backend = pb.ACQUISITION_DMA
            cfg.alignment_policy = pb.ALIGNMENT_SKIP
            for afe in cfg.afes:
                set_adc_fields(afe.adc, resolution=False, output_format=False, sb_first=False)
                afe.pga.clamp = 0
            (directory / 'configuration-request.json').write_text(json.dumps(MessageToDict(cfg), indent=2)+'\n')
            response = link.rpc(pb.MT2_CONFIGURE_FE_REQ, cfg, pb.MT2_CONFIGURE_FE_RESP, pb.ConfigureResponse)
            evidence['configuration_response'] = MessageToDict(response, preserving_proto_field_name=True)
            if not response.success or not response.configured or response.backend != pb.ACQUISITION_DMA:
                raise RuntimeError('DMA frontend configuration failed: '+response.message)
            evidence['alignment'] = []
            for afe in range(5):
                request = pb.AfeDelaySweepRequest(backend=pb.ACQUISITION_DMA, afes=[afe],
                    firstTap=0, lastTap=511, tapStep=4, numberOfSamples=2048,
                    numberOfWaveforms=1, settleTimeUs=2000, coarse_step=16,
                    apply_best=True, verification_samples=32768, timeout_ms=600000)
                try:
                    print(f'Measuring AFE{afe}, including 32768-sample physical ramp verification', flush=True)
                    result = client.scan(request)
                    evidence['alignment'].append(MessageToDict(result, preserving_proto_field_name=True))
                    if (not result.success or len(result.afes) != 1 or result.afes[0].afe != afe or
                            result.afes[0].approved_lane_mask != 255 or not result.afes[0].applied):
                        raise RuntimeError(f'AFE{afe} has no measured, applied eight-lane eye')
                    client.acknowledge()
                except Exception as error:
                    evidence['alignment_error'] = {'afe': afe, 'message': str(error)}
                    raise
                finally:
                    client.cancel()
                    (directory / 'alignment.json').write_text(json.dumps(evidence, indent=2)+'\n')
            print('Measured DMA alignment saved to '+str(directory))
        caps = client.probe('software', 'persistent')
        # Check the actual frontend admission cache, rather than reusing old taps.
        states = caps.afes
        if {s.afe for s in states} != set(range(5)) or any(
                s.state != pb.FRONTEND_ALIGNED or s.approved_lane_mask != 255 for s in states):
            print(json.dumps({'ready': False, 'frontends': [MessageToDict(s, preserving_proto_field_name=True) for s in states]}, indent=2))
            raise RuntimeError('DMA frontend admission is not fully aligned')
        vgain = []
        for afe in range(5):
            value = link.rpc(pb.MT2_READ_AFE_VGAIN_REQ, low.cmd_readAFEVgain(afeBlock=afe),
                pb.MT2_READ_AFE_VGAIN_RESP, low.cmd_readAFEVgain_response)
            if not value.success or (args.command == 'prepare' and value.vgainValue != 1700):
                raise RuntimeError(f'VGAIN readback failed for AFE{afe}')
            vgain.append(value.vgainValue)
        evidence['capabilities'] = MessageToDict(caps, preserving_proto_field_name=True)
        evidence['vgain'] = vgain
        if args.command == 'prepare':
            (directory / 'ready.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'ready': True, 'build_id': hex(caps.gateware_build_id),
            'session_abi': caps.session_abi, 'features': caps.session_features,
            'frontends': [MessageToDict(s, preserving_proto_field_name=True) for s in states],
            'vgain': vgain}, indent=2))


if __name__ == '__main__':
    main()
