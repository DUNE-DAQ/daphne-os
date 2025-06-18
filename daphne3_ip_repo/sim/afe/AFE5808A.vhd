-- AFE5808A.vhd
-- a very basic BFM (bus functional model) for AFE5808A SPI interface
-- commands are 24 bits: 8 bit address followed by 16 bit data, sent MSb first.
-- this BFM assumes that that AFE SPI interface is in read mode, SDOUT is active
-- also this assumes that SEN goes high after each operation
-- Jamieson Olsen <jamieson@fnal.gov>

library ieee,std;
use ieee.std_logic_1164.all;
use std.textio;

entity AFE5808A is
port(
    rst: in std_logic;
    pdn: in std_logic;
    sclk: in std_logic; -- 20MHz max
    sdata: in std_logic;
    sen: in std_logic;
    sdout: out std_logic -- Z when SEN is high
);
end AFE5808A;

architecture AFE5808A_arch of AFE5808A is

signal addr: std_logic_vector(7 downto 0) := (others=>'0');
signal data_new, data_old: std_logic_vector(15 downto 0) := (others=>'0');

begin

spi_transactor: process
begin
    sdout <= '0';
    wait until falling_edge(sen); -- each SPI transaction must begin with falling SEN

    for i in 7 downto 0 loop
        wait until rising_edge(sclk);
        addr(i) <= sdata;
    end loop;

    for i in 15 downto 0 loop
        wait until rising_edge(sclk);
        data_new(i) <= sdata;
        sdout <= data_old(i);
    end loop;

    wait until rising_edge(sen); -- each SPI transaction must end with rising SEN
    data_old <= data_new;
    report "AFE SPI access register " & to_hstring(addr) & " data = " & to_hstring(data_new);

end process spi_transactor;

end AFE5808A_arch;