-- ADS1261.vhd
-- a very basic BFM (bus functional model) for current monitor chip ADS1261IRHBT
-- This SPI chip is unusual in that the number of bits to transfer is variable,
-- depending on the command being issued. Most commands are 16 bits but if 32 bits
-- are sent then it assumes CRC mode is in use.
-- 
-- Jamieson Olsen <jamieson@fnal.gov>

-- needs updating!!!

library ieee,std;
use ieee.std_logic_1164.all;
use std.textio;

entity ADS1261 is
port(
    sclk: in std_logic; -- 10MHz max
    din:  in std_logic;
    cs_n: in std_logic;
    dout: out std_logic;
    drdyn: out std_logic
);
end ADS1261;

architecture ADS1261_arch of ADS1261 is

signal din_reg: std_logic_vector(47 downto 0) := (others=>'0');
constant dout_reg: std_logic_vector(47 downto 0) := X"FF00DEADBEEF"; -- static output data

begin

spi_transactor: process
begin
    dout <= '0';
    wait until falling_edge(cs_n); 

    for i in 47 downto 0 loop
        wait until rising_edge(sclk);
        din_reg(i) <= din;
    end loop;

    wait until rising_edge(sclk); -- each SPI transaction must end with rising SEN
    -- data_old <= data_new;
    -- report "AFE SPI access register " & to_hstring(addr) & " data = " & to_hstring(data_new);

end process spi_transactor;

drdyn <= '0';

end ADS1261_arch;