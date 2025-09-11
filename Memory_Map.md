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

| Offset  |  Address   |     Register     | Size  | Access |  Default   |                   Description                   |        Additional Information         |
|---------|------------|------------------|-------|--------|------------|-------------------------------------------------|---------------------------------------|
|  0x00   | 0x94000000 |  fan_speed_reg   |  8b   |  R/W   |    0xFF    |           Fan speed control register            |    0x00 (Off) - 0xFF (Full speed)     |
|  0x04   | 0x94000004 |    fan0_rpm      |  12b  |  R/O   |     -      |           Fan0 speed in RPM register            |                   -                   |
|  0x08   | 0x94000008 |    fan1_rpm      |  12b  |  R/O   |     -      |           Fan1 speed in RPM register            |                   -                   |
|  0x0C   | 0x9400000C |  hvbias_en_reg   |  1b   |  R/W   |    0x0     |          Voltage bias control register          |           Values 0x0 or 0x1           |
|  0x10   | 0x94000010 |   mux_en_reg     |  2b   |  R/W   |    0x0     |        Analog mux enable lines register         |           Values 0x1 or 0x2           |
|  0x14   | 0x94000014 |    mux_a_reg     |  2b   |  R/W   |    0x0     |        Analog mux address lines register        |           Values 0x0 or 0x1           |
|  0x18   | 0x94000018 |   stat_led_reg   |  6b   |  R/W   |    0x0     |              Status LEDs register               |         Currently Unconnected         |
|  0x1C   | 0x9400001C |     version      |  28b  |  R/O   |     -      |       GIT commit version number register        |                   -                   |
|  0x20   | 0x94000020 | core_enable_reg  |  32b  |  R/W   | 0x00000000 | Self triggered mode channel enable LSB register | Channel 31 to channel 0 (31 downto 0) |
|  0x24   | 0x94000024 | core_enable_reg  |  8b   |  R/W   |    0x00    | Self triggered mode channel enable MSB register | Channel 39 to channel 32 (7 downto 0) |

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