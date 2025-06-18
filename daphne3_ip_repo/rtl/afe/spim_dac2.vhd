-- spim_dac2.vhd
-- a simple SPI master for writing to a pair of DAC chips (AD5327) daisy chained
-- the 2 DAC chips are written in one shot of 32 bits, this master cannot write just to one DAC chip.
-- there is no readback as the SDO pin of the last device in the chain is not connected.
-- when this module is idle: SCLK, LDAC_N, and SYNC_N are all HIGH; MOSI is LOW.
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity spim_dac2 is
generic( CLKDIV: integer := 8 ); -- SCLK frequency = clock frequency / CLKDIV
port(
    clock: in std_logic;
    reset: in std_logic;
    din: in std_logic_vector(31 downto 0);
    we: in std_logic;
    busy: out std_logic;

    -- spi device signals
    sclk: out std_logic;
    mosi: out std_logic;
    ldac_n: out std_logic;
    sync_n: out std_logic
);
end spim_dac2;

architecture spim_dac2_arch of spim_dac2 is

type state_type is (rst, idle, dhi, dlo, sync, load0, load1);
signal state: state_type;

signal din_reg: std_logic_vector(31 downto 0) := (others=>'0');

signal bit_count: integer range 0 to 31;
signal clk_count: integer range 0 to CLKDIV;

begin

fsm_proc: process(clock)
begin
    if rising_edge(clock) then
        if (reset='1') then
            state <= rst;
        else
           
case state is 

when rst =>
    state <= idle;

when idle =>
    if (we='1') then
        din_reg(31 downto 0) <= din; 
        clk_count <= 0;
        bit_count <= 31;
        state <= dhi;
    else
        state <= idle;  
    end if;

when dhi => -- sclk high cycle
    if (clk_count=CLKDIV/2) then
        state <= dlo;
        clk_count <= 0;
    else
        state <= dhi;
        clk_count <= clk_count + 1;
    end if;

when dlo => -- sclk low cycle
    if (clk_count=CLKDIV/2) then
        din_reg <= din_reg(30 downto 0) & '0'; -- shift data register left one bit
        if (bit_count=0) then -- we have just finished shifting out the last bit, get ready to load
            state <= sync;
            clk_count <= 0; 
        else -- done with this bit, but there are more bits to send, shift data and make another sclk high pulse
            clk_count <= 0;
            bit_count <= bit_count - 1;
            state <= dhi;
        end if;
    else
        clk_count <= clk_count + 1;
        state <= dlo;
    end if;

when sync => -- sclk is still low, let sync_n go high, then release sclk and let it go high
    if (clk_count=CLKDIV) then
        clk_count <= 0; 
        state <= load0;
    else
        clk_count <= clk_count + 1;
        state <= sync;
    end if;

when load0 => -- wait here for a little while... 
    if (clk_count=CLKDIV) then
        state <= load1;
        clk_count <= 0;
    else
        state <= load0;
        clk_count <= clk_count + 1;
    end if;

when load1 => -- pulse ldac_n low to load the DACs 
    if (clk_count=CLKDIV) then
        state <= idle;
    else
        state <= load1;
        clk_count <= clk_count + 1;
    end if;

when others =>
    state <= rst;

end case;
    
        end if;
    end if;
end process fsm_proc;

-- output equations

ldac_n <= '0' when (state=load1) else '1';

sync_n <= '0' when (state=dhi) else
          '0' when (state=dlo) else
          '1';

sclk <= '0' when (state=dlo) else
        '0' when (state=sync) else 
        '1';

mosi <= '0' when (state=idle) else din_reg(31); -- serial data is shifted out MSb first

busy <= '0' when (state=idle) else '1';

end spim_dac2_arch;
