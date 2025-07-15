-- testbench for the 40 channel self triggered sender for DAPHNE3/DAPHNE_MEZZ
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.std_logic_textio.all;
use std.textio.all;
use work.daphne3_package.all;

entity st40_top_testbench is
end st40_top_testbench;

architecture st40_top_testbench_arch of st40_top_testbench is

component st40_top
generic( baseline_runlength: integer := 256 );
port(
    link_id: std_logic_vector(5 downto 0);
    slot_id: in std_logic_vector(3 downto 0);
    crate_id: in std_logic_vector(9 downto 0);
    detector_id: in std_logic_vector(5 downto 0);
    version_id: in std_logic_vector(5 downto 0);
    threshold: in std_logic_vector(9 downto 0);

    clock: in std_logic; -- main clock 62.5 MHz
    reset: in std_logic;
    timestamp: in std_logic_vector(63 downto 0);
    enable: in std_logic_vector(39 downto 0);
    forcetrig: in std_logic;
	din: in array_40x14_type; -- ALL AFE channels feed into this module
    d0: out std_logic_vector(63 downto 0); -- output to single channel 10G sender
    d0_valid: out std_logic;
    d0_last: out std_logic
);
end component;

signal reset: std_logic := '1';
signal clock: std_logic := '0';
signal timestamp: std_logic_vector(63 downto 0) := X"0000000000000000";
signal din: array_40x14_type;

begin

clock <= not clock after 8.000 ns; --  62.500 MHz
reset <= '1', '0' after 96ns;

transactor: process(clock)
    file test_vector: text open read_mode is "$dsn/src/selftrig/st40_top_testbench.txt";
    variable row: line;
    variable v_ts: std_logic_vector(31 downto 0);  -- hex string 8 char
    variable v_din: array_40x16_type; -- hex string 4 char / 16 bits per channel
begin 
    if rising_edge(clock) then
   
        if (not endfile(test_vector)) then
            readline(test_vector,row);
        end if;

        hread(row, v_ts);
        for i in 0 to 39 loop
          hread(row, v_din(i));
        end loop;

        timestamp <= X"00000000" & v_ts;
        for i in 0 to 39 loop
            din(i) <= v_din(i)(13 downto 0);  -- cut down to 14 bits
        end loop;

    end if;    
end process transactor;

DUT: st40_top
generic map ( baseline_runlength => 64 )
port map(
    link_id => "000001",
    slot_id => "0011",
    crate_id => "0000100100",
    detector_id => "100000",
    version_id => "001100",
    threshold => "1000000000", -- threshold is 512 counts above calculated baseline
    clock => clock,
    reset => reset,
    timestamp => timestamp,
    enable => X"FFFFFFFFFF",
    forcetrig => '0',
	din => din
);

end st40_top_testbench_arch;