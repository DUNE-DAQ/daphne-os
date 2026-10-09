# Raw DMA hardware contract consumed by point 3

Derived from the firmware handoff instructions and `raw-dma-infrastructure.md`
dated 2026-10-09, branch `test/dma_ethernet_aquisition` (infrastructure `1864bf3`,
build-flow/SFP corrections `66b7300` and `2ca8afd`). These references describe
the expected hardware; they do not identify a qualified deployed build.

## Identity and topology

STUFF base is `0x94000000`: capabilities +E0 must be `0x00000520`, DAPH magic
+F0 `0x44415048`, ABI +F4 `0x00020000`, raw variant +F8 `3`, build +FC is the
manifest's 28-bit identity. Bit 5 is DMA diagnostics; physical AFE DMA bit 4
is zero. Legacy spy/self-trigger/Hermes windows return SLVERR on raw and must
never be accessed by the diagnostic or initialized as a legacy server mode.

| Route | S2MM control (64 KiB) | Producer (4 KiB) | PS DDR | GIC SPI |
| --- | --- | --- | --- | --- |
| 0 | `0xB0020000` | `0xB0030000` | HP0 | 104 |
| 1 | `0xB0040000` | `0xB0050000` | HP1 | 105 |
| 2 | `0xB0060000` | `0xB0070000` | HP3 | 106 |

AXI DMA 7.1, S2MM only, scatter/gather, no DRE/MM2S. Payload/AXIS are 128 bits,
address width 40, SG length width 26 (`2^26-1` bytes maximum per descriptor),
payload alignment 16 bytes, hardware SG alignment 64 bytes. The diagnostic
client uses smaller aligned SG segments; the provider owns hardware BDs.
PL2 is 199998001 Hz. IRQs use DTS `<0 104 4>` through `<0 106 4>`, not Linux
IRQ numbers. All three DMA clock names resolve to PL2. HP is noncoherent.
The high DDR aperture starts at `0x8_0000_0000`; populated/usable memory can
only be obtained from the Linux DMA API, never inferred from that aperture.

## Producer registers

Offsets are relative to each producer base:

| Offset | Access | Register/meaning |
| --- | --- | --- |
| 00 | RO | magic DMAP `0x444D4150` |
| 04 | RO | ABI `1` |
| 08 | RO | route ID `0`, `1` or `2` |
| 0C | WO | command low byte: START `1`, STOP `2`, CLEAR `4`, no-op `0` |
| 10 | RW | beats per packet, nonzero (reset 1024) |
| 14 | RW | finite packet count, nonzero (reset 1) |
| 18 | RW | seed (reset 0) |
| 1C | RW | offered-rate numerator (reset 1) |
| 20 | RW | offered-rate denominator (reset 1) |
| 24 | RO | status: busy bit 0, done 1, config error 2, diagnostic 3 |
| 28 | RO | accepted AXIS beats low 32 bits |
| 2C | RO | accepted beats high 32 bits |
| 30 | RO | accepted TLAST/completed packet count |

Numerator and denominator must be nonzero, numerator <= denominator. Busy
configuration writes, invalid START, unknown/unaligned registers and RO writes
return SLVERR. Configuration is frozen during a job. START resets counters;
CLEAR clears done/config error. Live 64-bit counters require high/low/high
retry. Configure only while idle. Post DMA capacity before START.

Each accepted 16-byte beat has four little-endian 32-bit words, in increasing
memory order: `0x444D4100 + route`, zero-based packet index, zero-based beat
index within packet, `seed + accepted beat index` modulo `2^32`. Indices
restart per START. TKEEP is FFFF; TLAST is the final beat of each packet.
VALID/data/TLAST remain stable during backpressure.

STOP drains the current packet and sets done. It can wait indefinitely without
buffers. DMA soft reset aborts the producer, clears progress/done, and retains
configuration. Software must distinguish draining from abort/reset and prove
DMA access ceased before reclamation.

Offered 1/1 is approximately 3.2 GB/s per route; 5/8 approximately 2 GB/s;
5/16 approximately 1 GB/s. Backpressure reduces accepted throughput. These
fractions do not measure DDR performance or qualify the physical AFE path.
