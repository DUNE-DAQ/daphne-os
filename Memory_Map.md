# Memory Map

List of all the register addresses present in DAPHNE3/MEZZ's firmware.

## SPI Master Control for AFE chips AXI-4 Lite Slave Interface: `AFE_SPI_S_AXI`
**Base Address:** `0x8000_0000`
**Memory Bank Size:** `64M`

**IMPORTANT NOTE:** The notation on this module is as follows:
1. AFE0 = 1 AFE + 2 Trim DACs + 2 Offset DACs
2. AFE12 = 2 AFEs + 4 Trim DACs + 4 Offset DACs
3. AFE34 = 2 AFEs + 4 Trim DACs + 4 Offset DACs

| Offset  |  Address   |         Register        | Size  | Access |  Default   |            Description             |                     Additional Information                      |
|---------|------------|-------------------------|-------|--------|------------|------------------------------------|-----------------------------------------------------------------|
|  0x00   | 0x80000000 | afe_rst_reg, afe_pd_reg |  5b   |  R/W   |    0x00    | AFE global control status register | (4) AFE34 interface busy R/O. (3) AFE12 interface busy R/O. (2) AFE0 interface busy R/O. (1) AFE power down R/W. (0) AFE hard reset R/W |
|  0x04   | 0x80000004 |        afe_we(0)        |  24b  |  R/W   |     -      |        AFE0 data register          |                           TX/RX Data                            |
|  0x08   | 0x80000008 |       trim_we(0)        |  32b  |  W/O   |     -      |    AFE0 Trim DAC data register     |                                -                                |
|  0x0C   | 0x8000000C |      offset_we(0)       |  32b  |  W/O   |     -      |   AFE0 Offset DAC data register    |                                -                                |
|  0x10   | 0x80000010 |        afe_we(1)        |  24b  |  R/W   |     -      |        AFE1 data register          |                           TX/RX Data                            |
|  0x14   | 0x80000014 |       trim_we(1)        |  32b  |  W/O   |     -      |    AFE1 Trim DAC data register     |                                -                                |
|  0x18   | 0x80000018 |      offset_we(1)       |  32b  |  W/O   |     -      |   AFE1 Offset DAC data register    |                                -                                |
|  0x1C   | 0x8000001C |        afe_we(2)        |  24b  |  R/W   |     -      |        AFE2 data register          |                           TX/RX Data                            |
|  0x20   | 0x80000020 |       trim_we(2)        |  32b  |  W/O   |     -      |    AFE2 Trim DAC data register     |                                -                                |
|  0x24   | 0x80000024 |      offset_we(2)       |  32b  |  W/O   |     -      |   AFE2 Offset DAC data register    |                                -                                |
|  0x28   | 0x80000028 |        afe_we(3)        |  24b  |  R/W   |     -      |        AFE3 data register          |                           TX/RX Data                            |
|  0x2C   | 0x8000002C |       trim_we(3)        |  32b  |  W/O   |     -      |    AFE3 Trim DAC data register     |                                -                                |
|  0x30   | 0x80000030 |      offset_we(3)       |  32b  |  W/O   |     -      |   AFE3 Offset DAC data register    |                                -                                |
|  0x34   | 0x80000034 |        afe_we(4)        |  24b  |  R/W   |     -      |        AFE4 data register          |                           TX/RX Data                            |
|  0x38   | 0x80000038 |       trim_we(4)        |  32b  |  W/O   |     -      |    AFE4 Trim DAC data register     |                                -                                |
|  0x3C   | 0x8000003C |      offset_we(4)       |  32b  |  W/O   |     -      |   AFE4 Offset DAC data register    |                                -                                |

## Timing Endpoint Control AXI-4 Lite Slave Interface: `END_P_S_AXI`
**Base Address:** `0x8400_0000`
**Memory Bank Size:** `64M`

| Offset  |  Address   |        Register        | Size  | Access |  Default   |           Description             |                      Additional Information                      |
|---------|------------|------------------------|-------|--------|------------|-----------------------------------|------------------------------------------------------------------|
|  0x00   | 0x84000000 |     clock_ctrl_reg     |  32b  |  R/W   | 0x00000000 |      Clock control register       | (31:3) Don't care. (2) Clock source 0=local, 1=endpoint. (1) MMCM1 reset. (0) reserved |
|  0x04   | 0x84000004 |      clock_status      |  32b  |  R/O   | 0x00000000 |       Clock status register       |         (31:2) Zero. (1) MMCM1 locked. (0) MMCM0 locked          |
|  0x08   | 0x84000008 |      ep_ctrl_reg       |  32b  |  R/W   | 0x00000000 |     Endpoint control register     | (31:17) Don't care. (16) Endpoint reset. (15:0) Endpoint address |
|  0x0C   | 0x8400000C |       ep_status        |  32b  |  R/O   | 0x00000000 |  Endpoint module status register  | (31:5) Zero. (4) Endpoint timestamp OK. (3:0) Endpoint state machine status |

## Front End Control AXI-4 Lite Slave Interface: `FRONT_END_S_AXI`
**Base Address:** `0x8800_0000`
**Memory Bank Size:** `64M`

| Offset  |  Address   |        Register        | Size  | Access |  Default   |           Description             |                     Additional Information                      |
|---------|------------|------------------------|-------|--------|------------|-----------------------------------|-----------------------------------------------------------------|
|  0x00   | 0x88000000 |    control_reg(2:0)    |  3b   |  R/W   |    0x0     |  Control idelay modules register  | Bit0=idelay reset, Bit1=iserdes reset, Bit2=idelay voltage and temperature compensation |
|  0x04   | 0x88000004 |    idelayctrl_ready    |  1b   |  R/O   |     -      |          Status register          |             Bit 0=value of the signal defined here              |
|  0x08   | 0x88000008 |      trig_reg(0)       |  1b   |  W/O   |    0x0     | Force Spy buffers to capture data |       Force a momentary pulse on the TRIG output (0xBABA)       |
|  0x0C   | 0x8800000C |   idelay_tap_reg(0)    |  8b   |  R/W   |    0x00    |  AFE0 Delay tap control register  | Load a pulse  on the corresponding ouput idelay (0x000 - 0x1FF) |
|  0x10   | 0x88000010 |   idelay_tap_reg(1)    |  8b   |  R/W   |    0x00    |  AFE1 Delay tap control register  | Load a pulse  on the corresponding ouput idelay (0x000 - 0x1FF) |
|  0x14   | 0x88000014 |   idelay_tap_reg(2)    |  8b   |  R/W   |    0x00    |  AFE2 Delay tap control register  | Load a pulse  on the corresponding ouput idelay (0x000 - 0x1FF) |
|  0x18   | 0x88000018 |   idelay_tap_reg(3)    |  8b   |  R/W   |    0x00    |  AFE3 Delay tap control register  | Load a pulse  on the corresponding ouput idelay (0x000 - 0x1FF) |
|  0x1C   | 0x8800001C |   idelay_tap_reg(4)    |  8b   |  R/W   |    0x00    |  AFE4 Delay tap control register  | Load a pulse  on the corresponding ouput idelay (0x000 - 0x1FF) |
|  0x20   | 0x88000020 | iserdes_bitslip_reg(0) |  4b   |  R/W   |    0x0     |       AFE0 Bitslip register       |   Execute a defined amount of bitslip operations (0x0 - 0xF)    |
|  0x24   | 0x88000024 | iserdes_bitslip_reg(1) |  4b   |  R/W   |    0x0     |       AFE1 Bitslip register       |   Execute a defined amount of bitslip operations (0x0 - 0xF)    |
|  0x28   | 0x88000028 | iserdes_bitslip_reg(2) |  4b   |  R/W   |    0x0     |       AFE2 Bitslip register       |   Execute a defined amount of bitslip operations (0x0 - 0xF)    |
|  0x2C   | 0x8800002C | iserdes_bitslip_reg(3) |  4b   |  R/W   |    0x0     |       AFE3 Bitslip register       |   Execute a defined amount of bitslip operations (0x0 - 0xF)    |
|  0x30   | 0x88000030 | iserdes_bitslip_reg(4) |  4b   |  R/W   |    0x0     |       AFE4 Bitslip register       |   Execute a defined amount of bitslip operations (0x0 - 0xF)    |

## SPI Master Control for DAC chips AXI-4 Lite Slave Interface: `SPI_DAC_S_AXI`
**Base Address:** `0x8C00_0000`
**Memory Bank Size:** `64M`

| Offset  |  Address   |        Register        | Size  | Access |  Default   |             Description              |                     Additional Information                     |
|---------|------------|------------------------|-------|--------|------------|--------------------------------------|----------------------------------------------------------------|
|  0x00   | 0x8C000000 |         go_reg         |  1b   |  R/W   |    0x0     |     Start transmission register      | Serial transfer to DACs. When reading this register, LSb is set when it is busy doing SPI transaction (DEFAULT=0xBABA) |
|  0x04   | 0x8C000004 |        dac0_reg        |  16b  |  R/W   |   0x0000   | Data for first DAC chip U50 register |                           TX - Data                            |
|  0x08   | 0x8C000008 |        dac1_reg        |  16b  |  R/W   |   0x0000   | Data for first DAC chip U53 register |                           TX - Data                            |
|  0x0C   | 0x8C00000C |        dac2_reg        |  16b  |  R/W   |   0x0000   | Data for first DAC chip U5 register  |                           TX - Data                            |

## Spy Buffers Control AXI-4 Lite Slave Interface: `SPY_BUF_S_S_AXI`
**Base Address:** `0x9000_0000`
**Memory Bank Size:** `64M`

This module is special, as here are noted only the first element of each address. Since each spy buffer stores about 1024 samples of data, the very first address contains the first two samples (sample 1 and sample 0) stored in the spy buffer in this configuration: `sample1 (15:0) & sample0 (15:0)`. The following address, which should be the `BASE + 0x00004` also returns data from the AFE0 Channel 0, but this time, it contains the following two samples (sample 3 and sample 2) using the same configuration. This pattern goes on until the last two samples, `sample1023 (15:0) & sample1022(15:0)` are seen when reading `BASE + 0x00FFC` or `OFFSET + 4092`. In this last case, the next address will change to the following channel, and then after reaching 8 channels, we change the AFE, and so on. For each AFE, channel 8 is the frame marker pattern. The timestamp is also stored in a window of 1024 samples, however, since it is a 64 bit word, it is split into 4 fragments of 16 bits each. When you access the first element e.g. `BASE + 0x2D000` you will read the LSB of the timestamp `timestamp (15:0)`. In the next address space, `BASE + 0x2E000` or `OFFSET + 188416` you will read the following 16 bits `timestamp (31:16)` and so on.

### Spy Buffer For The AFE0

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x00000 | 0x90000000 |    din(0)(0)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 0, Samples (1:0)  |   0x00000 - 0x00FFC AFE0 Channel 0    |
| 0x01000 | 0x90001000 |    din(0)(1)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 1, Samples (1:0)  |   0x01000 - 0x01FFC AFE0 Channel 1    |
| 0x02000 | 0x90002000 |    din(0)(2)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 2, Samples (1:0)  |   0x02000 - 0x02FFC AFE0 Channel 2    |
| 0x03000 | 0x90003000 |    din(0)(3)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 3, Samples (1:0)  |   0x03000 - 0x03FFC AFE0 Channel 3    |
| 0x04000 | 0x90004000 |    din(0)(4)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 4, Samples (1:0)  |   0x04000 - 0x04FFC AFE0 Channel 4    |
| 0x05000 | 0x90005000 |    din(0)(5)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 5, Samples (1:0)  |   0x05000 - 0x05FFC AFE0 Channel 5    |
| 0x06000 | 0x90006000 |    din(0)(6)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 6, Samples (1:0)  |   0x06000 - 0x06FFC AFE0 Channel 6    |
| 0x07000 | 0x90007000 |    din(0)(7)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 7, Samples (1:0)  |   0x07000 - 0x07FFC AFE0 Channel 7    |
| 0x08000 | 0x90008000 |    din(0)(8)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE0 - Channel 8, Samples (1:0)  |  0x08000 - 0x08FFC AFE0 Frame Clock   |

### Spy Buffer For The AFE1

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x09000 | 0x90009000 |    din(1)(0)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 0, Samples (1:0)  |   0x09000 - 0x09FFC AFE1 Channel 0    |
| 0x0A000 | 0x9000A000 |    din(1)(1)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 1, Samples (1:0)  |   0x0A000 - 0x0AFFC AFE1 Channel 1    |
| 0x0B000 | 0x9000B000 |    din(1)(2)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 2, Samples (1:0)  |   0x0B000 - 0x0BFFC AFE1 Channel 2    |
| 0x0C000 | 0x9000C000 |    din(1)(3)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 3, Samples (1:0)  |   0x0C000 - 0x0CFFC AFE1 Channel 3    |
| 0x0D000 | 0x9000D000 |    din(1)(4)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 4, Samples (1:0)  |   0x0D000 - 0x0DFFC AFE1 Channel 4    |
| 0x0E000 | 0x9000E000 |    din(1)(5)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 5, Samples (1:0)  |   0x0E000 - 0x0EFFC AFE1 Channel 5    |
| 0x0F000 | 0x9000F000 |    din(1)(6)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 6, Samples (1:0)  |   0x0F000 - 0x0FFFC AFE1 Channel 6    |
| 0x10000 | 0x90010000 |    din(1)(7)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 7, Samples (1:0)  |   0x10000 - 0x10FFC AFE1 Channel 7    |
| 0x11000 | 0x90011000 |    din(1)(8)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE1 - Channel 8, Samples (1:0)  |  0x11000 - 0x11FFC AFE1 Frame Clock   |

### Spy Buffer For The AFE2

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x12000 | 0x90012000 |    din(2)(0)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 0, Samples (1:0)  |   0x12000 - 0x12FFC AFE2 Channel 0    |
| 0x13000 | 0x90013000 |    din(2)(1)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 1, Samples (1:0)  |   0x13000 - 0x13FFC AFE2 Channel 1    |
| 0x14000 | 0x90014000 |    din(2)(2)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 2, Samples (1:0)  |   0x14000 - 0x14FFC AFE2 Channel 2    |
| 0x15000 | 0x90015000 |    din(2)(3)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 3, Samples (1:0)  |   0x15000 - 0x15FFC AFE2 Channel 3    |
| 0x16000 | 0x90016000 |    din(2)(4)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 4, Samples (1:0)  |   0x16000 - 0x16FFC AFE2 Channel 4    |
| 0x17000 | 0x90017000 |    din(2)(5)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 5, Samples (1:0)  |   0x17000 - 0x17FFC AFE2 Channel 5    |
| 0x18000 | 0x90018000 |    din(2)(6)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 6, Samples (1:0)  |   0x18000 - 0x18FFC AFE2 Channel 6    |
| 0x19000 | 0x90019000 |    din(2)(7)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 7, Samples (1:0)  |   0x19000 - 0x19FFC AFE2 Channel 7    |
| 0x1A000 | 0x9001A000 |    din(2)(8)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE2 - Channel 8, Samples (1:0)  |  0x1A000 - 0x1AFFC AFE2 Frame Clock   |

### Spy Buffer For The AFE3

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x1B000 | 0x9001B000 |    din(3)(0)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 0, Samples (1:0)  |   0x1B000 - 0x1BFFC AFE3 Channel 0    |
| 0x1C000 | 0x9001C000 |    din(3)(1)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 1, Samples (1:0)  |   0x1C000 - 0x1CFFC AFE3 Channel 1    |
| 0x1D000 | 0x9001D000 |    din(3)(2)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 2, Samples (1:0)  |   0x1D000 - 0x1DFFC AFE3 Channel 2    |
| 0x1E000 | 0x9001E000 |    din(3)(3)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 3, Samples (1:0)  |   0x1E000 - 0x1EFFC AFE3 Channel 3    |
| 0x1F000 | 0x9001F000 |    din(3)(4)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 4, Samples (1:0)  |   0x1F000 - 0x1FFFC AFE3 Channel 4    |
| 0x20000 | 0x90020000 |    din(3)(5)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 5, Samples (1:0)  |   0x20000 - 0x20FFC AFE3 Channel 5    |
| 0x21000 | 0x90021000 |    din(3)(6)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 6, Samples (1:0)  |   0x21000 - 0x21FFC AFE3 Channel 6    |
| 0x22000 | 0x90022000 |    din(3)(7)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 7, Samples (1:0)  |   0x22000 - 0x22FFC AFE3 Channel 7    |
| 0x23000 | 0x90023000 |    din(3)(8)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE3 - Channel 8, Samples (1:0)  |  0x23000 - 0x23FFC AFE3 Frame Clock   |

### Spy Buffer For The AFE4

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x24000 | 0x90024000 |    din(4)(0)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 0, Samples (1:0)  |   0x24000 - 0x24FFC AFE4 Channel 0    |
| 0x25000 | 0x90025000 |    din(4)(1)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 1, Samples (1:0)  |   0x25000 - 0x25FFC AFE4 Channel 1    |
| 0x26000 | 0x90026000 |    din(4)(2)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 2, Samples (1:0)  |   0x26000 - 0x26FFC AFE4 Channel 2    |
| 0x27000 | 0x90027000 |    din(4)(3)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 3, Samples (1:0)  |   0x27000 - 0x27FFC AFE4 Channel 3    |
| 0x28000 | 0x90028000 |    din(4)(4)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 4, Samples (1:0)  |   0x28000 - 0x28FFC AFE4 Channel 4    |
| 0x29000 | 0x90029000 |    din(4)(5)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 5, Samples (1:0)  |   0x29000 - 0x29FFC AFE4 Channel 5    |
| 0x2A000 | 0x9002A000 |    din(4)(6)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 6, Samples (1:0)  |   0x2A000 - 0x2AFFC AFE4 Channel 6    |
| 0x2B000 | 0x9002B000 |    din(4)(7)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 7, Samples (1:0)  |   0x2B000 - 0x2BFFC AFE4 Channel 7    |
| 0x2C000 | 0x9002C000 |    din(4)(8)     |  32b  |  R/O   | 0x00000000 | Spy buffer for AFE4 - Channel 8, Samples (1:0)  |  0x2C000 - 0x2CFFC AFE4 Frame Clock   |

### Spy Buffer For The Timestamp

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x2D000 | 0x9002D000 | timestamp(15:0)  |  32b  |  R/O   | 0x00000000 |     Spy buffer for Timestamp, Samples (1:0)     |  0x2D000 - 0x2DFFC Timestamp (15:0)   |
| 0x2E000 | 0x9002E000 | timestamp(31:16) |  32b  |  R/O   | 0x00000000 |     Spy buffer for Timestamp, Samples (1:0)     |  0x2E000 - 0x2EFFC Timestamp (31:16)  |
| 0x2F000 | 0x9002F000 | timestamp(47:32) |  32b  |  R/O   | 0x00000000 |     Spy buffer for Timestamp, Samples (1:0)     |  0x2F000 - 0x2FFFC Timestamp (47:32)  |
| 0x30000 | 0x90030000 | timestamp(63:48) |  32b  |  R/O   | 0x00000000 |     Spy buffer for Timestamp, Samples (1:0)     |  0x30000 - 0x30FFC Timestamp (63:48)  |

## Miscellaneous Stuff AXI-4 Lite Slave Interface: `STUFF_S_AXI`
**Base Address:** `0x9400_0000`
**Memory Bank Size:** `64M`

This module contains a lot of registers dedicated to reading flags from each channel in self trigger mode. Regarding the trigger counters, there are two types, the self trigger packet counter, and the self trigger trigger counter, these counters are Read Only and have a width of 64 bits. Since AXI-4 Lite interface supports 32 bit words, the counters are split in two in order to store their values. The first register/address related to a channel for these counters reads the least significant 32 bits, while the following address reads the most significant 32 bits of the 64 bit word given by these counters. The counters start from the `BASE + 84` and go all the way up to the `BASE + 720`.

| Offset  |  Address   |       Register        | Size  | Access |  Default   |                       Description                       |         Additional Information          |
|---------|------------|-----------------------|-------|--------|------------|---------------------------------------------------------|-----------------------------------------|
|  0x00   | 0x94000000 |     fan_speed_reg     |  8b   |  R/W   |    0xFF    |               Fan speed control register                |     0x00 (Off) - 0xFF (Full speed)      |
|  0x04   | 0x94000004 |       fan0_rpm        |  12b  |  R/O   |     -      |               Fan0 speed in RPM register                |                    -                    |
|  0x08   | 0x94000008 |       fan1_rpm        |  12b  |  R/O   |     -      |               Fan1 speed in RPM register                |                    -                    |
|  0x0C   | 0x9400000C |     hvbias_en_reg     |  1b   |  R/W   |    0x0     |              Voltage bias control register              |            Values 0x0 or 0x1            |
|  0x10   | 0x94000010 |      mux_en_reg       |  2b   |  R/W   |    0x0     |            Analog mux enable lines register             |            Values 0x1 or 0x2            |
|  0x14   | 0x94000014 |       mux_a_reg       |  2b   |  R/W   |    0x0     |            Analog mux address lines register            |            Values 0x0 or 0x1            |
|  0x18   | 0x94000018 |     stat_led_reg      |  6b   |  R/W   |    0x0     |                  Status LEDs register                   |        **Currently Unconnected**        |
|  0x1C   | 0x9400001C |        version        |  28b  |  R/O   |     -      |           GIT commit version number register            |                    -                    |
|  0x20   | 0x94000020 |    core_enable_reg    |  32b  |  R/W   | 0x00000000 |     Self triggered mode channel enable LSB register     |  Channel 31 to channel 0 (31 downto 0)  |
|  0x24   | 0x94000024 |    core_enable_reg    |  8b   |  R/W   |    0x00    |     Self triggered mode channel enable MSB register     | Channel 39 to channel 32 (39 downto 32) |
|  0x28   | 0x94000028 |       adhoc_reg       |  8b   |  R/W   |    0x07    |             Ad hoc trigger command register             |                    -                    |
|  0x2C   | 0x9400002C |     st_config_reg     |  14b  |  R/W   |   0x36CD   |        Trigger Primitives configuration register        | Configuration of the trigger primitives calculation module. Bits 13 to 7: Slope threshold, must be negative. Bit 6: '0' = Slope calculation with 2 consecutive samples. '1' = Slope calculation with 3 consecutive samples. Bit 5: '0' = Do not allow self trigger with light pulse between 2 acquisition frames. '1' = Allow self trigger with light pulse between 2 data acquisition frames. Bit 4: '0' = Peak detector as self-trigger. '1' = Main detection as self trigger (no undershoot). Bits 3 to 0 **Currently Unused**. |
|  0x30   | 0x94000030 |   signal_delay_reg    |  5b   |  R/W   |    0x10    |                  Signal delay register                  | Configure the delay of the signal that allows for trigger primitive calculation |
|  0x34   | 0x94000034 |   threshold_xc_reg    |  32b  |  R/W   | 0x1000047E |  Self trigger cross correlation threshold LSB register  | Bits 31 to 0 of the register. Threshold_xc from bit 27 to 0 set the low boundary, in cross correlation values, the threshold where any signal will be detected and allow to generate a trigger. |
|  0x38   | 0x94000038 |   threshold_xc_reg    |  10b  |  R/W   |   0x200    |  Self trigger cross correlation threshold MSB register  | Bits 41 to 32 of the register. Threshold_xc from bit 41 to bit 28 set the high boundary, any event above this value will be ignored by the trigger. **Currently Unused**. |
|  0x3C   | 0x9400003C | filt_out_selector_reg |  2b   |  R/W   |    0x0     |      Self trigger filter output selector register       | "00"=High pass filter output when core_enable_reg of the channel is '0', High pass filter output + low pass filter output when core_enable_reg of the channel is '1'. "01"=Calculated baseline + high pass filter output. "10"=Low pass filter output + cross correlation signal. "11"= Raw data. |
|  0x40   | 0x94000040 | reset_st_counters_reg |  1b   |  R/W   |    0x0     |          Self trigger counters reset register           | Reset trigger counters, write anything  |
|  0x44   | 0x94000044 |  afe_comp_enable_reg  |  32b  |  R/W   | 0x00000000 |      Self trigger compensator enable LSB register       |  Channel 31 to channel 0 (31 downto 0)  |
|  0x48   | 0x94000048 |  afe_comp_enable_reg  |  8b   |  R/W   |    0x00    |      Self trigger compensator enable MSB register       | Channel 39 to channel 32 (39 downto 32) |
|  0x4C   | 0x9400004C |   invert_enable_reg   |  32b  |  R/W   | 0x00000000 |    Self trigger signal inverter enable LSB register     |  Channel 31 to channel 0 (31 downto 0)  |
|  0x50   | 0x94000050 |   invert_enable_reg   |  8b   |  R/W   |    0x00    |    Self trigger signal inverter enable MSB register     | Channel 39 to channel 32 (39 downto 32) |
|  0x54   | 0x94000054 |     PCount_reg(0)     |  32b  |  R/O   | 0x00000000 |  Self trigger packets counter LSB - channel 0 register  |       Channel 0 LSB (31 downto 0)       |
|  0x58   | 0x94000058 |     PCount_reg(0)     |  32b  |  R/O   | 0x00000000 |  Self trigger packets counter MSB - channel 0 register  |      Channel 0 MSB (63 downto 32)       |
|  0x5C   | 0x9400005C |     PCount_reg(1)     |  32b  |  R/O   | 0x00000000 |  Self trigger packets counter LSB - channel 1 register  |       Channel 1 LSB (31 downto 0)       |
|  0x60   | 0x94000060 |     PCount_reg(1)     |  32b  |  R/O   | 0x00000000 |  Self trigger packets counter MSB - channel 1 register  |      Channel 1 MSB (63 downto 32)       |
|  0x64   | 0x94000064 |     PCount_reg(2)     |  32b  |  R/O   | 0x00000000 |  Self trigger packets counter LSB - channel 2 register  |       Channel 2 LSB (31 downto 0)       |
|  0x68   | 0x94000068 |     PCount_reg(2)     |  32b  |  R/O   | 0x00000000 |  Self trigger packets counter MSB - channel 2 register  |      Channel 2 MSB (63 downto 32)       |
|    .    |     .      |           .           |   .   |   .    |     .      |                            .                            |                    .                    |
|    .    |     .      |           .           |   .   |   .    |     .      |                            .                            |                    .                    |
|    .    |     .      |           .           |   .   |   .    |     .      |                            .                            |                    .                    |
|  0x184  | 0x94000184 |    PCount_reg(38)     |  32b  |  R/O   | 0x00000000 | Self trigger packets counter LSB - channel 38 register  |      Channel 38 LSB (31 downto 0)       |
|  0x188  | 0x94000188 |    PCount_reg(38)     |  32b  |  R/O   | 0x00000000 | Self trigger packets counter MSB - channel 38 register  |      Channel 38 MSB (63 downto 32)      |
|  0x18C  | 0x9400018C |    PCount_reg(39)     |  32b  |  R/O   | 0x00000000 | Self trigger packets counter LSB - channel 39 register  |      Channel 39 LSB (31 downto 0)       |
|  0x190  | 0x94000190 |    PCount_reg(39)     |  32b  |  R/O   | 0x00000000 | Self trigger packets counter MSB - channel 39 register  |      Channel 39 MSB (63 downto 32)      |
|  0x194  | 0x94000194 |     TCount_reg(0)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter LSB - channel 0 register  |       Channel 0 LSB (31 downto 0)       |
|  0x198  | 0x94000198 |     TCount_reg(0)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter MSB - channel 0 register  |      Channel 0 MSB (63 downto 32)       |
|  0x19C  | 0x9400019C |     TCount_reg(1)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter LSB - channel 1 register  |       Channel 1 LSB (31 downto 0)       |
|  0x1A0  | 0x940001A0 |     TCount_reg(1)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter MSB - channel 1 register  |      Channel 1 MSB (63 downto 32)       |
|    .    |     .      |           .           |   .   |   .    |     .      |                            .                            |                    .                    |
|    .    |     .      |           .           |   .   |   .    |     .      |                            .                            |                    .                    |
|    .    |     .      |           .           |   .   |   .    |     .      |                            .                            |                    .                    |
|  0x2BC  | 0x940002BC |    TCount_reg(37)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter LSB - channel 37 register |      Channel 37 LSB (31 downto 0)       |
|  0x2C0  | 0x940002C0 |    TCount_reg(37)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter MSB - channel 37 register |      Channel 37 MSB (63 downto 32)      |
|  0x2C4  | 0x940002C4 |    TCount_reg(38)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter LSB - channel 38 register |      Channel 38 LSB (31 downto 0)       |
|  0x2C8  | 0x940002C8 |    TCount_reg(38)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter MSB - channel 38 register |      Channel 38 MSB (63 downto 32)      |
|  0x2CC  | 0x940002CC |    TCount_reg(39)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter LSB - channel 39 register |      Channel 39 LSB (31 downto 0)       |
|  0x2D0  | 0x940002D0 |    TCount_reg(39)     |  32b  |  R/O   | 0x00000000 | Self trigger triggers counter MSB - channel 39 register |      Channel 39 MSB (63 downto 32)      |

## Trigger Core Control AXI-4 Lite Slave Interface: `TRIRG_S_AXI`
**Base Address:** `0x9800_0000`
**Memory Bank Size:** `64M`

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
|  0x00   | 0x98000000 |    10g_sender    |  32b  |  R/W   |     -      |            10G Hermes sender module             |                   -                   |

## AXI IIC AXI-4 Lite Slave Interface: `S_AXI`
**Base Address:** `0x9C00_0000`
**Memory Bank Size:** `64K`

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
|  0x00   | 0x9C000000 |     AXI IIC      |  32b  |  R/W   |     -      |                 AXI IIC module                  |          Check product guide          |

## AXI Interrupt Controller AXI-4 Lite Slave Interface: `s_axi`
**Base Address:** `0x9C01_0000`
**Memory Bank Size:** `64K`

| Offset  |  Address   |         Register         | Size  | Access |  Default   |                 Description                  |        Additional Information         |
|---------|------------|--------------------------|-------|--------|------------|----------------------------------------------|---------------------------------------|
|  0x00   | 0x9C010000 | AXI Interrupt Controller |  32b  |  R/W   |     -      | AXI Interrupt Controller module for the ZYNQ |          Check product guide          |

## AXI Quad SPI AXI-4 Lite Slave Interface: `AXI_LITE`
**Base Address:** `0x9C02_0000`
**Memory Bank Size:** `64K`

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
|  0x00   | 0x9C020000 |   AXI Quad SPI   |  32b  |  R/W   |     -      |               AXI Quad SPI module               |          Check product guide          |

## DAPHNE Output Spy Buffer 64 AXI-4 Lite Slave Interface: `S_AXI`
**Base Address:** `0xA000_0000`
**Memory Bank Size:** `64K`

This module waits for trigger, stores 1024 64-bit words, including 64 pre-trigger words. Since AXI-4 Lite reads 32 bits at a time, there are two 32-bit registers related to each full word. Therefore, from the AXI side this module appears as a 2k x 32 R/W memory. First 32-bit word is address 0, the next 32 bit word is address 4, and so on up to address 8188.

| Offset  |  Address   |      Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|-------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
| 0x0000  | 0xA0000000 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |        Captured data word 0 LSB register        |             Bits 31 to 0              |
| 0x0004  | 0xA0000004 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |        Captured data word 1 LSB register        |             Bits 31 to 0              |
| 0x0008  | 0xA0000008 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |        Captured data word 2 LSB register        |             Bits 31 to 0              |
|    .    |     .      |         .         |   .   |   .    |     .      |                        .                        |                   .                   |
|    .    |     .      |         .         |   .   |   .    |     .      |                        .                        |                   .                   |
|    .    |     .      |         .         |   .   |   .    |     .      |                        .                        |                   .                   |
| 0x0FF8  | 0xA0000FF8 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |      Captured data word 1022 LSB register       |             Bits 31 to 0              |
| 0x0FFC  | 0xA0000FFC | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |      Captured data word 1023 LSB register       |             Bits 31 to 0              |
| 0x1000  | 0xA0001000 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |        Captured data word 0 MSB register        |             Bits 63 to 32             |
| 0x1004  | 0xA0001004 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |        Captured data word 1 MSB register        |             Bits 63 to 32             |
|    .    |     .      |         .         |   .   |   .    |     .      |                        .                        |                   .                   |
|    .    |     .      |         .         |   .   |   .    |     .      |                        .                        |                   .                   |
|    .    |     .      |         .         |   .   |   .    |     .      |                        .                        |                   .                   |
| 0x1FF4  | 0xA0001FF4 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |      Captured data word 1021 MSB register       |             Bits 63 to 32             |
| 0x1FF8  | 0xA0001FF8 | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |      Captured data word 1022 MSB register       |             Bits 63 to 32             |
| 0x1FFC  | 0xA0001FFC | axi_awaddr/araddr |  32b  |  R/W   | 0x00000000 |      Captured data word 1023 MSB register       |             Bits 63 to 32             |