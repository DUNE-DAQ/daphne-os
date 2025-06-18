-- febit3.vhd
--
-- DAPHNE_V3 FPGA AFE front end for one bit. This module does the following:
-- single LVDS receiver with IDELAYE3 and a single ISERDESE3 in DDR 8:1 mode
-- The input LVDS stream must be 16 bit mode, LSb first.
-- this is a TOTAL REDESIGN around the UltraScale/Ultrascale+ ISERDESE3 which does away with 
-- the BITSLIP feature. The bitslip functionality is now done in the FPGA fabric.
--
-- The three clocks must be frequency locked and have the rising edges aligned.
--
-- Xilinx recommends having a single MMCM output (500MHz) drive a BUFG to make clk500
-- and use that same MMCM ouput to drive a BUFGCE_DIV (BUFGCE_DIVIDE=4) to make the 125MHz clock.
-- Apparently this is better than using another MMCM output to make the 125MHz clock.
-- I think that's kludgy but whatever...
--
-- NOTE idelay_en_vtc must be LOW when loading IDELAY tap values.
--
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity febit3 is
port(
    din_p, din_n: in std_logic;  -- LVDS data input from AFE chip
    clock: in std_logic;   -- word/master clock 62.5MHz
    clk500: in std_logic;  -- fast bit clock 500MHz
    clk125: in std_logic;  -- byte clock 125MHz
    idelay_load: in std_logic;  -- load the IDELAY value (clk125)
    idelay_cntvaluein: in std_logic_vector(8 downto 0); -- IDELAY tap value (clk125)
    idelay_en_vtc: in std_logic;  -- IDELAY temperature/voltage comp (async)
    iserdes_reset: in std_logic;  -- reset for ISERDES (async)
    iserdes_bitslip: in std_logic_vector(3 downto 0); -- word alignment value (clock)
    dout: out std_logic_vector(15 downto 0)
  );
end febit3;

architecture febit3_arch of febit3 is

    -- signal clk500_b: std_logic;
    signal din_ibuf, din_delayed : std_logic;
    signal q, q_reg, q2_reg, q3_reg: std_logic_vector(7 downto 0);
    signal dout_reg: std_logic_vector(15 downto 0);
    
begin

    -- LVDS input buffer with internal termination

    IBUFDS_inst: IBUFDS
    generic map(
        DIFF_TERM    => TRUE,
        IBUF_LOW_PWR => FALSE,
        IOSTANDARD   => "LVDS"
    )
    port map(
        I  => din_p,
        IB => din_n,
        O  => din_ibuf
    );

-- adjustable delay 512 taps and the loading of the delay value is 
-- done synchronously with the clkdiv clock when load=1 as described in UG571 

-- IDELAYCTRL needs a refclk in the range of 300MHz to 800MHz, we use 500MHz because we have it available
-- One IDELAYCTRL module (located one level up) covers all IDELAYE3's used in this design.

IDELAYE3_inst : IDELAYE3
generic map(
    CASCADE => "NONE",               -- Cascade setting (MASTER, NONE, SLAVE_END, SLAVE_MIDDLE)   
    DELAY_FORMAT => "COUNT",         -- Units of the DELAY_VALUE (COUNT, TIME)   
    DELAY_SRC => "IDATAIN",          -- Delay input (DATAIN, IDATAIN)   
    DELAY_TYPE => "VAR_LOAD",        -- Set the type of tap delay line (FIXED, VARIABLE, VAR_LOAD)   
    DELAY_VALUE => 0,                -- Input delay value setting   
    IS_CLK_INVERTED => '0',          -- Optional inversion for CLK   
    IS_RST_INVERTED => '0',          -- Optional inversion for RST   
    REFCLK_FREQUENCY => 500.0,       -- IDELAYCTRL clock input frequency in MHz (200.0-800.0)   
    SIM_DEVICE => "ULTRASCALE_PLUS", -- Set the device version for simulation functionality (ULTRASCALE, ULTRASCALE_PLUS, ULTRASCALE_PLUS_ES1, ULTRASCALE_PLUS_ES2)
    UPDATE_MODE => "ASYNC"           -- Determines when updates to the delay will take effect (ASYNC, MANUAL, SYNC)
)
port map(
    CASC_OUT => open,           -- 1-bit output: Cascade delay output to ODELAY input cascade 
    CNTVALUEOUT => open,        -- 9-bit output: Counter value output   
    DATAOUT => din_delayed,     -- 1-bit output: Delayed data output 
    CASC_IN => '0',             -- 1-bit input: Cascade delay input from slave ODELAY CASCADE_OUT
    CASC_RETURN => '0',         -- 1-bit input: Cascade delay returning from slave ODELAY DATAOUT   
    CE => '0',                  -- 1-bit input: Active-High enable increment/decrement input   
    CLK => clk125,              -- 1-bit input: Clock input   
    CNTVALUEIN => idelay_cntvaluein, -- 9-bit input: Counter value input   
    DATAIN => '0',              -- 1-bit input: Data input from the logic   
    EN_VTC => idelay_en_vtc,    -- 1-bit input: Keep delay constant over VT   
    IDATAIN => din_ibuf,        -- 1-bit input: Data input from the IOBUF   
    INC => '0',                 -- 1-bit input: Increment / Decrement tap delay input   
    LOAD => idelay_load,        -- 1-bit input: Load DELAY_VALUE input
    RST => '0'                  -- 1-bit input: Asynchronous Reset to the DELAY_VALUE
);

-- NOTE: CLK and CLK_B can use the same clock (clk500) if IS_CLK_INVERTED=0 and IS_CLK_B_INVERTED=1

ISERDESE3_inst : ISERDESE3
generic map(
    DATA_WIDTH => 8,                 -- Parallel data width (4,8)
    FIFO_ENABLE => "FALSE",          -- Enables the use of the FIFO   
    FIFO_SYNC_MODE => "FALSE",       -- Always set to FALSE. TRUE is reserved for later use.   
    IS_CLK_B_INVERTED => '1',        -- Optional inversion for CLK_B
    IS_CLK_INVERTED => '0',          -- Optional inversion for CLK   
    IS_RST_INVERTED => '0',          -- Optional inversion for RST   
    SIM_DEVICE => "ULTRASCALE_PLUS"  -- Set the device version for simulation functionality (ULTRASCALE, ULTRASCALE_PLUS, ULTRASCALE_PLUS_ES1, ULTRASCALE_PLUS_ES2)
)
port map(
    FIFO_EMPTY => open,      -- 1-bit output: FIFO empty flag   
    INTERNAL_DIVCLK => open, -- 1-bit output: Internally divided down clock used when FIFO is disabled (do not connect)   
    Q => Q,                  -- 8-bit registered output   
    CLK => clk500,           -- 1-bit input: High-speed clock   
    CLK_B => clk500,         -- 1-bit input: Inversion of High-speed clock CLK, assumes IS_CLK_B_INVERTED=1
    CLKDIV => clk125,        -- 1-bit input: Divided Clock
    D => din_delayed,        -- 1-bit input: Serial Data Input   
    FIFO_RD_CLK => clk125,   -- 1-bit input: FIFO read clock 
    FIFO_RD_EN => '1',       -- 1-bit input: Enables reading the FIFO when asserted
    RST => iserdes_reset     -- 1-bit input: Asynchronous Reset
);

-- now we have to do the bitslip stuff here, manually, since this functionality is no longer in the ISERDESE3 module...

byte_proc: process(clk125)
begin
    if rising_edge(clk125) then
        q_reg <= q;
        q2_reg <= q_reg;
        q3_reg <= q2_reg;
    end if;
end process byte_proc;

-- "bitslip" is done here...
--
-- the AFE chip must be configured to send LSB first in 16 bit mode, which means that
-- two extra zeros (represented here by ..) are inserted at the LSb end of the word:
--
--      ..0123456789ABCD ..0123456789ABCD ..0123456789ABCD ..
-- Q             X 543210.. X DCBA9876 X 543210.. X DCBA9876 X 543210.. X DCBA9876 X 
-- 

clock_proc: process(clock)
begin
    if rising_edge(clock) then
        case iserdes_bitslip is
            when "0000" => dout_reg <= q(7 downto 0) & q_reg(7 downto 0);
            when "0001" => dout_reg <= q(6 downto 0) & q_reg(7 downto 0) & q2_reg(7);
            when "0010" => dout_reg <= q(5 downto 0) & q_reg(7 downto 0) & q2_reg(7 downto 6);
            when "0011" => dout_reg <= q(4 downto 0) & q_reg(7 downto 0) & q2_reg(7 downto 5);
            when "0100" => dout_reg <= q(3 downto 0) & q_reg(7 downto 0) & q2_reg(7 downto 4);
            when "0101" => dout_reg <= q(2 downto 0) & q_reg(7 downto 0) & q2_reg(7 downto 3);
            when "0110" => dout_reg <= q(1 downto 0) & q_reg(7 downto 0) & q2_reg(7 downto 2);
            when "0111" => dout_reg <= q(0)          & q_reg(7 downto 0) & q2_reg(7 downto 1);
            when "1000" => dout_reg <=                 q_reg(7 downto 0) & q2_reg(7 downto 0);
            when "1001" => dout_reg <=                 q_reg(6 downto 0) & q2_reg(7 downto 0) & q3_reg(7);
            when "1010" => dout_reg <=                 q_reg(5 downto 0) & q2_reg(7 downto 0) & q3_reg(7 downto 6);
            when "1011" => dout_reg <=                 q_reg(4 downto 0) & q2_reg(7 downto 0) & q3_reg(7 downto 5);
            when "1100" => dout_reg <=                 q_reg(3 downto 0) & q2_reg(7 downto 0) & q3_reg(7 downto 4);
            when "1101" => dout_reg <=                 q_reg(2 downto 0) & q2_reg(7 downto 0) & q3_reg(7 downto 3);
            when "1110" => dout_reg <=                 q_reg(1 downto 0) & q2_reg(7 downto 0) & q3_reg(7 downto 2);
            when others => dout_reg <=                 q_reg(0)          & q2_reg(7 downto 0) & q3_reg(7 downto 1);
        end case;
    end if;
end process clock_proc;

dout <= dout_reg;

end febit3_arch;
