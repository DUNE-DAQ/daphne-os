-- testbench for a single spybuff module

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity spybuff_tb is
end spybuff_tb;

architecture spybuff_tb_arch of spybuff_tb is

component spybuff is
port(
    clock: in std_logic; -- master clock
    reset: in std_logic; -- active high reset async
    trig:  in std_logic; -- trigger pulse sync to clock
    data:  in std_logic_vector(15 downto 0); -- afe data sync to clock

    clka:  in  std_logic;
    addra: in  std_logic_vector(9 downto 0); -- 1k x 32 RAM interface is R/W
	ena:   in  std_logic;
	wea:   in  std_logic;
	dina:  in  std_logic_vector(31 downto 0);
    douta: out std_logic_vector(31 downto 0)  
  );
end component;

constant clka_period:  time := 5.0ns;   -- 200 MHz
constant clock_period: time := 16.0ns;  -- 62.5 MHz

signal reset: std_logic := '1';
signal clka, clock: std_logic := '0';
signal data: std_logic_vector(15 downto 0) := X"0000";
signal trig: std_logic := '0';

signal ena, wea: std_logic := '0';
signal addra: std_logic_vector(9 downto 0) := (others=>'0');
signal dina: std_logic_vector(31 downto 0) := (others=>'0');

begin

reset <= '1', '0' after 96ns;
clock <= not clock after clock_period/2;
clka  <= not clka after clka_period/2;

datasrc_proc: process(clock)
begin
    if falling_edge(clock) then
        if (reset='1') then
            data <= X"0000";
        else
            data <= std_logic_vector( unsigned(data) + 1 );
        end if;
    end if;
end process datasrc_proc;

trig_proc: process
begin
    wait for 5us;

    wait until falling_edge(clock);
    trig <= '1';
    wait until falling_edge(clock);
    trig <= '0';

    wait for 100us;

    wait until falling_edge(clock);
    trig <= '1';
    wait until falling_edge(clock);
    trig <= '0';

    wait;
end process trig_proc;

DUT: spybuff
port map(
    clock => clock,
    reset => reset,
    trig => trig,
    data => data,

    clka => clka,
    addra => addra,
	ena => ena,
	wea => wea,
	dina => dina
    );

read_proc: process
begin
    wait for 80us;
    wait until rising_edge(clka);
    ena <= '1';
    addra <= "0000000000";   
    wait until rising_edge(clka);
    addra <= "0000000001";   
    wait until rising_edge(clka);
    addra <= "0000000010";   
    wait until rising_edge(clka);
    ena <= '0';
    addra <= "0000000000";   
    wait;
end process read_proc;


end spybuff_tb_arch;
