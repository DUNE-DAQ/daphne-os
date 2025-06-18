-- a very simple testbench for testing just one febit3 module...
-- jamieson olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library unisim;
use unisim.vcomponents.all;

entity febit3_testbench is
end febit3_testbench;

architecture febit3_testbench_arch of febit3_testbench is

component AFE5808 -- simple model of one AFE chip
port(
    clkadc_p, clkadc_n: in std_logic; -- assumes 62.5MHz, period 16.0ns    
    afe_p: out std_logic_vector(8 downto 0); -- FCLK is bit 8
    afe_n: out std_logic_vector(8 downto 0)
  );
end component;

component febit3 is
port(
    din_p, din_n: in std_logic;  -- LVDS data input from AFE chip
    clk500: in std_logic;  -- fast bit clock 500MHz
    clk125: in std_logic;  -- byte clock 125MHz
    clock: in std_logic;  -- word/master clock 62.5MHz
    idelay_load: in std_logic;                     
    idelay_cntvaluein: in std_logic_vector(8 downto 0);
    idelay_en_vtc: in std_logic;  -- IDELAY temperature/voltage compensation (async)
    iserdes_reset: in std_logic;
    iserdes_bitslip: in std_logic_vector(3 downto 0);
    dout: out std_logic_vector(15 downto 0)
  );
end component;

constant clock_period:    time := 16.0ns;  -- 62.5 MHz
constant clk125_period:   time := 8.0ns;   -- 125 MHz
constant clk500_period:   time := 2.0ns;   -- 500 MHz

signal iserdes_reset: std_logic := '1';
signal clock, clk125, clk500: std_logic := '1';

signal afe_p, afe_n: std_logic_vector(8 downto 0);
signal clkadc_p, clkadc_n: std_logic;

signal cntvalue: std_logic_vector(8 downto 0) := "000000000";
signal load: std_logic := '0';

begin

iserdes_reset <= '1', '0' after 96ns;

clock  <= not clock  after clock_period/2;
clk125 <= not clk125 after clk125_period/2;
clk500 <= not clk500 after clk500_period/2;

obufds_inst: OBUFDS
generic map ( IOSTANDARD => "DEFAULT", SLEW => "FAST" )
port map ( I => clock, O => clkadc_p, OB => clkadc_n );

afe_inst: AFE5808
port map(
    clkadc_p => clkadc_p,
    clkadc_n => clkadc_n,
    afe_p => afe_p, 
    afe_n => afe_n
);

febit3_inst: febit3
port map(
    din_p => afe_p(8), -- 8=fclk 7=countup
    din_n => afe_n(8),
    clock => clock,
    clk125 => clk125,
    clk500 => clk500,

    idelay_load => load,
    idelay_cntvaluein => cntvalue, -- delay line tap number
    idelay_en_vtc => '0', -- keep this low while we're messing with idelay 

    iserdes_reset  => iserdes_reset,
    iserdes_bitslip => "1000"
  );

-- sweep delay tap numbers and find the bit edges

bitsweep: process
begin

    wait for 1us;

    for d in 0 to 511 loop -- do the timing scan

        wait until falling_edge(clk125);
        cntvalue <= std_logic_vector( to_unsigned(d,9) );

        wait until falling_edge(clk125);    
        load <= '1';

        wait until falling_edge(clk125);
        load <= '0';

        wait for 500ns;

    end loop;

    wait for 10us;

    wait until falling_edge(clk125);
    cntvalue <= std_logic_vector( to_unsigned(112,9) ); -- let's pick the sweet spot 
    wait until falling_edge(clk125);    
    load <= '1';
    wait until falling_edge(clk125);
    load <= '0';

    wait;

end process bitsweep;

end febit3_testbench_arch;
