"""DMA implementation of the acquire-list CLI; legacy path remains separate."""
import json
from pathlib import Path
import tarfile
import subprocess
import uuid
from dma_client import DmaClient
from dma_output import prepare_dma_output, record_dma_output
from v2_client import V2Client


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
    with V2Client(pb, args.ip, args.port, route=args.route, timeout_ms=args.timeout_ms,
                  identity="dma-acquire-" + uuid.uuid4().hex) as transport:
        client = DmaClient(pb, transport.rpc)
        client.probe(args.trigger_source)
        batch = min(args.chunk, client.batch_limit(channels, args.L))
        if getattr(args, "osc_mode", False):
            batch = 1
        prepare_dma_output(folder, channels, args.append_data)
        try:
            for ch in channels:
                files[ch] = (folder / f"channel_{ch}.dat").open("ab" if args.append_data else "wb")
            record_dma_output(folder, channels)
            with metadata_path.open("w", encoding="utf-8") as metadata_file:
                while completed < args.N:
                    n = min(batch, args.N - completed)
                    data, metadata = client.acquire(channels, args.L, n, args.trigger_source,
                                                    timeout_ms=min(600000, max(10, args.timeout_ms)))
                    for i, ch in enumerate(channels):
                        files[ch].write(data[:, i, :].astype("<u2", copy=False).tobytes())
                        files[ch].flush()
                    metadata["first_waveform"] = completed
                    metadata_file.write(json.dumps(metadata) + "\n")
                    metadata_file.flush()
                    client.acknowledge()
                    completed += n
                    print(f"DMA: {completed}/{args.N} waveforms, L={args.L}")
        finally:
            try:
                client.cancel()
            finally:
                for f in files.values():
                    f.close()
    if args.compress:
        if args.compression_format == "tar":
            with tarfile.open(str(folder) + ".tar.gz", "w:gz", compresslevel=args.compression_level) as archive:
                archive.add(folder, arcname=folder.name)
        else:
            subprocess.run(["7z", "a", f"-mx={args.compression_level}", str(folder) + ".7z", str(folder)], check=True)
    return 0
