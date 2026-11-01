"""DMA implementation of the acquire-list CLI; legacy path remains separate."""
import json
from pathlib import Path
import tarfile
import subprocess
import sys
import uuid
import time
from dma_client import DmaClient
from dma_cli_signals import DmaCliSignals
from dma_output import prepare_dma_output, record_dma_output
from v2_client import V2Client
from tqdm import tqdm
from cli_presentation import print_acquisition_start, print_acquisition_done
from dma_options import capture_contract, phase_text


def run_dma_acquire(args, pb):
    if not args.v2 or args.legacy or args.legacy_only:
        raise ValueError("--dma requires EnvelopeV2; omit legacy flags")
    channels = [int(v) for token in args.channel_list for v in token.split(',') if v.strip()]
    if args.N <= 0 or args.chunk <= 0:
        raise ValueError("N and chunk must be positive")
    folder = Path(args.foldername)
    files = {}
    completed = 0
    metadata_path = folder / ("dma_metadata_" + uuid.uuid4().hex + ".jsonl")
    contract = capture_contract(args)
    mode, pretrigger = contract['capture_mode'], contract['pretrigger_samples']
    with DmaCliSignals() as signals, V2Client(pb, args.ip, args.port, route=args.route, timeout_ms=args.timeout_ms,
                  identity="dma-acquire-" + uuid.uuid4().hex) as transport:
        client = DmaClient(pb, transport.rpc, stop_checker=signals.stop_requested)
        client.probe(args.trigger_source, mode, pretrigger)
        client._check_force_acq(getattr(args, 'force_acq', False))
        print_acquisition_start(args, channels, 'dma')
        batch = min(args.chunk, client.batch_limit(channels, args.L, mode, pretrigger))
        if getattr(args, "osc_mode", False):
            batch = 1
        prepare_dma_output(folder, channels, args.append_data, contract)
        offsets = {str(ch): (folder / f'channel_{ch}.dat').stat().st_size // (2*args.L)
                   if args.append_data and (folder / f'channel_{ch}.dat').is_file() else 0 for ch in channels}
        if mode in ('triggered', 'persistent'):
            print(f'DMA {mode}: N={args.N}, L={args.L}, P={pretrigger}, trigger sample={pretrigger}, source={args.trigger_source}')
            if args.trigger_source in ('external', 'timing'):
                print(f'DMA {args.trigger_source}: experimental source; waiting for an event from hardware')
        try:
            acquisition_begin = time.monotonic()
            disk_write_s = 0.
            for ch in channels:
                files[ch] = (folder / f"channel_{ch}.dat").open("ab" if args.append_data else "wb")
            record_dma_output(folder, channels, contract)
            with metadata_path.open("w", encoding="utf-8") as metadata_file, tqdm(total=args.N, unit='wf') as pbar:
                if mode == 'triggered':
                    def progress(done, total, phase):
                        pbar.update(max(0, completed + done - pbar.n))
                        pbar.set_postfix_str(phase_text(pb, phase))
                    client.progress_callback = progress
                if mode == 'persistent':
                    client.start_session(channels, args.L, args.N, args.trigger_source,
                        timeout_ms=getattr(args, 'trigger_timeout_ms', 30000), pretrigger=pretrigger,
                        job_timeout_ms=getattr(args, 'job_timeout_ms', 0),
                        pressure_timeout_ms=getattr(args, 'pressure_timeout_ms', 0),
                        force_acq=getattr(args, 'force_acq', False))
                while completed < args.N:
                    n = min(batch, args.N - completed)
                    if mode == 'persistent':
                        data, metadata = client.read_batch(n)
                        n = data.shape[0]
                    else:
                        data, metadata = client.acquire(channels, args.L, n, args.trigger_source,
                            timeout_ms=getattr(args, 'trigger_timeout_ms', 10000), capture_mode=mode,
                            pretrigger=pretrigger, job_timeout_ms=getattr(args, 'job_timeout_ms', 0),
                            force_acq=getattr(args, 'force_acq', False))
                    disk_begin = time.monotonic()
                    for i, ch in enumerate(channels):
                        files[ch].write(data[:, i, :].astype("<u2", copy=False).tobytes())
                        files[ch].flush()
                    metadata["first_waveform"] = completed
                    metadata['file_first_waveform'] = {ch: start + completed for ch, start in offsets.items()}
                    metadata_file.write(json.dumps(metadata) + "\n")
                    metadata_file.flush()
                    disk_write_s += time.monotonic() - disk_begin
                    if mode == 'persistent':
                        client.ack_batch()
                    else:
                        client.acknowledge()
                    completed += n
                    pbar.update(max(0, completed - pbar.n))
                if mode == 'persistent':
                    result = client.finish_session()
                    from google.protobuf.json_format import MessageToDict
                    metadata_file.write(json.dumps({'session_result': MessageToDict(result,
                        preserving_proto_field_name=True), 'client_elapsed_s': time.monotonic()-acquisition_begin,
                        'read_rpc_s': client._stream_read_rpc_ns/1e9, 'validation_decode_s': client._stream_decode_ns/1e9,
                        'disk_write_flush_s': disk_write_s}) + '\n')
        finally:
            original_error = sys.exc_info()[1]
            try:
                try:
                    client.cancel()
                except Exception as cleanup:
                    if original_error is not None:
                        raise RuntimeError(
                            f"{original_error}; DMA cleanup unconfirmed: {cleanup}"
                        ) from original_error
                    raise
            finally:
                for f in files.values():
                    f.close()
    print_acquisition_done(completed, args.N)
    if args.compress:
        if args.compression_format == "tar":
            with tarfile.open(str(folder) + ".tar.gz", "w:gz", compresslevel=args.compression_level) as archive:
                archive.add(folder, arcname=folder.name)
        else:
            subprocess.run(["7z", "a", f"-mx={args.compression_level}", str(folder) + ".7z", str(folder)], check=True)
    return 0
