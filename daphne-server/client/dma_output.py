"""Keep files produced with different ADC encodings from being appended."""
import json
from pathlib import Path


def prepare_dma_output(directory, channels, append=False, contract=None):
    directory = Path(directory)
    marker = directory / "dma_format.json"
    previous = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    compatible = previous.get("saved_encoding") == "offset_binary" and previous.get("adc_bits") == 14
    recorded = set(previous.get("channels", [])) if compatible else set()
    if append:
        for ch in channels:
            file = directory / f"channel_{ch}.dat"
            if file.is_file() and file.stat().st_size and ch not in recorded:
                raise ValueError("Cannot append DMA data: existing ADC encoding is unknown or predates the offset-binary correction; use a new folder")
            if file.is_file() and file.stat().st_size:
                old = previous.get('capture_contracts', {}).get(str(ch))
                triggered = (contract or {}).get('capture_mode') == 'triggered' or (old or {}).get('capture_mode') == 'triggered'
                if (triggered or old is not None) and old != contract:
                    raise ValueError('Cannot append DMA data: capture mode/L/P/source differs or is unknown; use a new folder')
                if contract and file.stat().st_size % (2 * contract['samples']):
                    raise ValueError('Cannot append DMA data: file contains a partial waveform')
    directory.mkdir(parents=True, exist_ok=True)


def record_dma_output(directory, channels, contract=None):
    """Call after every selected file has been opened/truncated successfully."""
    directory = Path(directory)
    marker = directory / "dma_format.json"
    previous = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    compatible = previous.get("saved_encoding") == "offset_binary" and previous.get("adc_bits") == 14
    recorded = set(previous.get("channels", [])) if compatible else set()
    contracts = previous.get('capture_contracts', {}) if compatible else {}
    for ch in channels:
        if contract is None:
            contracts.pop(str(ch), None)
        else:
            contracts[str(ch)] = contract
    marker.write_text(json.dumps({"saved_encoding": "offset_binary", "adc_bits": 14,
                                 "channels": sorted(recorded | set(channels)),
                                 "capture_contracts": contracts}, indent=2) + "\n", encoding="utf-8")
