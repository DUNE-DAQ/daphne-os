-- stc3.vhd
-- self triggered channel machine for ONE DAPHNE channel
--
-- updated for DAPHNE3 using new backend 10G Ethernet sender block
-- this block handles buffering of output data, so FIFO has been removed from this module
-- and has been replaced with a single UltraScale+ UltraRAM block
-- 
-- This module watches one channel data bus and computes the average signal level 
-- (baseline.vhd) based on the last N samples. When it detects a trigger condition
-- (defined in trig.vhd) it then begins assemblying the output frame IN MEMORY and when done,
-- begins clocking the data out directly, using a 64 bit wide bus. the trigger module provided here 
-- is very basic and is intended as a placeholder to simulate a more advanced trigger
-- which has a total latency of 128 clock cycles.

-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity stc3 is
generic( 
    link_id: std_logic_vector(5 downto 0) := "000000"; 
    ch_id: std_logic_vector(5 downto 0) := "000000";
    slot_id: std_logic_vector(3 downto 0) := "0010";
    crate_id: std_logic_vector(9 downto 0) := "0000000011";
    detector_id: std_logic_vector(5 downto 0) := "000010";
    version_id: std_logic_vector(5 downto 0) := "000011";
    runlength: integer := 256; -- baseline runlength must be one of: 32, 64, 128, 256
    threshold: std_logic_vector(13 downto 0):= "10000000000000" -- trig threshold relative to calculated baseline
);
port(
    clock: in std_logic; -- master clock 62.5MHz
    reset: in std_logic;
    enable: in std_logic; 
    timestamp: in std_logic_vector(63 downto 0);
	din: in std_logic_vector(13 downto 0); -- aligned AFE data
    dout: out std_logic_vector(63 downto 0);
    valid: out std_logic;
    last: out std_logic
);
end stc3;

architecture stc3_arch of stc3 is

signal din_dly32_i, din_dly64_i, din_dly96_i, din_dly128_i, din_dly160_i, din_dly192_i: std_logic_vector(13 downto 0);
signal R0, R1, R2, R3, R4, R5: std_logic_vector(13 downto 0);
signal block_count: integer range 0 to 31 := 0;

type state_type is (rst, wait4trig, w0, w1, w2, w3, w4, w5, w6,
                    d0, d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11, d12, d13, d14, d15, 
                    d16, d17, d18, d19, d20, d21, d22, d23, d24, d25, d26, d27, d28, d29, d30, d31,
                    h0, h1, h2, h3, h4, h5, h6, h7, h8, hold, dump0, dump1, dump2);
signal state: state_type;

signal sample0_timestamp: std_logic_vector(63 downto 0) := (others=>'0');
signal bline, trigsample: std_logic_vector(13 downto 0) := (others=>'0');
signal triggered: std_logic := '0';

signal DIN_A, DOUT_B: std_logic_vector(71 downto 0) := (others=>'0');
signal EN_A, EN_B, SLEEP: std_logic := '0';
signal BWE_A: std_logic_vector(8 downto 0) := (others=>'0');
signal addra, addrb: integer range 0 to 255 := 0;
signal ADDR_A, ADDR_B: std_logic_vector(22 downto 0) := (others=>'0');

component baseline
generic( runlength: integer := 256 );
port(
    clock: in std_logic;
    reset: in std_logic;
    din: in std_logic_vector(13 downto 0);
    bline: out std_logic_vector(13 downto 0));
end component;

component trig
port(
    clock: in std_logic;
    din: in std_logic_vector(13 downto 0);
    baseline: in std_logic_vector(13 downto 0);
    threshold: in std_logic_vector(13 downto 0);
    triggered: out std_logic;
    trigsample: out std_logic_vector(13 downto 0));
end component;

begin

-- delay input data by 192 clocks (!) to compensate for 128 clock trigger latency 
-- + 64 pre-trigger samples

gendelay: for i in 13 downto 0 generate

    srlc32e_0_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => din(i), -- live AFE data
        q => open,
        q31 => din_dly32_i(i) -- live data delayed 32 clocks
    );

    srlc32e_1_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => din_dly32_i(i),
        q => open,
        q31 => din_dly64_i(i) -- live data delayed 64 clocks
    );

    srlc32e_2_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => din_dly64_i(i),
        q => open,
        q31 => din_dly96_i(i) -- live data delayed 96 clocks
    );

    srlc32e_3_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => din_dly96_i(i),
        q => open,
        q31 => din_dly128_i(i) -- live data delayed 128 clocks
    );

    srlc32e_4_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => din_dly128_i(i),
        q => open,
        q31 => din_dly160_i(i) -- live data delayed 160 clocks
    );

    srlc32e_5_inst : srlc32e
    port map(
        clk => clock,
        ce => '1',
        a => "11111",
        d => din_dly160_i(i),
        q => open,
        q31 => din_dly192_i(i) -- live data delayed 192 clocks
    );

end generate gendelay;

-- compute the average signal baseline level over the last N samples

baseline_inst: baseline
generic map ( runlength => runlength ) -- must be 32, 64, 128, or 256
port map(
    clock => clock,
    reset => reset,
    din => din, -- this looks at LIVE AFE data, not the delayed data
    bline => bline
);

-- for dense data packing 14 bit samples into 64 bit words,
-- we need to access up to last 6 samples at once...

pack_proc: process(clock)
begin
    if rising_edge(clock) then
        R0 <= din_dly192_i;
        R1 <= R0;
        R2 <= R1;
        R3 <= R2;
        R4 <= R3;
        R5 <= R4;
    end if;
end process pack_proc;       

-- trigger module latency is FIXED at 128 clocks:

trig_inst: trig
port map(
     clock => clock,
     din => din, -- watching live AFE data
     baseline => bline,
     threshold => threshold,
     triggered => triggered,
     trigsample => trigsample -- the ADC sample that caused the trigger 
);        

-- big FSM waits for trigger condition then dense pack assembly of the output frame 
-- in memory, then jumps back and fills in the header.

-- one BLOCK = 32 14-bit samples DENSE PACKED into 7 64-bit words
-- one SUPERBLOCK = 32 blocks = 1024 samples = 224 64 bit words

-- sample0 is the first sample packed into the output record
-- sample0...sample63 = pretrigger
-- sample64 = trigger sample
-- sample65...sample1023 = post trigger
-- the timestamp value recorded in the output record corresponds to sample0 NOT the trigger sample!

builder_fsm_proc: process(clock)
begin
    if rising_edge(clock) then
        if (reset='1') then
            state <= rst;
        else
            case(state) is
                when rst =>
                    state <= wait4trig;
                when wait4trig => 
                    if (triggered='1' and enable='1') then -- start packing
                        block_count <= 0;
                        sample0_timestamp <= std_logic_vector( unsigned(timestamp) - 189 ); 
                        state <= w0; 
                    else
                        state <= wait4trig;
                    end if;

                when w0 => state <= w1; -- some wait states
                when w1 => state <= w2;
                when w2 => state <= w3;
                when w3 => state <= w4;
                when w4 => state <= w5;
                when w5 => state <= w6;
                when w6 => 
                    addra <= 9; -- address of first data word in output buffer
                    state <= d0;

                when d0 => state <= d1;
                when d1 => state <= d2;
                when d2 => state <= d3;
                when d3 => state <= d4;
                when d4 => state <= d5; addra <= addra + 1;
                when d5 => state <= d6;
                when d6 => state <= d7;
                when d7 => state <= d8;
                when d8 => state <= d9; addra <= addra + 1;
                when d9 => state <= d10;
                when d10 => state <= d11;
                when d11 => state <= d12;
                when d12 => state <= d13;
                when d13 => state <= d14; addra <= addra + 1;
                when d14 => state <= d15;
                when d15 => state <= d16;
                when d16 => state <= d17;
                when d17 => state <= d18; addra <= addra + 1;
                when d18 => state <= d19;
                when d19 => state <= d20;
                when d20 => state <= d21;
                when d21 => state <= d22;
                when d22 => state <= d23; addra <= addra + 1;
                when d23 => state <= d24;
                when d24 => state <= d25;
                when d25 => state <= d26;
                when d26 => state <= d27; addra <= addra + 1;
                when d27 => state <= d28;
                when d28 => state <= d29;
                when d29 => state <= d30;
                when d30 => state <= d31;

                when d31 =>
                    if (block_count=31) then -- done with packing data samples, update header info
                        state <= h0;
                        addra <= 0; -- address of header word 0
                    else
                        block_count <= block_count + 1;
                        state <= d0;
                        addra <= addra + 1;
                    end if;

                -- jump back in and fill in the header information in the buffer

                when h0 => 
                    state <= h1; 
                    addra <= addra + 1;
                when h1 => 
                    state <= h2;
                    addra <= addra + 1;
                when h2 => 
                    state <= h3;
                    addra <= addra + 1;
                when h3 =>
                    state <= h4;
                    addra <= addra + 1;
                when h4 =>
                    state <= h5;
                    addra <= addra + 1;
                when h5 =>
                    state <= h6;
                    addra <= addra + 1;
                when h6 =>
                    state <= h7;
                    addra <= addra + 1;
                when h7 =>
                    state <= h8;
                    addra <= addra + 1;
                when h8 =>
                    state <= hold;

                when hold => -- wait a moment for the last writes into the buffer to finish
                    state <= dump0;
                    addrb <= 0; -- set read pointer to beginning of buffer

                when dump0 =>
                    addrb <= addrb+1;
                    state <= dump1;

                when dump1 => -- read out the buffer, dump memory locations 0-232 to output
                    if (addrb=232) then
                        state <= dump2;
                    else
                        state <= dump1;
                        addrb <= addrb+1;
                    end if;

                when dump2 =>
                    addrb <= 0;
                    state <= wait4trig;

                when others => 
                    state <= rst;
            end case;
        end if;
    end if;
end process builder_fsm_proc;

-- mux to determine what is written into the output buffer, note this is 72 bits to match ultraram bus

DIN_A <= X"0000000000" & link_id & slot_id & crate_id & detector_id & version_id when (state=h0) else
         X"00" & sample0_timestamp when (state=h1) else
         X"00" & "0000000000" & ch_id & "00" & bline & "00" & threshold & "00" & trigsample when (state=h2) else
         -- add header 3 through header 8 assignments here...
         X"00" & R0(7 downto 0) & R1 & R2 & R3 & R4                    when (state=d0) else -- sample4l ... sample0
         X"00" & R0(1 downto 0) & R1 & R2 & R3 & R4 & R5(13 downto 8)  when (state=d5) else -- sample9l ... sample4h
         X"00" & R0(9 downto 0) & R1 & R2 & R3 & R4(13 downto 2)       when (state=d9) else -- sample13l ... sample9h
         X"00" & R0(3 downto 0) & R1 & R2 & R3 & R4 & R5(13 downto 10) when (state=d14) else -- sample18l ... sample13h
         X"00" & R0(11 downto 0) & R1 & R2 & R3 & R4(13 downto 4)      when (state=d18) else -- sample22l ... sample18h
         X"00" & R0(5 downto 0) & R1 & R2 & R3 & R4 & R5(13 downto 12) when (state=d23) else -- sample27l ... sample22h
         X"00" & R0 & R1 & R2 & R3 & R4(13 downto 6)                   when (state=d27) else -- sample31 ... sample27h
         X"000000000000000000";

BWE_A <= "111111111" when (state=h0) else  -- port A write enable
         "111111111" when (state=h1) else
         "111111111" when (state=h2) else
         "111111111" when (state=h3) else
         "111111111" when (state=h4) else
         "111111111" when (state=h5) else
         "111111111" when (state=h6) else
         "111111111" when (state=h7) else
         "111111111" when (state=h8) else
         "111111111" when (state=d0) else
         "111111111" when (state=d5) else
         "111111111" when (state=d9) else
         "111111111" when (state=d14) else
         "111111111" when (state=d18) else
         "111111111" when (state=d23) else
         "111111111" when (state=d27) else
         "000000000";

EN_A <= '0' when (state=rst) else
        '0' when (state=wait4trig) else
        '0' when (state=w0) else  -- hold enable low during wait states to allow the UltraRAM to "wake up" after SLEEPing
        '0' when (state=w1) else
        '0' when (state=w2) else
        '0' when (state=w3) else
        '0' when (state=w4) else
        '0' when (state=w5) else
        '0' when (state=w6) else
        '0' when (state=hold) else 
        '0' when (state=dump0) else 
        '0' when (state=dump1) else 
        '0' when (state=dump2) else 
        '1';

EN_B <= '1' when (state=dump0) else
        '1' when (state=dump1) else
        '1' when (state=dump2) else
        '0';

SLEEP <= '1' when (state=rst) else
         '1' when (state=wait4trig) else
         '0';

-- UltraRAM address bus is 23 bits, addra and addrb pointers are 8 bit

ADDR_A <= "000000000000000" & std_logic_vector( to_unsigned(addra,8) );
ADDR_B <= "000000000000000" & std_logic_vector( to_unsigned(addrb,8) );

-- URAM288_BASE: 288K-bit High-Density Base Memory Building Block
--               UltraScale
-- Xilinx HDL Language Template, version 2024.1

URAM288_BASE_inst : URAM288_BASE
generic map (
   AUTO_SLEEP_LATENCY => 8,            -- Latency requirement to enter sleep mode
   AVG_CONS_INACTIVE_CYCLES => 10,     -- Average consecutive inactive cycles when is SLEEP mode for power estimation
   BWE_MODE_A => "PARITY_INTERLEAVED", -- Port A Byte write control
   BWE_MODE_B => "PARITY_INTERLEAVED", -- Port B Byte write control
   EN_AUTO_SLEEP_MODE => "FALSE",      -- Enable to automatically enter sleep mode
   EN_ECC_RD_A => "FALSE",             -- Port A ECC encoder
   EN_ECC_RD_B => "FALSE",             -- Port B ECC encoder
   EN_ECC_WR_A => "FALSE",             -- Port A ECC decoder
   EN_ECC_WR_B => "FALSE",             -- Port B ECC decoder
   IREG_PRE_A => "FALSE",              -- Optional Port A input pipeline registers
   IREG_PRE_B => "FALSE",              -- Optional Port B input pipeline registers
   IS_CLK_INVERTED => '0',             -- Optional inverter for CLK
   IS_EN_A_INVERTED => '0',            -- Optional inverter for Port A enable
   IS_EN_B_INVERTED => '0',            -- Optional inverter for Port B enable
   IS_RDB_WR_A_INVERTED => '0',        -- Optional inverter for Port A read/write select
   IS_RDB_WR_B_INVERTED => '0',        -- Optional inverter for Port B read/write select
   IS_RST_A_INVERTED => '0',           -- Optional inverter for Port A reset
   IS_RST_B_INVERTED => '0',           -- Optional inverter for Port B reset
   OREG_A => "FALSE",                  -- Optional Port A output pipeline registers
   OREG_B => "FALSE",                  -- Optional Port B output pipeline registers
   OREG_ECC_A => "FALSE",              -- Port A ECC decoder output
   OREG_ECC_B => "FALSE",              -- Port B output ECC decoder
   RST_MODE_A => "SYNC",               -- Port A reset mode
   RST_MODE_B => "SYNC",               -- Port B reset mode
   USE_EXT_CE_A => "FALSE",            -- Enable Port A external CE inputs for output registers
   USE_EXT_CE_B => "FALSE"             -- Enable Port B external CE inputs for output registers
)
port map (
   DBITERR_A => open,
   DBITERR_B => open,
   DOUT_A => open, -- port A write only
   DOUT_B => DOUT_B, -- port B read only
   SBITERR_A => open,
   SBITERR_B => open,
   ADDR_A => ADDR_A, -- 23-bit input: Port A address
   ADDR_B => ADDR_B, -- 23-bit input: Port B address
   BWE_A => BWE_A,
   BWE_B => "000000000", -- port B read only
   CLK => clock,
   DIN_A => DIN_A,
   DIN_B => X"000000000000000000", -- port B read only
   EN_A => EN_A,
   EN_B => EN_B,
   INJECT_DBITERR_A => '0',
   INJECT_DBITERR_B => '0',
   INJECT_SBITERR_A => '0',
   INJECT_SBITERR_B => '0',
   OREG_CE_A => '0',
   OREG_CE_B => '0',
   OREG_ECC_CE_A => '0',
   OREG_ECC_CE_B => '0',
   RDB_WR_A => '1', -- port A write only
   RDB_WR_B => '0', -- port B read only
   RST_A => '0',
   RST_B => '0',
   SLEEP => SLEEP -- put into low power mode when idle
);

dout  <= DOUT_B(63 downto 0) when (state=dump1) else
         DOUT_B(63 downto 0) when (state=dump2) else
         (others=>'0');

valid <= '1' when (state=dump1) else
         '1' when (state=dump2) else 
         '0';

last <= '1' when (state=dump2) else '0';

end stc3_arch;
