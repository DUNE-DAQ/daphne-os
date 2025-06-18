-- spim_afe1.vhd
-- a simple SPI master for driving an AFE5808A
--
-- drop SEN and raises it after each transaction
-- AFE samples MOSI on rising edge SCLK
-- This master samples MISO on falling edge of SCLK
-- when idle: csn=1, sclk=1, mosi=0
--
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity spim_afe1 is
generic( CLKDIV: integer := 8 ); -- SPI sclk frequency = clock frequency / CLKDIV
port(
    clock: in std_logic;
    reset: in std_logic;
    din: in std_logic_vector(23 downto 0);
    we: in std_logic;
    dout: out std_logic_vector(23 downto 0);
    busy: out std_logic;

    -- spi device signals
    sclk: out std_logic; -- max 20MHz 
    sen:  out std_logic;
    mosi: out std_logic; -- aka SDATA
    miso: in std_logic   -- aka SDOUT
);
end spim_afe1;

architecture spim_afe1_arch of spim_afe1 is

type state_type is (rst, idle, dlo, dhi, done);
signal state: state_type;

signal din_reg: std_logic_vector(23 downto 0) := (others=>'0');

signal bit_count: integer range 0 to 23;
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

when idle => -- wait for the host to write something
    if (we='1') then
        din_reg <= din; -- load the shift register: addr(7..0) + data(15..0)
        clk_count <= 0;
        bit_count <= 23;
        state <= dlo;
    else
        state <= idle;  
    end if;

when dlo => -- sclk low cycle
    if (clk_count=CLKDIV/2) then
        state <= dhi;
        clk_count <= 0;
    else
        state <= dlo;
        clk_count <= clk_count + 1;
    end if;

when dhi => -- sclk hi cycle
    if (clk_count=CLKDIV/2) then
        din_reg <= din_reg(22 downto 0) & miso; -- shift & sample on falling edge SCLK
        if (bit_count=0) then -- finished last the last bit
            state <= idle;
        else -- done with this bit, but there are more bits to send
            clk_count <= 0;
            bit_count <= bit_count - 1;
            state <= dlo;
        end if;
    else
        clk_count <= clk_count + 1;
        state <= dhi;
    end if;

when others =>
    state <= rst;

end case;
    
        end if;
    end if;
end process fsm_proc;

sen <= '0' when (state=dhi) else
       '0' when (state=dlo) else
       '1';

sclk <= '0' when (state=dlo) else '1';

mosi <= din_reg(23) when (state=dhi) else 
        din_reg(23) when (state=dlo) else
        '0';

dout <= din_reg;

busy <= '0' when (state=idle) else '1';

end spim_afe1_arch;

